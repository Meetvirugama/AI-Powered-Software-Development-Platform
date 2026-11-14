"""Run available static-analysis tools and normalize their findings."""

import asyncio
import concurrent.futures
import inspect
import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from app.core.secret_redaction import redact, redact_obj

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticFinding:
    rule_id: str
    severity: str
    message: str
    file_path: str
    line_number: int | None = None
    scanner: str = "unknown"
    metadata: dict[str, Any] | None = None


class StaticReviewer:
    VALID_SEVERITIES: ClassVar[set[str]] = {"critical", "high", "medium", "low", "info"}

    def normalize_finding(
        self, finding: dict[str, Any], *, scanner: str
    ) -> StaticFinding:
        rule_id = str(finding.get("rule_id") or finding.get("code") or "unknown")
        raw_message = str(finding.get("message") or "No message provided")
        message = redact(raw_message)
        file_path = str(finding.get("file_path") or finding.get("filename") or "")

        raw_severity = str(finding.get("severity") or "info").lower()
        severity = (
            raw_severity if raw_severity in self.VALID_SEVERITIES else "info"
        )

        raw_line = finding.get("line_number", finding.get("line"))
        line_number = (
            raw_line
            if isinstance(raw_line, int)
            and not isinstance(raw_line, bool)
            and raw_line > 0
            else None
        )

        excluded = {
            "secret", "secret_value", "password", "token", "api_key",
            "authorization", "raw_secret", "rule_id", "code", "message",
            "file_path", "filename", "severity", "line_number", "line",
        }
        safe_metadata = {
            key: redact_obj(value)
            for key, value in finding.items()
            if key.lower() not in excluded
        }

        return StaticFinding(
            rule_id=rule_id,
            severity=severity,
            message=message,
            file_path=file_path,
            line_number=line_number,
            scanner=scanner,
            metadata=safe_metadata or None,
        )

    def normalize_findings(
        self, findings: list[dict[str, Any]], *, scanner: str
    ) -> list[StaticFinding]:
        return [
            self.normalize_finding(finding, scanner=scanner)
            for finding in findings
        ]

    def review(
        self, findings: list[dict[str, Any]], *, scanner: str
    ) -> list[dict[str, Any]]:
        return [
            asdict(item)
            for item in self.normalize_findings(findings, scanner=scanner)
        ]

    SUPPORTED_SCANNERS: ClassVar[set[str]] = {"ruff", "bandit", "eslint", "biome"}

    def detect_scanners_for_file(self, file_path: str, repo_root: str | None = None) -> list[str]:
        """Detect recommended static scanners based on file type and repository config."""
        lower = (file_path or "").lower()
        if lower.endswith(".py"):
            return ["ruff", "bandit"]
        if lower.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
            if repo_root:
                if os.path.exists(os.path.join(repo_root, "biome.json")) or os.path.exists(os.path.join(repo_root, "biome.jsonc")):
                    return ["biome"]
                if any(os.path.exists(os.path.join(repo_root, f)) for f in (".eslintrc", ".eslintrc.json", ".eslintrc.js", "eslint.config.js", "eslint.config.mjs")):
                    return ["eslint"]
            return ["eslint", "biome"]
        return []

    def _sanitize_target_paths(self, target_path: str | Sequence[str]) -> list[str]:
        """Validate and sanitize one or more target file paths against command and option injection."""
        if isinstance(target_path, str):
            raw_targets = [target_path]
        elif isinstance(target_path, (list, tuple, set)):
            raw_targets = list(target_path)
        else:
            raise TypeError(
                f"target_path must be a string or sequence of strings, got {type(target_path).__name__}"
            )

        if not raw_targets:
            raise ValueError("Unsafe or option-like target_path rejected: empty target list")

        cleaned_targets: list[str] = []
        for p in raw_targets:
            cleaned = (p or "").strip()
            if not cleaned or cleaned.startswith("-") or "\x00" in cleaned:
                raise ValueError(f"Unsafe or option-like target_path rejected: {p!r}")
            cleaned_targets.append(cleaned)

        return cleaned_targets

    def _build_scanner_command(self, scanner: str, cleaned_targets: list[str]) -> list[str]:
        """Construct a hardened CLI invocation with targets separated by '--'."""
        commands = {
            "ruff": [
                sys.executable, "-m", "ruff", "check",
                "--output-format", "json", "--", *cleaned_targets,
            ],
            "bandit": [
                sys.executable, "-m", "bandit", "-f", "json",
                "-r", "--", *cleaned_targets,
            ],
            "eslint": [
                "npx", "--no-install", "eslint", "--format", "json", "--no-color", "--", *cleaned_targets,
            ],
            "biome": [
                "npx", "--no-install", "@biomejs/biome", "lint", "--reporter=json", "--", *cleaned_targets,
            ],
        }

        if scanner not in commands:
            raise ValueError(f"Unsupported scanner: {scanner}")

        return commands[scanner]

    def _get_safe_env(self) -> dict[str, str]:
        """Provide a minimal, sanitized execution environment."""
        safe_env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "NODE_ENV": "production",
        }
        if "VIRTUAL_ENV" in os.environ:
            safe_env["VIRTUAL_ENV"] = os.environ["VIRTUAL_ENV"]
        return safe_env

    def _parse_scanner_output(
        self,
        scanner: str,
        stdout: str,
        stderr: str,
        returncode: int,
        cleaned_targets: list[str],
        cwd: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse raw scanner stdout JSON into normalized static review findings."""
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            detail = redact((stderr or stdout or "").strip())
            if returncode != 0:
                raise RuntimeError(f"{scanner} failed: {detail}") from exc
            raise RuntimeError(
                f"{scanner} returned invalid JSON output"
            ) from exc

        fallback_path = cleaned_targets[0] if len(cleaned_targets) == 1 else ""

        if scanner == "ruff":
            if not isinstance(payload, list):
                raise RuntimeError("Ruff returned an unexpected JSON format")

            findings = [
                {
                    "rule_id": item.get("code"),
                    "severity": "low",
                    "message": redact(str(item.get("message") or "")),
                    "file_path": item.get("filename") or fallback_path,
                    "line_number": (item.get("location") or {}).get("row"),
                }
                for item in payload
            ]
        elif scanner == "bandit":
            raw_findings = payload.get("results", [])
            findings = [
                {
                    "rule_id": item.get("test_id"),
                    "severity": str(
                        item.get("issue_severity", "low")
                    ).lower(),
                    "message": redact(str(item.get("issue_text") or "")),
                    "file_path": item.get("filename") or fallback_path,
                    "line_number": item.get("line_number"),
                }
                for item in raw_findings
            ]
        elif scanner == "eslint":
            if not isinstance(payload, list):
                raise RuntimeError("ESLint returned an unexpected JSON format")
            findings = []
            for file_entry in payload:
                f_path = file_entry.get("filePath") or fallback_path
                for msg in file_entry.get("messages", []):
                    sev = "high" if msg.get("severity") == 2 else "low"
                    findings.append({
                        "rule_id": msg.get("ruleId") or "eslint-rule",
                        "severity": sev,
                        "message": redact(str(msg.get("message") or "")),
                        "file_path": f_path,
                        "line_number": msg.get("line"),
                    })
        elif scanner == "biome":
            diagnostics = payload.get("diagnostics", []) if isinstance(payload, dict) else []
            findings = []
            for diag in diagnostics:
                loc = diag.get("location") or {}
                f_path = (loc.get("path") or {}).get("file") or fallback_path
                l_num = (loc.get("lines") or {}).get("start")

                # Derive line number if lines.start is missing but span is available
                if l_num is None:
                    span = loc.get("span")
                    if isinstance(span, (list, tuple)) and len(span) >= 1 and isinstance(span[0], int):
                        start_offset = span[0]
                        source_code = loc.get("sourceCode") or diag.get("sourceCode")
                        if not source_code:
                            candidate_file = f_path
                            if cwd and not os.path.isabs(candidate_file):
                                candidate_file = os.path.join(cwd, candidate_file)
                            if os.path.isfile(candidate_file):
                                try:
                                    with open(candidate_file, "r", encoding="utf-8", errors="replace") as f:
                                        source_code = f.read()
                                except OSError:
                                    pass
                        if source_code and 0 <= start_offset <= len(source_code):
                            l_num = source_code[:start_offset].count("\n") + 1

                sev = "high" if str(diag.get("severity", "")).lower() == "error" else "low"
                findings.append({
                    "rule_id": diag.get("category") or "biome-lint",
                    "severity": sev,
                    "message": redact(str(diag.get("description") or diag.get("message") or "")),
                    "file_path": f_path,
                    "line_number": l_num,
                })
        else:
            findings = []

        return self.review(findings, scanner=scanner)

    def _group_files_by_scanner(
        self,
        modified_files: Sequence[str],
        scanners: tuple[str, ...] | list[str] | None = None,
        repo_root: str | None = None,
    ) -> dict[str, list[str]]:
        """Group modified files by matching static scanner to amortize subprocess launches."""
        grouped: dict[str, list[str]] = {}
        for file_path in modified_files:
            if scanners is not None:
                active_scanners = list(scanners)
            else:
                active_scanners = self.detect_scanners_for_file(file_path, repo_root=repo_root)

            for sc in active_scanners:
                if sc not in grouped:
                    grouped[sc] = []
                if file_path not in grouped[sc]:
                    grouped[sc].append(file_path)
        return grouped

    def review_modified_files(
        self,
        modified_files: list[str],
        ai_findings: list[dict[str, Any]] | None = None,
        scanners: tuple[str, ...] | None = None,
        repo_root: str | None = None,
        parallel: bool = True,
        batch: bool = True,
    ) -> dict[str, Any]:
        """Run static scanners on modified files and combine their findings with AI findings.

        When batch=True (default), file targets are aggregated per scanner and passed in a
        single CLI invocation after '--' (e.g. ruff check -- target1.py target2.py),
        amortizing process spawn overhead from O(M * S) down to O(S).
        When parallel=True (default), independent scanner executions run concurrently via
        ThreadPoolExecutor.
        """
        static_findings: list[dict[str, Any]] = []

        if not modified_files:
            combined = list(ai_findings or [])
            return {
                "findings": combined,
                "static_findings_count": 0,
                "ai_findings_count": len(ai_findings or []),
                "total_findings": len(combined),
            }

        if not batch:
            # Fallback per-file execution loop (legacy unbatched mode)
            for file_path in modified_files:
                if scanners is not None:
                    file_scanners = list(scanners)
                else:
                    file_scanners = self.detect_scanners_for_file(file_path, repo_root=repo_root)

                for scanner in file_scanners:
                    try:
                        if repo_root is not None:
                            static_findings.extend(
                                self.run_scanner(scanner, file_path, cwd=repo_root)
                            )
                        else:
                            static_findings.extend(
                                self.run_scanner(scanner, file_path)
                            )
                    except (RuntimeError, ValueError):
                        continue
        else:
            grouped = self._group_files_by_scanner(
                modified_files, scanners=scanners, repo_root=repo_root
            )

            def _run_single_scanner(sc: str, targets: list[str]) -> list[dict[str, Any]]:
                try:
                    target_arg: str | list[str] = targets[0] if len(targets) == 1 else targets
                    if repo_root is not None:
                        return self.run_scanner(sc, target_arg, cwd=repo_root)
                    return self.run_scanner(sc, target_arg)
                except (RuntimeError, ValueError):
                    return []

            if parallel and len(grouped) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(grouped), 8)) as executor:
                    futures = {
                        executor.submit(_run_single_scanner, sc, targets): sc
                        for sc, targets in grouped.items()
                    }
                    scanner_results: dict[str, list[dict[str, Any]]] = {}
                    for fut in concurrent.futures.as_completed(futures):
                        sc = futures[fut]
                        scanner_results[sc] = fut.result()
                    for sc in grouped:
                        static_findings.extend(scanner_results.get(sc, []))
            else:
                for sc, targets in grouped.items():
                    static_findings.extend(_run_single_scanner(sc, targets))

        combined_findings = [
            *static_findings,
            *(ai_findings or []),
        ]

        return {
            "findings": combined_findings,
            "static_findings_count": len(static_findings),
            "ai_findings_count": len(ai_findings or []),
            "total_findings": len(combined_findings),
        }

    async def review_modified_files_async(
        self,
        modified_files: list[str],
        ai_findings: list[dict[str, Any]] | None = None,
        scanners: tuple[str, ...] | None = None,
        repo_root: str | None = None,
    ) -> dict[str, Any]:
        """Asynchronously run static scanners on modified files using non-blocking subprocesses.

        All applicable scanner subprocesses execute concurrently via asyncio.gather, reducing
        total scan latency from sum(scanner_latencies) to max(scanner_latencies).
        """
        static_findings: list[dict[str, Any]] = []

        if not modified_files:
            combined = list(ai_findings or [])
            return {
                "findings": combined,
                "static_findings_count": 0,
                "ai_findings_count": len(ai_findings or []),
                "total_findings": len(combined),
            }

        grouped = self._group_files_by_scanner(
            modified_files, scanners=scanners, repo_root=repo_root
        )

        async def _run_async_scanner(sc: str, targets: list[str]) -> list[dict[str, Any]]:
            try:
                target_arg: str | list[str] = targets[0] if len(targets) == 1 else targets
                if repo_root is not None:
                    return await self.run_scanner_async(sc, target_arg, cwd=repo_root)
                return await self.run_scanner_async(sc, target_arg)
            except (RuntimeError, ValueError):
                return []

        scanner_keys = list(grouped.keys())
        tasks = [_run_async_scanner(sc, grouped[sc]) for sc in scanner_keys]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for findings in results:
            static_findings.extend(findings)

        combined_findings = [
            *static_findings,
            *(ai_findings or []),
        ]

        return {
            "findings": combined_findings,
            "static_findings_count": len(static_findings),
            "ai_findings_count": len(ai_findings or []),
            "total_findings": len(combined_findings),
        }

    def run_scanner(
        self, scanner: str, target_path: str | Sequence[str], cwd: str | None = None
    ) -> list[dict[str, Any]]:
        """Run a supported scanner and normalize its JSON output.

        Security (W2-S3, Sukun/Divu, Issue #243):
        - Rejects empty paths, leading '-' option-injection strings, and null bytes.
        - Passes '--' before target_path(s) so file paths cannot be parsed as CLI flags.
        - Passes '--no-install' to npx to disallow downloading untrusted npm packages.
        - Executes under a sanitized, minimal environment.
        - Accepts single file path string or Sequence[str] for batch amortization.
        """
        cleaned_targets = self._sanitize_target_paths(target_path)
        cmd = self._build_scanner_command(scanner, cleaned_targets)
        safe_env = self._get_safe_env()

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                cwd=cwd,
                env=safe_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{scanner} could not complete: {redact(str(exc))}") from exc

        return self._parse_scanner_output(
            scanner=scanner,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            cleaned_targets=cleaned_targets,
            cwd=cwd,
        )

    async def run_scanner_async(
        self,
        scanner: str,
        target_path: str | Sequence[str],
        cwd: str | None = None,
        timeout: float = 60.0,
    ) -> list[dict[str, Any]]:
        """Asynchronously run a supported scanner in a non-blocking subprocess with timeout."""
        cleaned_targets = self._sanitize_target_paths(target_path)
        cmd = self._build_scanner_command(scanner, cleaned_targets)
        safe_env = self._get_safe_env()

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=safe_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            returncode = proc.returncode if proc.returncode is not None else 0
        except (TimeoutError, OSError) as exc:
            if proc is not None and proc.returncode is None:
                try:
                    proc_kill = getattr(proc, "kill", None)
                    if callable(proc_kill):
                        kill_res = proc_kill()
                        if inspect.isawaitable(kill_res):
                            await kill_res
                    await proc.wait()
                except (OSError, RuntimeError) as kill_exc:
                    logger.debug("Failed to terminate scanner process: %s", kill_exc)
            raise RuntimeError(f"{scanner} could not complete: {redact(str(exc))}") from exc

        return self._parse_scanner_output(
            scanner=scanner,
            stdout=stdout_str,
            stderr=stderr_str,
            returncode=returncode,
            cleaned_targets=cleaned_targets,
            cwd=cwd,
        )


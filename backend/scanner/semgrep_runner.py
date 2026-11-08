"""Semgrep CE Deterministic Security Analysis Runner.

Part of Issue #191: Broaden Security Analysis and Bug Detection Findings.
Provides sandboxed execution of Semgrep CE, output parsing, schema normalization,
and graceful degradation when the binary is not present.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.core.secret_redaction import redact

logger = logging.getLogger(__name__)

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "rules" / "semgrep_rules.yaml"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_SEMGREP_OUTPUT_BYTES = 5 * 1024 * 1024  # 5 MB

SEMGREP_SEVERITY_MAP: dict[str, str] = {
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
    "CRITICAL": "CRITICAL",
}


@dataclass
class SemgrepFinding:
    """Normalized finding emitted by Semgrep CE."""

    rule_id: str
    category: str
    severity: str
    message: str
    file_path: str
    start_line: int
    end_line: int
    column: int = 1
    evidence: str = ""
    suggested_fix: str | None = None
    cwe: list[str] = field(default_factory=list)
    owasp: list[str] = field(default_factory=list)
    confidence: str = "high"
    engine: str = "semgrep_ce"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "column": self.column,
            "evidence": self.evidence,
            "suggested_fix": self.suggested_fix,
            "metadata": {
                "cwe": self.cwe,
                "owasp": self.owasp,
                "engine": self.engine,
            },
        }

    def to_candidate_dict(self) -> dict[str, Any]:
        """Convert finding into BugCandidate dictionary representation."""
        return {
            "candidate_id": f"cand-semgrep-{self.rule_id}-{self.start_line}",
            "rule_id": self.rule_id,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "category": self.category,
            "severity": self.severity,
            "evidence": self.evidence,
            "source_type": "STATIC",
            "confidence": self.confidence,
            "remediation": self.suggested_fix or "",
            "metadata": {
                "cwe": self.cwe,
                "owasp": self.owasp,
                "engine": self.engine,
            },
        }


@dataclass
class SemgrepScanResult:
    """Result of Semgrep execution."""

    success: bool
    is_available: bool
    findings: list[SemgrepFinding] = field(default_factory=list)
    raw_output: str = ""
    error_message: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


class SemgrepRunner:
    """Orchestrates sandboxed Semgrep CE execution and result normalization."""

    def __init__(
        self,
        executable_path: str | None = None,
        rules_path: str | Path | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.executable_path = executable_path or shutil.which("semgrep")
        self.rules_path = Path(rules_path) if rules_path else DEFAULT_RULES_PATH
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Check if Semgrep CLI is installed and accessible."""
        return bool(self.executable_path and os.path.exists(self.executable_path))

    def scan_path(
        self,
        target_path: str | Path,
        workspace_root: str | Path | None = None,
        extra_args: Sequence[str] | None = None,
    ) -> SemgrepScanResult:
        """Execute Semgrep against target file or directory within workspace boundary."""
        start_time = time.perf_counter()

        if not self.is_available():
            logger.info("semgrep_binary_not_found; falling back to internal static analyzers")
            return SemgrepScanResult(
                success=True,
                is_available=False,
                findings=[],
                diagnostics=["Semgrep binary not installed; internal AST rules active."],
                execution_time_ms=0.0,
            )

        target = Path(target_path)
        workspace = Path(workspace_root).resolve() if workspace_root else (
            target.parent.resolve() if target.is_file() else target.resolve()
        )

        # Enforce sandbox boundary: target must be inside workspace_root
        try:
            resolved_target = target.resolve()
            if workspace and not (resolved_target == workspace or workspace in resolved_target.parents):
                return SemgrepScanResult(
                    success=False,
                    is_available=True,
                    error_message=f"Target path '{target}' escapes workspace root '{workspace}'.",
                    diagnostics=["Security violation: path traversal outside workspace blocked."],
                )
        except Exception as exc:
            return SemgrepScanResult(
                success=False,
                is_available=True,
                error_message=f"Invalid target path: {exc}",
            )

        cmd = [
            str(self.executable_path),
            "--json",
            "--config",
            str(self.rules_path),
            "--timeout",
            str(self.timeout_seconds),
            str(target),
        ]
        if extra_args:
            cmd.extend(extra_args)

        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
            "LANG": "en_US.UTF-8",
            "SEMGREP_SEND_METRICS": "off",
        }

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
                check=False,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return self.parse_json_output(
                proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                workspace_root=workspace,
                elapsed_ms=elapsed_ms,
            )

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("semgrep_execution_timeout", extra={"timeout": self.timeout_seconds})
            return SemgrepScanResult(
                success=False,
                is_available=True,
                findings=[],
                error_message=f"Semgrep execution timed out after {self.timeout_seconds} seconds.",
                diagnostics=["Execution timeout encountered; analysis continued with fallback."],
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            safe_err = redact(str(exc))
            logger.error("semgrep_execution_error", extra={"error": safe_err})
            return SemgrepScanResult(
                success=False,
                is_available=True,
                findings=[],
                error_message=f"Semgrep execution failed: {safe_err}",
                diagnostics=["Semgrep process error occurred."],
                execution_time_ms=elapsed_ms,
            )

    def parse_json_output(
        self,
        stdout: str,
        stderr: str = "",
        exit_code: int = 0,
        workspace_root: Path | None = None,
        elapsed_ms: float = 0.0,
    ) -> SemgrepScanResult:
        """Parse Semgrep JSON output and normalize findings."""
        if not stdout or not stdout.strip():
            if exit_code != 0:
                return SemgrepScanResult(
                    success=False,
                    is_available=True,
                    error_message=f"Semgrep exited with code {exit_code}: {redact(stderr[:500])}",
                    execution_time_ms=elapsed_ms,
                )
            return SemgrepScanResult(
                success=True,
                is_available=True,
                findings=[],
                raw_output=stdout,
                execution_time_ms=elapsed_ms,
            )

        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            return SemgrepScanResult(
                success=False,
                is_available=True,
                error_message=f"Invalid JSON from Semgrep: {exc}",
                raw_output=redact(stdout[:1000]),
                diagnostics=["Semgrep emitted malformed non-JSON output."],
                execution_time_ms=elapsed_ms,
            )

        findings: list[SemgrepFinding] = []
        raw_results = data.get("results", [])

        for r in raw_results:
            rule_id = r.get("check_id") or "SEMGREP-RULE"
            raw_path = r.get("path") or ""

            # Normalize path relative to workspace_root
            if workspace_root:
                try:
                    p = Path(raw_path)
                    if p.is_absolute():
                        raw_path = str(p.relative_to(workspace_root)).replace("\\", "/")
                    else:
                        raw_path = str(p).replace("\\", "/")
                except Exception:
                    raw_path = raw_path.replace("\\", "/")
            else:
                raw_path = raw_path.replace("\\", "/")

            start = r.get("start", {})
            end = r.get("end", {})
            start_line = max(1, int(start.get("line") or 1))
            end_line = max(start_line, int(end.get("line") or start_line))
            column = max(1, int(start.get("col") or 1))

            extra = r.get("extra", {})
            message = extra.get("message") or f"Issue detected by {rule_id}"
            raw_sev = (extra.get("severity") or "WARNING").upper()
            severity = SEMGREP_SEVERITY_MAP.get(raw_sev, "MEDIUM")

            metadata = extra.get("metadata", {})
            category = metadata.get("category") or "security"
            cwe_raw = metadata.get("cwe", [])
            cwe = [cwe_raw] if isinstance(cwe_raw, str) else list(cwe_raw)
            owasp_raw = metadata.get("owasp", [])
            owasp = [owasp_raw] if isinstance(owasp_raw, str) else list(owasp_raw)

            # Redact any secrets in lines/evidence
            raw_lines = extra.get("lines") or ""
            evidence = redact(raw_lines.strip())
            suggested_fix = extra.get("fix")

            findings.append(
                SemgrepFinding(
                    rule_id=rule_id,
                    category=category,
                    severity=severity,
                    message=message,
                    file_path=raw_path,
                    start_line=start_line,
                    end_line=end_line,
                    column=column,
                    evidence=evidence,
                    suggested_fix=suggested_fix,
                    cwe=cwe,
                    owasp=owasp,
                )
            )

        return SemgrepScanResult(
            success=True,
            is_available=True,
            findings=findings,
            raw_output=stdout,
            execution_time_ms=elapsed_ms,
        )

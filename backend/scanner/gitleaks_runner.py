"""Gitleaks Secret Detection Runner with Strict Redaction Guarantees.

Part of Issue #191: Broaden Security Analysis and Bug Detection Findings.
Provides sandboxed secret scanning across repository workspaces.

CRITICAL INVARIANT:
Raw secret values are NEVER stored in the database, NEVER logged, NEVER emitted
in API responses, and NEVER included in LLM prompts. Matches are redacted immediately
upon detection.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.core.secret_redaction import redact

logger = logging.getLogger(__name__)

# Excluded paths and extensions
EXCLUDED_PATTERNS: tuple[str, ...] = (
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "__pycache__",
    ".workspaces",
    ".pytest_cache",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
)

# Placeholder hints indicating non-live test / example values
_PLACEHOLDER_REGEX = re.compile(
    r"""(?i)(?:\[REDACTED\]|<[^>]+>|\.\.\.|x{4,}|example|placeholder|changeme|your[_-]|dummy|fake|mock|"""
    r"""test_key|sample|os\.environ|os\.getenv|process\.env|settings\.|\$\{)"""
)

# Canonical secret patterns aligned with Gitleaks rule definitions
GITLEAKS_PATTERNS: list[dict[str, Any]] = [
    {
        "rule_id": "OPENAI-API-KEY",
        "description": "OpenAI API Key",
        "pattern": re.compile(r"""\b(sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,})\b"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "GITHUB-PAT",
        "description": "GitHub Personal Access Token",
        "pattern": re.compile(r"""\b(gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{22,})\b"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "AWS-ACCESS-KEY",
        "description": "AWS Access Key ID",
        "pattern": re.compile(r"""\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "GOOGLE-API-KEY",
        "description": "Google Cloud API Key",
        "pattern": re.compile(r"""\b(AIza[0-9A-Za-z_\-]{35})\b"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "SLACK-BOT-TOKEN",
        "description": "Slack Bot Token",
        "pattern": re.compile(r"""\b(xoxb-[0-9]{11,13}-[0-9]{11,13}-[A-Za-z0-9]{24})\b"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "STRIPE-SECRET-KEY",
        "description": "Stripe Secret / Live Key",
        "pattern": re.compile(r"""\b((?:sk|rk)_live_[0-9a-zA-Z]{24,})\b"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "PRIVATE-KEY-HEADER",
        "description": "Unencrypted Private Key Block",
        "pattern": re.compile(r"""(-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)"""),
        "severity": "CRITICAL",
        "cwe": "CWE-798",
    },
    {
        "rule_id": "GENERIC-SECRET-ASSIGNMENT",
        "description": "Hardcoded Credential or Token Assignment",
        "pattern": re.compile(
            r"""(?i)(?:\b\w*(?:api_?key|secret|password|passwd|access_?token|auth_?token)\w*[\x22\x27]?\s*[:=]\s*[\x22\x27])([^\x22\x27\s]{12,})([\x22\x27])"""
        ),
        "severity": "HIGH",
        "cwe": "CWE-798",
    },
]


@dataclass
class GitleaksFinding:
    """Normalized finding representing a detected and redacted secret."""

    rule_id: str
    secret_type: str
    severity: str
    file_path: str
    start_line: int
    end_line: int
    evidence: str  # Strictly redacted: raw secret is masked!
    cwe: str = "CWE-798"
    confidence: str = "high"
    engine: str = "gitleaks"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": f"GITLEAKS-{self.rule_id}",
            "category": "secrets",
            "severity": self.severity,
            "title": f"Hardcoded secret detected: {self.secret_type}",
            "description": (
                f"An exposed {self.secret_type} was identified in source code or configuration. "
                "Secrets committed to source control create high risk of unauthorized access."
            ),
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "suggested_fix": "Remove the hardcoded secret and load it from environment variables or a secrets manager.",
            "confidence": self.confidence,
            "metadata": {
                "rule_id": self.rule_id,
                "secret_type": self.secret_type,
                "cwe": self.cwe,
                "is_redacted": True,
                "engine": self.engine,
            },
        }

    def to_candidate_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": f"cand-secret-{self.rule_id}-{self.start_line}",
            "rule_id": f"GITLEAKS-{self.rule_id}",
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "category": "secrets",
            "severity": self.severity,
            "evidence": self.evidence,
            "source_type": "STATIC",
            "confidence": self.confidence,
            "remediation": "Remove the hardcoded secret and load it from environment variables or a secrets manager.",
            "metadata": {
                "rule_id": self.rule_id,
                "secret_type": self.secret_type,
                "cwe": self.cwe,
                "is_redacted": True,
                "engine": self.engine,
            },
        }


@dataclass
class GitleaksScanResult:
    """Result of Gitleaks scan execution."""

    success: bool
    is_available: bool
    findings: list[GitleaksFinding] = field(default_factory=list)
    files_scanned: int = 0
    error_message: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


class GitleaksRunner:
    """Executes sandboxed Gitleaks or built-in secret detection with zero secret leakage."""

    def __init__(
        self,
        executable_path: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.executable_path = executable_path or shutil.which("gitleaks")
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Check if gitleaks CLI is installed."""
        return bool(self.executable_path and os.path.exists(self.executable_path))

    @staticmethod
    def mask_secret(value: str) -> str:
        """Mask secret string to ensure zero raw leakage."""
        if not value:
            return "[REDACTED]"
        if len(value) <= 8:
            return "***REDACTED***"
        prefix = value[:4]
        suffix = value[-4:]
        return f"{prefix}***REDACTED***{suffix}"

    @staticmethod
    def is_excluded(file_path: str) -> bool:
        """Check whether path matches standard excluded files."""
        normalized = file_path.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        return any(p in EXCLUDED_PATTERNS for p in parts)

    def scan_text(
        self,
        content: str,
        file_path: str = "snippet.py",
        base_line: int = 1,
    ) -> list[GitleaksFinding]:
        """Scan raw text content for secrets with mandatory value redaction."""
        if not content or not content.strip():
            return []

        if self.is_excluded(file_path):
            return []

        findings: list[GitleaksFinding] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines):
            line_no = base_line + idx
            stripped = line.strip()
            if not stripped:
                continue

            for rule in GITLEAKS_PATTERNS:
                m = rule["pattern"].search(line)
                if not m:
                    continue

                secret_val = m.group(1)
                # Check for placeholder strings (ignore false positives)
                if _PLACEHOLDER_REGEX.search(secret_val) or _PLACEHOLDER_REGEX.search(line):
                    continue

                # STRICT REDACTION: mask the secret value in the evidence snippet
                masked = self.mask_secret(secret_val)
                redacted_evidence = line.replace(secret_val, masked).strip()

                findings.append(
                    GitleaksFinding(
                        rule_id=rule["rule_id"],
                        secret_type=rule["description"],
                        severity=rule["severity"],
                        file_path=file_path,
                        start_line=line_no,
                        end_line=line_no,
                        evidence=redacted_evidence,
                        cwe=rule.get("cwe", "CWE-798"),
                        confidence="high",
                    )
                )

        return findings

    def scan_workspace(
        self,
        workspace_root: str | Path,
    ) -> GitleaksScanResult:
        """Scan a repository workspace for exposed secrets."""
        start_time = time.perf_counter()
        workspace = Path(workspace_root).resolve()

        if not workspace.is_dir():
            return GitleaksScanResult(
                success=False,
                is_available=self.is_available(),
                error_message=f"Workspace directory does not exist: {workspace}",
                execution_time_ms=0.0,
            )

        # Attempt CLI scan if binary is installed
        if self.is_available():
            try:
                cli_res = self._run_cli_scan(workspace)
                if cli_res.success:
                    cli_res.execution_time_ms = (time.perf_counter() - start_time) * 1000
                    return cli_res
            except Exception as exc:
                logger.warning("gitleaks_cli_failed; falling back to internal secret scanner: %s", exc)

        # Built-in deterministic secret scanner
        findings: list[GitleaksFinding] = []
        files_scanned = 0

        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_PATTERNS]
            for f in files:
                p = Path(root) / f
                rel_path = str(p.relative_to(workspace)).replace("\\", "/")
                if self.is_excluded(rel_path):
                    continue

                # Limit scan to text files under 2MB
                try:
                    if p.stat().st_size > 2 * 1024 * 1024:
                        continue
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                files_scanned += 1
                f_items = self.scan_text(text, file_path=rel_path)
                findings.extend(f_items)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return GitleaksScanResult(
            success=True,
            is_available=self.is_available(),
            findings=findings,
            files_scanned=files_scanned,
            diagnostics=[f"Scanned {files_scanned} files for exposed secrets with strict value redaction."],
            execution_time_ms=elapsed_ms,
        )

    def _run_cli_scan(self, workspace: Path) -> GitleaksScanResult:
        """Execute gitleaks CLI inside sandbox and redact any secret output."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_report = tmp.name

        try:
            cmd = [
                str(self.executable_path),
                "detect",
                "--no-git",
                "--source",
                str(workspace),
                "--report-format",
                "json",
                "--report-path",
                tmp_report,
                "--redact",  # Ask CLI to redact matches as well
            ]
            subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )

            # Read report
            report_text = Path(tmp_report).read_text(encoding="utf-8", errors="replace")
            findings = self._parse_cli_report(report_text, workspace)
            return GitleaksScanResult(
                success=True,
                is_available=True,
                findings=findings,
            )
        finally:
            if os.path.exists(tmp_report):
                try:
                    os.unlink(tmp_report)
                except Exception:
                    pass

    def _parse_cli_report(self, report_json: str, workspace: Path) -> list[GitleaksFinding]:
        """Parse Gitleaks JSON report, guaranteeing that raw secret matches are redacted."""
        findings: list[GitleaksFinding] = []
        if not report_json or not report_json.strip():
            return findings

        try:
            items = json.loads(report_json)
        except Exception:
            return findings

        for item in items:
            rule_id = item.get("RuleID", "SECRET")
            desc = item.get("Description", "Exposed Secret")
            raw_file = item.get("File", "")
            try:
                rel_file = str(Path(raw_file).relative_to(workspace)).replace("\\", "/")
            except Exception:
                rel_file = raw_file.replace("\\", "/")

            start_line = max(1, int(item.get("StartLine") or 1))
            end_line = max(start_line, int(item.get("EndLine") or start_line))

            # Strictly sanitize secret and line output
            raw_secret = item.get("Secret", "")
            raw_line = item.get("Line", "")
            masked_secret = self.mask_secret(raw_secret) if raw_secret else "[REDACTED]"
            redacted_evidence = raw_line.replace(raw_secret, masked_secret).strip() if raw_secret else redact(raw_line.strip())

            findings.append(
                GitleaksFinding(
                    rule_id=rule_id,
                    secret_type=desc,
                    severity="CRITICAL",
                    file_path=rel_file,
                    start_line=start_line,
                    end_line=end_line,
                    evidence=redacted_evidence or f"Secret pattern matched in {rel_file}:{start_line}",
                    confidence="high",
                )
            )
        return findings

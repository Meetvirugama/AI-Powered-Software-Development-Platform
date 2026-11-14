"""Secondary Secret Scanner using Gitleaks Engine (Issue #206 / F25).

Integrates Gitleaks detection across unified git diffs as a secondary secret
scanning engine alongside built-in regex pattern scanning.

Supports:
1. Native `gitleaks` CLI execution when installed in the runtime environment.
2. Built-in Gitleaks-standard rules engine matching canonical rules
   (AWS, GitHub tokens, Slack webhooks, Private Keys, Stripe, OpenAI, Generic API Keys).
3. Respects `.gitleaks.toml` allowlist paths and placeholder patterns (e.g. [REDACTED], test fixtures).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.secret_redaction import redact
from app.schemas.workspace import SecretScanFinding

logger = logging.getLogger(__name__)

# Canonical Gitleaks regex patterns for secondary scanning
GITLEAKS_RULES: dict[str, re.Pattern[str]] = {
    "gitleaks:aws-access-key-id": re.compile(
        r"\b(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}\b"
    ),
    "gitleaks:aws-secret-access-key": re.compile(
        r"(?i)\b(?:aws_secret_access_key|aws_secret_key|secret_key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
    ),
    "gitleaks:github-pat": re.compile(
        r"\b(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{22,82})\b"
    ),
    "gitleaks:github-token": re.compile(
        r"\b(gho_[a-zA-Z0-9]{36}|ghu_[a-zA-Z0-9]{36}|ghs_[a-zA-Z0-9]{36}|ghr_[a-zA-Z0-9]{36})\b"
    ),
    "gitleaks:openai-api-key": re.compile(
        r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b"
    ),
    "gitleaks:private-key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    ),
    "gitleaks:slack-webhook": re.compile(
        r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+"
    ),
    "gitleaks:stripe-api-key": re.compile(
        r"\b(?:sk|rk)_(?:test|live)_[0-9a-zA-Z]{24,}\b"
    ),
    "gitleaks:generic-api-key": re.compile(
        r"(?i)\b(?:api_?key|secret|access_?token|auth_?token|private_?key|password)\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{20,})['\"]"
    ),
}

# Values that are explicitly benign placeholders or allowed documentation examples
PLACEHOLDER_REGEX = re.compile(
    r"(?i)(\[REDACTED\]|<[A-Z0-9_\-\.]+>|your_api_key_here|my_secret_key|placeholder_secret|"
    r"changeme|dummy_token|fake_key|os\.environ\.get|getenv\()"
)


def is_gitleaks_cli_available() -> bool:
    """Return True if native gitleaks CLI is installed and discoverable on PATH."""
    return bool(shutil.which("gitleaks"))


class GitleaksDiffScanner:
    """Secondary secret scanning engine executing Gitleaks or canonical Gitleaks rules."""

    def __init__(
        self,
        config_path: Path | None = None,
        use_cli: bool = True,
        force_builtin: bool = False,
        rules: dict[str, re.Pattern[str]] | None = None,
    ) -> None:
        self.config_path = config_path or Path(".gitleaks.toml")
        self.use_cli = use_cli and not force_builtin
        self.force_builtin = force_builtin
        self.rules = rules or GITLEAKS_RULES
        self._gitleaks_binary = shutil.which("gitleaks") if self.use_cli else None

    @property
    def is_cli_available(self) -> bool:
        """Return True if native gitleaks CLI is installed and discoverable."""
        return bool(self._gitleaks_binary)

    def scan_diff(
        self,
        diff_text: str,
        file_path_hint: str | None = None,
    ) -> list[SecretScanFinding]:
        """Scan a unified git diff for hardcoded credentials using Gitleaks rules.

        Attempts CLI execution first if available; supplements and falls back smoothly
        to internal Gitleaks-standard rules engine.
        """
        if not diff_text or not diff_text.strip():
            return []

        findings: list[SecretScanFinding] = []

        # Attempt CLI if available and not explicitly disabled
        if self._gitleaks_binary:
            try:
                cli_findings = self._scan_with_cli(diff_text)
                if cli_findings:
                    findings.extend(cli_findings)
            except Exception as exc:
                logger.debug("Native gitleaks CLI scan failed, falling back to built-in rules: %s", exc)

        # Supplement with built-in canonical Gitleaks rules to guarantee pattern detection
        rule_findings = self._scan_with_rules(diff_text, file_path_hint=file_path_hint)
        for rf in rule_findings:
            if not any(
                f.file_path == rf.file_path and f.line_number == rf.line_number and f.secret_type == rf.secret_type
                for f in findings
            ):
                findings.append(rf)

        return findings

    def _scan_with_cli(self, diff_text: str) -> list[SecretScanFinding] | None:
        """Execute native gitleaks CLI with piping."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False, encoding="utf-8") as f:
            f.write(diff_text)
            diff_file = Path(f.name)

        report_file = diff_file.with_suffix(".json")
        try:
            cmd = [
                str(self._gitleaks_binary),
                "detect",
                "--no-git",
                "--source",
                str(diff_file),
                "--report-format",
                "json",
                "--report-path",
                str(report_file),
                "--exit-code",
                "0",
            ]
            if self.config_path.exists():
                cmd.extend(["--config", str(self.config_path)])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )

            if report_file.exists():
                data = json.loads(report_file.read_text(encoding="utf-8") or "[]")
                findings: list[SecretScanFinding] = []
                for item in data:
                    match_str = item.get("Secret", "") or item.get("Match", "")
                    if PLACEHOLDER_REGEX.search(match_str):
                        continue
                    findings.append(
                        SecretScanFinding(
                            file_path=item.get("File", "unknown"),
                            line_number=item.get("StartLine", 1),
                            secret_type=f"gitleaks:{item.get('RuleID', 'credential')}",
                            redacted_preview=redact(match_str[:80]),
                        )
                    )
                return findings
        finally:
            if diff_file.exists():
                diff_file.unlink(missing_ok=True)
            if report_file.exists():
                report_file.unlink(missing_ok=True)

        return None

    def _scan_with_rules(
        self,
        diff_text: str,
        file_path_hint: str | None = None,
    ) -> list[SecretScanFinding]:
        """Execute built-in Gitleaks rule evaluation over added lines in diff."""
        findings: list[SecretScanFinding] = []
        current_file = file_path_hint or "unknown"
        current_line_no = 0

        for line in diff_text.splitlines():
            # Track file headers in unified diff
            if line.startswith("+++ b/"):
                current_file = line[6:].strip()
                continue
            elif line.startswith("+++ "):
                current_file = line[4:].strip().lstrip("b/")
                continue

            if line.startswith("@@"):
                # Parse hunk header: @@ -old,len +new,len @@
                m = re.search(r"\+(\d+)", line)
                if m:
                    current_line_no = int(m.group(1)) - 1
                continue

            if line.startswith("+") and not line.startswith("+++"):
                current_line_no += 1
                content = line[1:].strip()

                # Skip comment lines that contain placeholder keywords
                if content.startswith(("#", "//", "/*", "*")) and any(
                    w in content.lower() for w in ("dummy", "example", "placeholder", "[redacted]")
                ):
                    continue

                # Skip obvious placeholder comments or redacted content
                if PLACEHOLDER_REGEX.search(content):
                    continue

                for rule_id, pattern in self.rules.items():
                    if pattern.search(content):
                        findings.append(
                            SecretScanFinding(
                                file_path=current_file,
                                line_number=current_line_no,
                                secret_type=rule_id,
                                redacted_preview=redact(content[:80]),
                            )
                        )
            elif not line.startswith("-"):
                current_line_no += 1

        return findings

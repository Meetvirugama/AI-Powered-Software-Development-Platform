
"""Run available static-analysis tools and normalize their findings."""

from dataclasses import asdict, dataclass
import json
import subprocess
import sys
from typing import Any


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
    VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}

    def normalize_finding(
        self, finding: dict[str, Any], *, scanner: str
    ) -> StaticFinding:
        rule_id = str(finding.get("rule_id") or finding.get("code") or "unknown")
        message = str(finding.get("message") or "No message provided")
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
            key: value
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

    def run_scanner(
        self, scanner: str, target_path: str
    ) -> list[dict[str, Any]]:
        """Run a supported scanner and normalize its JSON output."""

        commands = {
            "ruff": [
                sys.executable, "-m", "ruff", "check",
                "--output-format", "json", target_path,
            ],
            "bandit": [
                sys.executable, "-m", "bandit", "-f", "json",
                "-r", target_path,
            ],
        }

        if scanner not in commands:
            raise ValueError(f"Unsupported scanner: {scanner}")

        try:
            completed = subprocess.run(
                commands[scanner],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{scanner} could not complete: {exc}") from exc

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            detail = (completed.stderr or completed.stdout or "").strip()
            if completed.returncode != 0:
                raise RuntimeError(f"{scanner} failed: {detail}") from exc
            raise RuntimeError(
                f"{scanner} returned invalid JSON output"
            ) from exc

        if scanner == "ruff":
            if not isinstance(payload, list):
                raise RuntimeError("Ruff returned an unexpected JSON format")

            findings = [
                {
                    "rule_id": item.get("code"),
                    "severity": "low",
                    "message": item.get("message"),
                    "file_path": item.get("filename"),
                    "line_number": (item.get("location") or {}).get("row"),
                }
                for item in payload
            ]
        else:
            raw_findings = payload.get("results", [])
            findings = [
                {
                    "rule_id": item.get("test_id"),
                    "severity": str(
                        item.get("issue_severity", "low")
                    ).lower(),
                    "message": item.get("issue_text"),
                    "file_path": item.get("filename"),
                    "line_number": item.get("line_number"),
                }
                for item in raw_findings
            ]

        return self.review(findings, scanner=scanner)

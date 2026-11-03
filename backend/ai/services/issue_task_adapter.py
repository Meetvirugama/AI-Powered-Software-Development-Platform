"""Issue-to-Task Context Adapter & Finding-to-Issue Formatter.

Owners:
- Meet (Week 3 Day 1: Issue-to-Task context adapter converting issue details and Week 2 findings into implementation objectives)
- Sukun (Week 3 Day 1: Prompt-injection fencing and secret scrubbing on untrusted issue bodies and finding evidence)

Responsibilities:
1. Fence untrusted issue descriptions and comments in per-call randomized boundary markers (`<<<ISSUE_DATA_<hex>>>> ... <<<END_ISSUE_DATA_<hex>>>>`).
2. Safely extract candidate repository-relative file paths from issue descriptions or findings using `validate_repo_relative_path` (discarding any path traversal attempts).
3. Convert a GitHub issue, Week 2 `AnalysisFinding` (bug/review), or user requirement into a validated `TaskIntakePayload` separating `requirements`, `assumptions`, and `constraints`.
4. Format a Week 2 `AnalysisFinding` into a clean, secret-redacted GitHub Issue title, Markdown body, and label set.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Sequence
from uuid import UUID

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact
from app.schemas.task import (
    TaskAssumption,
    TaskConstraint,
    TaskIntakePayload,
    TaskRequirement,
    TaskRequirementCategory,
    TaskSourceReference,
)

# Matches plausible relative file paths in issue bodies (e.g. `src/main.py`, `backend/app/auth.py`)
_FILE_PATH_CANDIDATE_RE = re.compile(
    r"(?:`|\b)([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.(?:py|ts|tsx|js|jsx|json|yml|yaml|toml|md|sql|sh|go|rs|java|c|cpp|h))(?:`|\b)"
)

_DEFAULT_PROTECTED_FILES: list[str] = [
    ".env",
    ".env.production",
    ".github/workflows/deploy.yml",
]


def fence_untrusted_issue_data(raw_text: str) -> str:
    """Wrap untrusted GitHub issue or finding content in a randomized boundary and scrub secrets."""
    token = secrets.token_hex(8)
    safe_body = redact(raw_text or "")
    return f"<<<ISSUE_DATA_{token}>>>\n{safe_body}\n<<<END_ISSUE_DATA_{token}>>>"


def extract_safe_repo_paths(
    text: str,
    *,
    known_repo_paths: Sequence[str] | None = None,
    forbidden_files: Sequence[str] | None = None,
) -> list[str]:
    """Extract valid repository-relative file paths from untrusted text, dropping any unsafe or forbidden paths."""
    if not text:
        return []

    forbidden_lower = {p.lower() for p in (forbidden_files or _DEFAULT_PROTECTED_FILES)}
    known_set = set(known_repo_paths) if known_repo_paths else None

    extracted: list[str] = []
    for match in _FILE_PATH_CANDIDATE_RE.finditer(text):
        candidate = match.group(1).strip()
        try:
            normalized = validate_repo_relative_path(candidate)
        except UnsafePathError:
            continue

        if normalized.lower() in forbidden_lower:
            continue
        if known_set is not None and normalized not in known_set:
            # Check if suffix matches a known file
            matched_known = next(
                (kp for kp in known_set if kp.endswith("/" + normalized) or kp == normalized),
                None,
            )
            if matched_known and matched_known.lower() not in forbidden_lower:
                normalized = matched_known
            else:
                continue

        if normalized not in extracted:
            extracted.append(normalized)

    return extracted[:10]


def format_issue_from_finding(
    finding: Any,
    *,
    custom_title: str | None = None,
    custom_body: str | None = None,
    extra_labels: Sequence[str] | None = None,
) -> tuple[str, str, list[str]]:
    """Format a Week 2 AnalysisFinding (or finding dict) into a secret-redacted `(title, body, labels)` tuple."""
    if hasattr(finding, "to_dict"):
        data = finding.to_dict()
    elif hasattr(finding, "model_dump"):
        data = finding.model_dump(mode="json")
    elif isinstance(finding, dict):
        data = dict(finding)
    else:
        data = {
            "id": str(getattr(finding, "id", "")),
            "title": getattr(finding, "title", "Code Finding"),
            "description": getattr(finding, "description", ""),
            "severity": getattr(finding, "severity", "MEDIUM"),
            "category": getattr(finding, "category", "bug"),
            "file_path": getattr(finding, "file_path", ""),
            "start_line": getattr(finding, "start_line", None),
            "end_line": getattr(finding, "end_line", None),
            "evidence": getattr(finding, "evidence", ""),
            "suggested_fix": getattr(finding, "suggested_fix", None),
            "rule_id": getattr(finding, "rule_id", None),
        }

    finding_id = str(data.get("id") or "")
    severity = str(data.get("severity") or "MEDIUM").upper()
    category = str(data.get("category") or "defect").lower()
    raw_title = str(data.get("title") or "Detected Code Defect").strip()

    source_ref = data.get("source_reference") or {}
    file_path = str(data.get("file_path") or source_ref.get("file_path") or "unknown")
    start_line = data.get("start_line") if data.get("start_line") is not None else source_ref.get("start_line")
    end_line = data.get("end_line") if data.get("end_line") is not None else source_ref.get("end_line")
    revision = data.get("source_revision") or source_ref.get("revision")

    title = redact((custom_title or f"[{severity}] {raw_title}").strip())[:250]

    location_str = f"`{file_path}`"
    if start_line is not None:
        location_str += f" (Lines {start_line}–{end_line or start_line})"
    if revision:
        location_str += f" @ `{revision}`"

    if custom_body and custom_body.strip():
        body = redact(custom_body.strip())
    else:
        sections = [
            f"## Automated Developer Intelligence Finding",
            f"- **Finding ID:** `{finding_id}`" if finding_id else "- **Origin:** Developer Intelligence Suite",
            f"- **Severity:** `{severity}`",
            f"- **Category:** `{category}`",
            f"- **Location:** {location_str}",
        ]
        if data.get("rule_id"):
            sections.append(f"- **Rule ID:** `{data['rule_id']}`")

        sections.append("\n### Description")
        sections.append(redact(str(data.get("description") or raw_title)))

        if data.get("evidence"):
            sections.append("\n### Evidence")
            sections.append(f"```\n{redact(str(data['evidence']))}\n```")

        if data.get("suggested_fix"):
            sections.append("\n### Suggested Remediation")
            sections.append(f"```\n{redact(str(data['suggested_fix']))}\n```")

        body = "\n".join(sections)

    labels: list[str] = ["ai-finding"]
    if "security" in category or severity == "CRITICAL":
        labels.append("security")
    else:
        labels.append("bug")
    labels.append(f"severity:{severity.lower()}")
    if extra_labels:
        for lbl in extra_labels:
            clean_lbl = redact(str(lbl).strip())
            if clean_lbl and clean_lbl not in labels:
                labels.append(clean_lbl)

    return title, body, labels[:10]


class IssueToTaskAdapter:
    """Converts a GitHub issue, Week 2 finding, or user prompt into a validated TaskIntakePayload (Meet W3 Day 1)."""

    def __init__(
        self,
        *,
        protected_files: list[str] | None = None,
        max_budget_tokens: int = 20_000,
    ) -> None:
        self._protected_files = list(protected_files or _DEFAULT_PROTECTED_FILES)
        self._max_budget_tokens = max_budget_tokens

    def _default_constraints(self) -> list[TaskConstraint]:
        return [
            TaskConstraint(
                id="cst-protected-files",
                description="Do not modify environment secrets or production deployment workflows.",
                constraint_type="protected_file",
                forbidden_files=self._protected_files,
                max_budget_tokens=self._max_budget_tokens,
            ),
            TaskConstraint(
                id="cst-security-policy",
                description="All changes must pass static analysis, secret scanning, and existing tests before publication.",
                constraint_type="security_policy",
                forbidden_files=[],
                max_budget_tokens=self._max_budget_tokens,
            ),
        ]

    @staticmethod
    def _infer_category(title: str, body: str, labels: Sequence[str] | None = None) -> TaskRequirementCategory:
        combined = f"{title} {body} {' '.join(labels or [])}".lower()
        if any(k in combined for k in ("security", "vulnerability", "injection", "xss", "csrf", "secret", "auth")):
            return "security"
        if any(k in combined for k in ("test", "coverage", "pytest", "vitest", "jest")):
            return "test"
        if any(k in combined for k in ("refactor", "cleanup", "restructure")):
            return "refactor"
        if any(k in combined for k in ("bug", "fix", "error", "crash", "defect", "exception", "fail")):
            return "bug_fix"
        return "functional"

    def from_github_issue(
        self,
        *,
        repository_id: UUID | str,
        issue_number: int,
        title: str,
        body: str,
        html_url: str,
        labels: Sequence[str] | None = None,
        base_revision: str | None = None,
        finding_id: str | None = None,
        known_repo_paths: Sequence[str] | None = None,
    ) -> TaskIntakePayload:
        """Convert an imported or created GitHub issue into a validated TaskIntakePayload."""
        repo_uuid = UUID(str(repository_id)) if not isinstance(repository_id, UUID) else repository_id
        safe_title = redact((title or f"Resolve GitHub Issue #{issue_number}").strip())
        if len(safe_title) < 3:
            safe_title = f"Issue #{issue_number}: {safe_title}"

        safe_body = redact((body or safe_title).strip()) or safe_title
        category = self._infer_category(safe_title, safe_body, labels)
        target_files = extract_safe_repo_paths(
            f"{safe_title}\n{safe_body}",
            known_repo_paths=known_repo_paths,
            forbidden_files=self._protected_files,
        )

        # Extract bullet points or numbered acceptance items if present
        acceptance_criteria: list[str] = []
        for line in safe_body.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- [ ]", "- [x]", "* ")) and len(stripped) > 5:
                cleaned_item = stripped.lstrip("-*[] xX").strip()
                if cleaned_item:
                    acceptance_criteria.append(cleaned_item[:200])
        if not acceptance_criteria:
            acceptance_criteria = [
                f"Resolve the root cause described in GitHub Issue #{issue_number}.",
                "Add or update unit tests covering the fix and verify all existing tests pass.",
            ]

        requirements = [
            TaskRequirement(
                id="req-1",
                description=f"Implement resolution for GitHub Issue #{issue_number}: {safe_title}",
                category=category,
                target_files=target_files,
                acceptance_criteria=acceptance_criteria[:6],
            )
        ]

        assumptions = [
            TaskAssumption(
                id="asm-1",
                description=(
                    f"Target files ({', '.join(target_files)}) identified from issue description."
                    if target_files
                    else "Exact target files will be resolved by TaskPlanner using repository RAG context."
                ),
                unresolved=len(target_files) == 0,
                risk_level="low" if target_files else "medium",
            )
        ]

        # Validate base_revision format for TaskSourceReference (requires 7-64 hex SHA if set on source)
        commit_sha_rev = (
            base_revision
            if (base_revision and re.match(r"^[0-9a-fA-F]{7,64}$", base_revision.strip()))
            else None
        )

        source_ref = TaskSourceReference(
            type="GITHUB_ISSUE",
            issue_number=int(issue_number),
            issue_url=html_url,
            url=html_url,
            finding_id=str(finding_id) if finding_id else None,
            repository_id=str(repo_uuid),
            base_revision=commit_sha_rev,
        )

        return TaskIntakePayload(
            repository_id=repo_uuid,
            title=safe_title[:256],
            description=safe_body,
            source=source_ref,
            requirements=requirements,
            assumptions=assumptions,
            constraints=self._default_constraints(),
            base_revision=base_revision,
        )

    def from_finding(
        self,
        *,
        repository_id: UUID | str,
        finding: Any,
        source_type: str = "BUG_FINDING",
        base_revision: str | None = None,
    ) -> TaskIntakePayload:
        """Convert a Week 2 BugFinding or ReviewFinding directly into a TaskIntakePayload."""
        repo_uuid = UUID(str(repository_id)) if not isinstance(repository_id, UUID) else repository_id
        title, body, labels = format_issue_from_finding(finding)

        if hasattr(finding, "to_dict"):
            f_data = finding.to_dict()
        elif isinstance(finding, dict):
            f_data = finding
        else:
            f_data = {}

        finding_id = str(f_data.get("id") or getattr(finding, "id", ""))
        raw_path = str(
            f_data.get("file_path")
            or (f_data.get("source_reference") or {}).get("file_path")
            or getattr(finding, "file_path", "")
        )

        target_files: list[str] = []
        if raw_path:
            try:
                norm_path = validate_repo_relative_path(raw_path)
                if norm_path.lower() not in {p.lower() for p in self._protected_files}:
                    target_files.append(norm_path)
            except UnsafePathError:
                pass

        category = self._infer_category(title, body, labels)
        effective_source_type = (
            "REVIEW_FINDING" if source_type == "REVIEW_FINDING" else "BUG_FINDING"
        )
        commit_sha_rev = (
            base_revision
            if (base_revision and re.match(r"^[0-9a-fA-F]{7,64}$", base_revision.strip()))
            else None
        )

        return TaskIntakePayload(
            repository_id=repo_uuid,
            title=title[:256],
            description=body,
            source=TaskSourceReference(
                type=effective_source_type,  # type: ignore[arg-type]
                finding_id=finding_id or None,
                repository_id=str(repo_uuid),
                base_revision=commit_sha_rev,
            ),
            requirements=[
                TaskRequirement(
                    id="req-1",
                    description=f"Remediate {effective_source_type.lower().replace('_', ' ')}: {title}",
                    category=category,
                    target_files=target_files,
                    acceptance_criteria=[
                        "Eliminate the reported defect without breaking existing callers.",
                        "Add regression test coverage for the affected code path.",
                    ],
                )
            ],
            assumptions=[
                TaskAssumption(
                    id="asm-1",
                    description="Existing unit test suite can execute inside the isolated task workspace.",
                    unresolved=False,
                    risk_level="low",
                )
            ],
            constraints=self._default_constraints(),
            base_revision=base_revision,
        )


__all__ = [
    "IssueToTaskAdapter",
    "extract_safe_repo_paths",
    "fence_untrusted_issue_data",
    "format_issue_from_finding",
]

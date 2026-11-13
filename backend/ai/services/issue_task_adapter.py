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
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact
from ai.security.provenance import TrustLevel, create_provenance
from ai.security.taint_tracker import get_taint_tracker
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
            "## Automated Developer Intelligence Finding",
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
        tracker = get_taint_tracker()
        plat_prov = tracker.register_source(
            source_type="platform_constraint",
            source_id="cst-platform-defaults",
            trust_level=TrustLevel.PLATFORM,
            tainted=False,
            metadata={"policy": "protected_files_and_security_policy"},
        )
        return [
            TaskConstraint(
                id="cst-protected-files",
                description="Do not modify environment secrets or production deployment workflows.",
                constraint_type="protected_file",
                forbidden_files=self._protected_files,
                max_budget_tokens=self._max_budget_tokens,
                provenance=plat_prov,
                provenance_ids=[plat_prov.provenance_id],
            ),
            TaskConstraint(
                id="cst-security-policy",
                description="All changes must pass static analysis, secret scanning, and existing tests before publication.",
                constraint_type="security_policy",
                forbidden_files=[],
                max_budget_tokens=self._max_budget_tokens,
                provenance=plat_prov,
                provenance_ids=[plat_prov.provenance_id],
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
        comments: Sequence[dict[str, Any]] | None = None,
    ) -> TaskIntakePayload:
        """Convert an imported or created GitHub issue into a validated TaskIntakePayload with provenance."""
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

        # Register external untrusted provenance for the GitHub issue
        tracker = get_taint_tracker()
        issue_prov = tracker.register_source(
            source_type="github_issue",
            source_id=str(issue_number),
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            tainted=True,
            source_repository_id=str(repo_uuid),
            source_reference=html_url,
            metadata={"issue_number": issue_number, "title": safe_title},
        )
        parent_prov_ids = [issue_prov.provenance_id]

        # Register comment provenance if comments were imported
        if comments:
            for idx, c in enumerate(comments):
                cid = str(c.get("id") or f"comment-{idx}")
                c_prov = tracker.register_source(
                    source_type="github_comment",
                    source_id=cid,
                    trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
                    tainted=True,
                    source_repository_id=str(repo_uuid),
                    source_reference=f"{html_url}#issuecomment-{cid}",
                    parent_ids=[issue_prov.provenance_id],
                    metadata={"user": str(c.get("user") or ""), "body_length": len(str(c.get("body", "")))},
                )
                parent_prov_ids.append(c_prov.provenance_id)

        # Register finding evidence provenance if linked
        if finding_id:
            find_prov = tracker.register_source(
                source_type="finding_evidence",
                source_id=str(finding_id),
                trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
                tainted=True,
                source_repository_id=str(repo_uuid),
                parent_ids=[issue_prov.provenance_id],
                metadata={"finding_id": str(finding_id)},
            )
            parent_prov_ids.append(find_prov.provenance_id)

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

        # Derive requirement with inherited provenance and taint
        req_prov = tracker.propagate(
            parent_ids=parent_prov_ids,
            transformation="intake_requirement_extraction",
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            source_type="task_requirement",
            metadata={"requirement_id": "req-1", "category": category},
            source_repository_id=str(repo_uuid),
        )

        requirements = [
            TaskRequirement(
                id="req-1",
                description=f"Implement resolution for GitHub Issue #{issue_number}: {safe_title}",
                category=category,
                target_files=target_files,
                acceptance_criteria=acceptance_criteria[:6],
                provenance=req_prov,
                provenance_ids=[req_prov.provenance_id],
            )
        ]

        # Derive assumption with inherited provenance and taint
        asm_prov = tracker.propagate(
            parent_ids=parent_prov_ids,
            transformation="intake_assumption_derivation",
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            source_type="task_assumption",
            metadata={"assumption_id": "asm-1"},
            source_repository_id=str(repo_uuid),
        )

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
                provenance=asm_prov,
                provenance_ids=[asm_prov.provenance_id],
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

        default_constraints = self._default_constraints()
        constraint_prov_ids = [c.provenance.provenance_id for c in default_constraints if c.provenance]

        payload_prov = tracker.propagate(
            parent_ids=parent_prov_ids + constraint_prov_ids,
            transformation="intake_payload_aggregation",
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            source_type="task_intake_payload",
            source_repository_id=str(repo_uuid),
        )

        return TaskIntakePayload(
            repository_id=repo_uuid,
            title=safe_title[:256],
            description=safe_body,
            source=source_ref,
            requirements=requirements,
            assumptions=assumptions,
            constraints=default_constraints,
            base_revision=base_revision,
            provenance=payload_prov,
            provenance_ids=payload_prov.parent_ids + [payload_prov.provenance_id],
        )

    def from_finding(
        self,
        *,
        repository_id: UUID | str,
        finding: Any,
        known_repo_paths: Sequence[str] | None = None,
        base_revision: str | None = None,
    ) -> TaskIntakePayload:
        """Convert a Week 2 AnalysisFinding directly into a TaskIntakePayload with complete provenance."""
        repo_uuid = UUID(str(repository_id)) if not isinstance(repository_id, UUID) else repository_id
        title, body, labels = format_issue_from_finding(finding)

        finding_id = str(
            getattr(finding, "id", None)
            or (finding.get("id") if isinstance(finding, dict) else "unknown_finding")
        )
        finding_desc = str(
            getattr(finding, "description", None)
            or (finding.get("description") if isinstance(finding, dict) else title)
        )
        finding_evidence = str(
            getattr(finding, "evidence", None)
            or (finding.get("evidence") if isinstance(finding, dict) else "")
        )

        tracker = get_taint_tracker()
        desc_prov = tracker.register_source(
            source_type="finding_description",
            source_id=finding_id,
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            tainted=True,
            source_repository_id=str(repo_uuid),
            metadata={"finding_id": finding_id, "title": title},
        )

        evidence_prov = tracker.register_source(
            source_type="finding_evidence",
            source_id=finding_id,
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            tainted=True,
            source_repository_id=str(repo_uuid),
            parent_ids=[desc_prov.provenance_id],
            metadata={"evidence_length": len(finding_evidence)},
        )

        parent_prov_ids = [desc_prov.provenance_id, evidence_prov.provenance_id]

        target_files = extract_safe_repo_paths(
            f"{title}\n{body}",
            known_repo_paths=known_repo_paths,
            forbidden_files=self._protected_files,
        )

        req_prov = tracker.propagate(
            parent_ids=parent_prov_ids,
            transformation="intake_finding_requirement_extraction",
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            source_type="task_requirement",
            metadata={"finding_id": finding_id},
            source_repository_id=str(repo_uuid),
        )

        requirements = [
            TaskRequirement(
                id="req-1",
                description=f"Resolve finding [{finding_id}]: {title}",
                category="bug_fix",
                target_files=target_files,
                acceptance_criteria=[
                    f"Fix defect identified in finding {finding_id}.",
                    "Verify all existing tests pass.",
                ],
                provenance=req_prov,
                provenance_ids=[req_prov.provenance_id],
            )
        ]

        asm_prov = tracker.propagate(
            parent_ids=parent_prov_ids,
            transformation="intake_finding_assumption_derivation",
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            source_type="task_assumption",
            metadata={"finding_id": finding_id},
            source_repository_id=str(repo_uuid),
        )

        assumptions = [
            TaskAssumption(
                id="asm-1",
                description="Target defect localized to candidate files from finding evidence.",
                unresolved=len(target_files) == 0,
                risk_level="low" if target_files else "medium",
                provenance=asm_prov,
                provenance_ids=[asm_prov.provenance_id],
            )
        ]

        source_ref = TaskSourceReference(
            type="BUG_FINDING",
            finding_id=finding_id,
            repository_id=str(repo_uuid),
        )

        default_constraints = self._default_constraints()
        constraint_prov_ids = [c.provenance.provenance_id for c in default_constraints if c.provenance]

        payload_prov = tracker.propagate(
            parent_ids=parent_prov_ids + constraint_prov_ids,
            transformation="intake_finding_payload_aggregation",
            trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
            source_type="task_intake_payload",
            source_repository_id=str(repo_uuid),
        )

        return TaskIntakePayload(
            repository_id=repo_uuid,
            title=title[:256],
            description=body,
            source=source_ref,
            requirements=requirements,
            assumptions=assumptions,
            constraints=default_constraints,
            base_revision=base_revision,
            provenance=payload_prov,
            provenance_ids=payload_prov.parent_ids + [payload_prov.provenance_id],
        )

    def from_user_prompt(
        self,
        *,
        repository_id: UUID | str,
        user_id: str,
        prompt: str,
        title: str | None = None,
        target_files: Sequence[str] | None = None,
        base_revision: str | None = None,
    ) -> TaskIntakePayload:
        """Convert an authenticated user prompt into a TaskIntakePayload with USER_PROVIDED trust."""
        repo_uuid = UUID(str(repository_id)) if not isinstance(repository_id, UUID) else repository_id
        safe_prompt = redact((prompt or "").strip())
        safe_title = redact((title or safe_prompt[:60]).strip()) or "User Development Task"

        tracker = get_taint_tracker()
        user_prov = tracker.register_source(
            source_type="user_prompt",
            source_id=str(user_id),
            trust_level=TrustLevel.USER_PROVIDED,
            tainted=False,
            source_repository_id=str(repo_uuid),
            metadata={"user_id": str(user_id)},
        )

        clean_files = list(target_files or [])
        req_prov = tracker.propagate(
            parent_ids=[user_prov.provenance_id],
            transformation="user_prompt_requirement_extraction",
            trust_level=TrustLevel.USER_PROVIDED,
            source_type="task_requirement",
            source_repository_id=str(repo_uuid),
        )

        requirements = [
            TaskRequirement(
                id="req-1",
                description=safe_prompt,
                category="functional",
                target_files=clean_files,
                acceptance_criteria=["Implement requested changes per user prompt."],
                provenance=req_prov,
                provenance_ids=[req_prov.provenance_id],
            )
        ]

        default_constraints = self._default_constraints()
        constraint_prov_ids = [c.provenance.provenance_id for c in default_constraints if c.provenance]

        payload_prov = tracker.propagate(
            parent_ids=[user_prov.provenance_id] + constraint_prov_ids,
            transformation="user_task_payload_aggregation",
            trust_level=TrustLevel.USER_PROVIDED,
            source_type="task_intake_payload",
            source_repository_id=str(repo_uuid),
        )

        source_ref = TaskSourceReference(
            type="USER_PROMPT",
            repository_id=str(repo_uuid),
        )

        return TaskIntakePayload(
            repository_id=repo_uuid,
            title=safe_title[:256],
            description=safe_prompt,
            source=source_ref,
            requirements=requirements,
            assumptions=[],
            constraints=default_constraints,
            base_revision=base_revision,
            provenance=payload_prov,
            provenance_ids=[user_prov.provenance_id, payload_prov.provenance_id],
        )


__all__ = [
    "IssueToTaskAdapter",
    "extract_safe_repo_paths",
    "fence_untrusted_issue_data",
    "format_issue_from_finding",
]

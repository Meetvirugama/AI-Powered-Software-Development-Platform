"""Provenance and Trust Level Models for Untrusted Data Lineage.

Reference:
- Greshake et al. (Indirect Prompt Injection)
- CaMeL (Separation of Control Flow & Data Flow)
- Task Security Specification (§3 Provenance Foundation)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import secrets
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core.secret_redaction import redact


class TrustLevel(str, Enum):
    """Trust tier classifications assigned by trusted backend platform code."""

    SYSTEM = "SYSTEM"                      # Internal platform kernel / framework invariants
    PLATFORM = "PLATFORM"                  # Platform-generated constraints, tools, allowlists
    USER_APPROVED = "USER_APPROVED"        # Explicitly reviewed and authorized by verified human operator
    USER_PROVIDED = "USER_PROVIDED"        # Prompt or parameters directly supplied by authenticated user
    EXTERNAL_UNTRUSTED = "EXTERNAL_UNTRUSTED"  # GitHub issues, external comments, untrusted webhooks/evidence
    MODEL_GENERATED = "MODEL_GENERATED"    # Synthesized by LLM or autonomous agent


class DataProvenance(BaseModel):
    """Immutable metadata tracking the origin, lineage, and taint status of data."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    provenance_id: str = Field(
        default_factory=lambda: f"prov-{uuid4().hex[:12]}",
        description="Globally unique provenance identifier.",
    )
    source_type: str = Field(
        ...,
        description="Category of origin: github_issue, github_comment, finding_evidence, user_prompt, platform_constraint, etc.",
    )
    source_id: str | None = Field(
        default=None,
        description="External source identifier (e.g. issue number, finding UUID).",
    )
    source_repository_id: str | None = Field(
        default=None,
        description="Target repository UUID string when applicable.",
    )
    source_reference: str | None = Field(
        default=None,
        description="Contextual reference descriptor (e.g. URL, file path, commit SHA).",
    )
    trust_level: TrustLevel = Field(
        ...,
        description="Platform-assigned trust level. Must never be set directly by LLM content.",
    )
    tainted: bool = Field(
        ...,
        description="True if originated from or influenced by an untrusted external entity.",
    )
    parent_ids: list[str] = Field(
        default_factory=list,
        description="List of parent provenance IDs from which this data was derived.",
    )
    transformation: str | None = Field(
        default=None,
        description="Description of the operation that created this entity (e.g. intake_fence, llm_plan, replan_recovery).",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of provenance record creation.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional non-sensitive provenance context (e.g. requirement_id, step_id).",
    )

    def is_tainted(self) -> bool:
        """Return True if this entity is classified as tainted or untrusted."""
        return self.tainted or self.trust_level == TrustLevel.EXTERNAL_UNTRUSTED

    def to_dict(self) -> dict[str, Any]:
        """Serialize provenance record to a clean dictionary."""
        return self.model_dump(mode="json")


def create_provenance(
    *,
    source_type: str,
    trust_level: TrustLevel,
    tainted: bool | None = None,
    source_id: str | None = None,
    source_repository_id: str | None = None,
    source_reference: str | None = None,
    parent_ids: list[str] | None = None,
    transformation: str | None = None,
    metadata: dict[str, Any] | None = None,
    provenance_id: str | None = None,
) -> DataProvenance:
    """Factory creating an immutable DataProvenance record with deterministic defaults."""
    # By default, EXTERNAL_UNTRUSTED is always tainted.
    is_tainted = (
        True
        if trust_level == TrustLevel.EXTERNAL_UNTRUSTED
        else (bool(tainted) if tainted is not None else False)
    )

    clean_meta = dict(metadata or {})
    if source_reference:
        source_reference = redact(str(source_reference))

    kwargs: dict[str, Any] = {
        "source_type": source_type,
        "trust_level": trust_level,
        "tainted": is_tainted,
        "source_id": str(source_id) if source_id is not None else None,
        "source_repository_id": str(source_repository_id) if source_repository_id is not None else None,
        "source_reference": source_reference,
        "parent_ids": list(parent_ids or []),
        "transformation": transformation,
        "metadata": clean_meta,
    }
    if provenance_id:
        kwargs["provenance_id"] = provenance_id

    return DataProvenance(**kwargs)


__all__ = [
    "DataProvenance",
    "TrustLevel",
    "create_provenance",
]

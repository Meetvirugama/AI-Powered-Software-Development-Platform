"""Taint Tracking Engine for Data Provenance and Lineage Propagation.

Reference:
- Greshake et al. (Indirect Prompt Injection)
- CaMeL (Separation of Control Flow & Data Flow)
- Task Security Specification (§4 Taint Tracking)
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ai.security.provenance import DataProvenance, TrustLevel, create_provenance

logger = logging.getLogger(__name__)

# Canonical transformations that involve model synthesis
_MODEL_TRANSFORMATIONS = frozenset({
    "llm_plan",
    "llm_edit",
    "llm_replan",
    "llm_synthesis",
    "llm_summarize",
    "model_generation",
    "agent_reasoning",
})


class TaintTracker:
    """Thread-safe in-memory registry and propagation engine for data provenance."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registry: dict[str, DataProvenance] = {}

    def register_source(
        self,
        *,
        source_type: str,
        trust_level: TrustLevel = TrustLevel.EXTERNAL_UNTRUSTED,
        tainted: bool | None = None,
        source_id: str | None = None,
        source_repository_id: str | None = None,
        source_reference: str | None = None,
        parent_ids: list[str] | None = None,
        transformation: str | None = None,
        metadata: dict[str, Any] | None = None,
        provenance_id: str | None = None,
    ) -> DataProvenance:
        """Register a new source entity and return its immutable DataProvenance record."""
        prov = create_provenance(
            source_type=source_type,
            trust_level=trust_level,
            tainted=tainted,
            source_id=source_id,
            source_repository_id=source_repository_id,
            source_reference=source_reference,
            parent_ids=parent_ids,
            transformation=transformation,
            metadata=metadata,
            provenance_id=provenance_id,
        )
        with self._lock:
            self._registry[prov.provenance_id] = prov
        return prov

    def propagate(
        self,
        *,
        parent_ids: list[str],
        transformation: str,
        trust_level: TrustLevel | None = None,
        source_type: str = "derived",
        metadata: dict[str, Any] | None = None,
        source_repository_id: str | None = None,
        source_reference: str | None = None,
    ) -> DataProvenance:
        """Propagate taint and lineage across transformations.

        Security Invariants:
        1. If ANY parent is tainted or untrusted, child is marked tainted.
        2. Missing parent provenance fails closed (marks child as tainted).
        3. Model generation cannot escalate trust: any transformation involving LLMs
           caps trust level at MODEL_GENERATED, regardless of requested trust level.
        4. Taint history cannot be erased by downstream summarization or transformations.
        """
        clean_parents = [str(pid) for pid in (parent_ids or []) if pid]
        any_tainted = False
        lowest_trust = TrustLevel.SYSTEM
        has_external_parent = False
        all_parents_found = True

        with self._lock:
            parent_records: list[DataProvenance] = []
            for pid in clean_parents:
                record = self._registry.get(pid)
                if record is None:
                    # Missing parent provenance fails closed
                    all_parents_found = False
                    any_tainted = True
                    logger.warning("Provenance propagation with unregistered parent ID: %s (failing closed)", pid)
                else:
                    parent_records.append(record)
                    if record.is_tainted():
                        any_tainted = True
                    if record.trust_level == TrustLevel.EXTERNAL_UNTRUSTED:
                        has_external_parent = True

        # Check if transformation is model synthesis
        trans_lower = transformation.lower()
        is_model_op = any(m in trans_lower for m in ("llm", "model", "synthesiz", "agent"))

        # Determine trust level safely
        if is_model_op:
            # Model output can never escalate to SYSTEM, PLATFORM, or USER_APPROVED
            assigned_trust = TrustLevel.MODEL_GENERATED
        elif has_external_parent or not all_parents_found:
            # External untrusted input cannot escalate
            assigned_trust = (
                trust_level
                if trust_level in (TrustLevel.EXTERNAL_UNTRUSTED, TrustLevel.MODEL_GENERATED)
                else TrustLevel.EXTERNAL_UNTRUSTED
            )
        elif trust_level is not None:
            assigned_trust = trust_level
        else:
            # Inherit lowest trust level among found parents
            if parent_records:
                # Trust ranking from least to most trusted
                trust_ranks = {
                    TrustLevel.EXTERNAL_UNTRUSTED: 0,
                    TrustLevel.MODEL_GENERATED: 1,
                    TrustLevel.USER_PROVIDED: 2,
                    TrustLevel.USER_APPROVED: 3,
                    TrustLevel.PLATFORM: 4,
                    TrustLevel.SYSTEM: 5,
                }
                min_record = min(parent_records, key=lambda r: trust_ranks.get(r.trust_level, 0))
                assigned_trust = min_record.trust_level
            else:
                assigned_trust = TrustLevel.EXTERNAL_UNTRUSTED
                any_tainted = True

        # Inherit repository ID if not supplied
        if not source_repository_id and parent_records:
            for pr in parent_records:
                if pr.source_repository_id:
                    source_repository_id = pr.source_repository_id
                    break

        child_prov = create_provenance(
            source_type=source_type,
            trust_level=assigned_trust,
            tainted=any_tainted,
            parent_ids=clean_parents,
            transformation=transformation,
            metadata=metadata,
            source_repository_id=source_repository_id,
            source_reference=source_reference,
        )

        with self._lock:
            self._registry[child_prov.provenance_id] = child_prov

        return child_prov

    def get(self, provenance_id: str) -> DataProvenance | None:
        """Retrieve a provenance record by ID."""
        if not provenance_id:
            return None
        with self._lock:
            return self._registry.get(str(provenance_id))

    def validate_provenance(self, provenance_id: str) -> bool:
        """Validate that a provenance ID exists and is properly registered. Fails closed."""
        if not provenance_id:
            return False
        with self._lock:
            return str(provenance_id) in self._registry

    def is_tainted(self, provenance_id: str | None) -> bool:
        """Check if an entity is tainted. Fails closed (missing ID returns True)."""
        if not provenance_id:
            return True
        with self._lock:
            record = self._registry.get(str(provenance_id))
            if record is None:
                return True
            return record.is_tainted()

    def get_lineage(self, provenance_id: str) -> list[DataProvenance]:
        """Traverse the parent DAG to return the full ancestor lineage in order."""
        if not provenance_id:
            return []

        lineage: list[DataProvenance] = []
        visited: set[str] = set()
        queue: list[str] = [str(provenance_id)]

        with self._lock:
            while queue:
                curr_id = queue.pop(0)
                if curr_id in visited:
                    continue
                visited.add(curr_id)

                record = self._registry.get(curr_id)
                if record is not None:
                    lineage.append(record)
                    for pid in record.parent_ids:
                        if pid not in visited:
                            queue.append(pid)

        return lineage

    def serialize(self, provenance: DataProvenance | str) -> dict[str, Any]:
        """Serialize a provenance record to a JSON-safe dictionary."""
        if isinstance(provenance, str):
            record = self.get(provenance)
            if not record:
                raise ValueError(f"Provenance record '{provenance}' not found.")
            return record.to_dict()
        return provenance.to_dict()

    def deserialize(self, data: dict[str, Any]) -> DataProvenance:
        """Deserialize and register a provenance dictionary, preserving exact metadata."""
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary for provenance deserialization.")
        prov = DataProvenance(**data)
        with self._lock:
            self._registry[prov.provenance_id] = prov
        return prov

    def clear(self) -> None:
        """Clear all registered provenance records (for test isolation)."""
        with self._lock:
            self._registry.clear()


# Process-wide singleton instance
_GLOBAL_TAINT_TRACKER = TaintTracker()


def get_taint_tracker() -> TaintTracker:
    """Return the global process-wide TaintTracker instance."""
    return _GLOBAL_TAINT_TRACKER


def reset_taint_tracker() -> None:
    """Reset the global TaintTracker (used in unit test fixtures)."""
    _GLOBAL_TAINT_TRACKER.clear()


__all__ = [
    "TaintTracker",
    "get_taint_tracker",
    "reset_taint_tracker",
]

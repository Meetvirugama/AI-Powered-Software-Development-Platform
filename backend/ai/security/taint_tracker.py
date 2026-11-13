"""Taint Tracking Engine for Data Provenance and Lineage Propagation."""

from __future__ import annotations

import logging
import threading
from typing import Any

from ai.security.provenance import DataProvenance, TrustLevel, create_provenance

logger = logging.getLogger(__name__)

MAX_PROVENANCE_REGISTRY_ENTRIES = 10_000

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
    """Thread-safe bounded in-memory registry and propagation engine for data provenance."""

    def __init__(self, max_entries: int = MAX_PROVENANCE_REGISTRY_ENTRIES) -> None:
        self._lock = threading.RLock()
        self._max_entries = max(100, int(max_entries))
        self._registry: dict[str, DataProvenance] = {}

    def _store_bounded(self, prov: DataProvenance) -> None:
        """Insert provenance record while bounding memory growth via FIFO eviction."""
        with self._lock:
            if prov.provenance_id not in self._registry and len(self._registry) >= self._max_entries:
                oldest_key = next(iter(self._registry))
                self._registry.pop(oldest_key, None)
            self._registry[prov.provenance_id] = prov

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
        self._store_bounded(prov)
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
        """Propagate taint and lineage across transformations."""
        clean_parents = [str(pid) for pid in (parent_ids or []) if pid]
        any_tainted = False
        has_external_parent = False
        all_parents_found = True

        with self._lock:
            parent_records: list[DataProvenance] = []
            for pid in clean_parents:
                record = self._registry.get(pid)
                if record is None:
                    all_parents_found = False
                    any_tainted = True
                    logger.warning("Provenance propagation with unregistered parent ID: %s (failing closed)", pid)
                else:
                    parent_records.append(record)
                    if record.is_tainted():
                        any_tainted = True
                    if record.trust_level == TrustLevel.EXTERNAL_UNTRUSTED:
                        has_external_parent = True

        trans_lower = transformation.lower()
        is_model_op = any(m in trans_lower for m in ("llm", "model", "synthesiz", "agent"))

        if is_model_op:
            assigned_trust = TrustLevel.MODEL_GENERATED
        elif has_external_parent or not all_parents_found:
            assigned_trust = (
                trust_level
                if trust_level in (TrustLevel.EXTERNAL_UNTRUSTED, TrustLevel.MODEL_GENERATED)
                else TrustLevel.EXTERNAL_UNTRUSTED
            )
        elif trust_level is not None:
            assigned_trust = trust_level
        else:
            if parent_records:
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

        self._store_bounded(child_prov)
        return child_prov

    def get(self, provenance_id: str) -> DataProvenance | None:
        if not provenance_id:
            return None
        with self._lock:
            return self._registry.get(str(provenance_id))

    def validate_provenance(self, provenance_id: str) -> bool:
        if not provenance_id:
            return False
        with self._lock:
            return str(provenance_id) in self._registry

    def is_tainted(self, provenance_id: str | None) -> bool:
        if not provenance_id:
            return True
        with self._lock:
            record = self._registry.get(str(provenance_id))
            if record is None:
                return True
            return record.is_tainted()

    def get_lineage(self, provenance_id: str) -> list[DataProvenance]:
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
        if isinstance(provenance, str):
            record = self.get(provenance)
            if not record:
                raise ValueError(f"Provenance record '{provenance}' not found.")
            return record.to_dict()
        return provenance.to_dict()

    def deserialize(self, data: dict[str, Any]) -> DataProvenance:
        """Deserialize and register a provenance dictionary, enforcing taint invariants on EXTERNAL_UNTRUSTED."""
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary for provenance deserialization.")
        normalized = dict(data)
        raw_trust = normalized.get("trust_level")
        if raw_trust in (TrustLevel.EXTERNAL_UNTRUSTED, TrustLevel.EXTERNAL_UNTRUSTED.value, "EXTERNAL_UNTRUSTED"):
            normalized["tainted"] = True
        prov = DataProvenance(**normalized)
        self._store_bounded(prov)
        return prov

    def clear(self) -> None:
        with self._lock:
            self._registry.clear()


_GLOBAL_TAINT_TRACKER = TaintTracker()


def get_taint_tracker() -> TaintTracker:
    return _GLOBAL_TAINT_TRACKER


def reset_taint_tracker() -> None:
    _GLOBAL_TAINT_TRACKER.clear()


__all__ = [
    "MAX_PROVENANCE_REGISTRY_ENTRIES",
    "TaintTracker",
    "get_taint_tracker",
    "reset_taint_tracker",
]

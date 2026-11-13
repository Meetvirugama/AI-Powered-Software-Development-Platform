"""Tests for serialization, deserialization, and legacy schema compatibility.

Reference:
- task.md §6 (Integrate with Task and Plan Schemas)
- task.md §11 (Test 8: Serialization and deserialization preserve provenance)
- task.md §12 (Backward Compatibility)
"""

import pytest

from ai.security.provenance import DataProvenance, TrustLevel
from ai.security.taint_tracker import TaintTracker
from app.schemas.plan import PlanStep
from app.schemas.task import TaskRequirement


def test_provenance_serialization_roundtrip():
    """Verify serialization to dict and deserialization restores exact provenance attributes."""
    tracker = TaintTracker()
    original = tracker.register_source(
        source_type="github_issue",
        source_id="601",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
        source_repository_id="repo-1234",
        source_reference="https://github.com/org/repo/issues/601",
        metadata={"priority": "high", "reporter": "alice"},
    )

    data = tracker.serialize(original)
    assert data["provenance_id"] == original.provenance_id
    assert data["trust_level"] == "EXTERNAL_UNTRUSTED"
    assert data["tainted"] is True
    assert data["metadata"]["reporter"] == "alice"

    restored = tracker.deserialize(data)
    assert restored.provenance_id == original.provenance_id
    assert restored.source_id == "601"
    assert restored.trust_level == TrustLevel.EXTERNAL_UNTRUSTED
    assert restored.tainted is True
    assert restored.source_repository_id == "repo-1234"


def test_plan_step_provenance_serialization():
    """PlanStep serializes and deserializes provenance and field_provenance safely."""
    prov = DataProvenance(
        provenance_id="prov-step-999",
        source_type="plan_step",
        trust_level=TrustLevel.MODEL_GENERATED,
        tainted=True,
    )

    step = PlanStep(
        step_id="step_serialize",
        title="Test Serialization",
        description="Verify JSON dump and load",
        action_type="modify",
        expected_files=["app/test.py"],
        provenance=prov,
        provenance_ids=["prov-step-999", "prov-root-1"],
        taint_status=True,
        field_provenance={"description": "prov-root-1"},
    )

    step_dict = step.model_dump(mode="json")
    assert step_dict["provenance"]["provenance_id"] == "prov-step-999"
    assert step_dict["taint_status"] is True
    assert step_dict["field_provenance"]["description"] == "prov-root-1"

    # Reload from dumped JSON
    reloaded_step = PlanStep.model_validate(step_dict)
    assert reloaded_step.provenance is not None
    assert reloaded_step.provenance.provenance_id == "prov-step-999"
    assert reloaded_step.taint_status is True
    assert reloaded_step.provenance_ids == ["prov-step-999", "prov-root-1"]


def test_legacy_payload_compatibility():
    """Legacy TaskRequirement and PlanStep without provenance parse safely without errors."""
    legacy_req_data = {
        "id": "req-legacy-1",
        "description": "Legacy requirement with no provenance attached",
        "category": "functional",
        "target_files": ["src/main.py"],
    }
    req = TaskRequirement.model_validate(legacy_req_data)
    assert req.id == "req-legacy-1"
    assert req.provenance is None
    assert req.provenance_ids == []

    legacy_step_data = {
        "step_id": "step_legacy_1",
        "title": "Legacy step",
        "description": "Legacy plan step without provenance fields",
        "action_type": "inspect",
        "expected_files": ["src/main.py"],
    }
    step = PlanStep.model_validate(legacy_step_data)
    assert step.step_id == "step_legacy_1"
    assert step.provenance is None
    assert step.provenance_ids == []
    assert step.taint_status is False

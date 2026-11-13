"""Unit tests for DataProvenance models and TrustLevel classifications.

Reference:
- task.md §3 (Implement Provenance Foundation)
- task.md §11 (Test 1, 8, 20)
"""

import pytest
from pydantic import ValidationError

from ai.security.provenance import DataProvenance, TrustLevel, create_provenance


def test_trust_level_enum_values():
    """Verify all 6 canonical trust levels are available."""
    expected = {
        "SYSTEM",
        "PLATFORM",
        "USER_APPROVED",
        "USER_PROVIDED",
        "EXTERNAL_UNTRUSTED",
        "MODEL_GENERATED",
    }
    assert {tl.value for tl in TrustLevel} == expected


def test_provenance_immutability():
    """Verify that DataProvenance is frozen and cannot be modified after creation."""
    prov = create_provenance(
        source_type="github_issue",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    with pytest.raises(ValidationError):
        # Attempting mutation must fail on frozen model
        prov.tainted = False


def test_external_untrusted_is_always_tainted_by_default():
    """EXTERNAL_UNTRUSTED source data defaults to tainted=True."""
    prov = create_provenance(
        source_type="github_issue",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
    )
    assert prov.tainted is True
    assert prov.is_tainted() is True


def test_provenance_secret_redaction_in_reference():
    """Verify that secrets in source_reference are automatically scrubbed."""
    raw_ref = "https://github.com/org/repo/issues/1?token=ghp_123456789012345678901234567890123456"
    prov = create_provenance(
        source_type="github_issue",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        source_reference=raw_ref,
    )
    assert "ghp_" not in prov.source_reference
    assert "[REDACTED" in prov.source_reference


def test_provenance_to_dict_and_roundtrip():
    """Verify that DataProvenance serializes cleanly and can be recreated."""
    prov = create_provenance(
        source_type="platform_constraint",
        trust_level=TrustLevel.PLATFORM,
        tainted=False,
        metadata={"rule": "forbidden_files"},
    )
    data = prov.to_dict()
    assert data["source_type"] == "platform_constraint"
    assert data["trust_level"] == "PLATFORM"
    assert data["tainted"] is False

    restored = DataProvenance(**data)
    assert restored.provenance_id == prov.provenance_id
    assert restored.metadata == prov.metadata

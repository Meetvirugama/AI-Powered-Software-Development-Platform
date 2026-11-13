"""Unit tests for TaintTracker registry and lookup operations.

Reference:
- task.md §4 (Implement Taint Tracking)
- task.md §11 (Test 9: Missing provenance cannot silently become trusted)
"""

import pytest

from ai.security.provenance import TrustLevel
from ai.security.taint_tracker import TaintTracker


@pytest.fixture
def tracker():
    return TaintTracker()


def test_register_and_get_source(tracker):
    """Verify registering a source provenance record and looking it up."""
    prov = tracker.register_source(
        source_type="github_issue",
        source_id="101",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    retrieved = tracker.get(prov.provenance_id)
    assert retrieved is not None
    assert retrieved.provenance_id == prov.provenance_id
    assert retrieved.source_id == "101"
    assert retrieved.trust_level == TrustLevel.EXTERNAL_UNTRUSTED


def test_validate_provenance_fails_closed_for_missing_ids(tracker):
    """Missing or unregistered provenance IDs must fail closed."""
    assert tracker.validate_provenance("") is False
    assert tracker.validate_provenance("prov-nonexistent") is False
    # is_tainted must fail closed (return True for missing ID)
    assert tracker.is_tainted(None) is True
    assert tracker.is_tainted("prov-nonexistent") is True


def test_get_lineage_dag_traversal(tracker):
    """Verify recursive DAG lineage traversal back to root sources."""
    # Root 1: GitHub issue
    root_issue = tracker.register_source(
        source_type="github_issue",
        source_id="42",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    # Root 2: Platform constraint
    root_plat = tracker.register_source(
        source_type="platform_constraint",
        source_id="cst-1",
        trust_level=TrustLevel.PLATFORM,
        tainted=False,
    )
    # Child 1: Requirement derived from issue
    req_prov = tracker.propagate(
        parent_ids=[root_issue.provenance_id],
        transformation="requirement_extraction",
    )
    # Child 2: Step derived from requirement + platform
    step_prov = tracker.propagate(
        parent_ids=[req_prov.provenance_id, root_plat.provenance_id],
        transformation="plan_step_creation",
    )

    lineage = tracker.get_lineage(step_prov.provenance_id)
    lineage_ids = [p.provenance_id for p in lineage]

    assert step_prov.provenance_id in lineage_ids
    assert req_prov.provenance_id in lineage_ids
    assert root_issue.provenance_id in lineage_ids
    assert root_plat.provenance_id in lineage_ids

"""Unit tests for taint propagation and trust escalation prevention.

Reference:
- task.md §4 (Taint Tracking Rules)
- task.md §11 (Tests 4, 5, 6, 9)
"""

import pytest

from ai.security.provenance import TrustLevel
from ai.security.taint_tracker import TaintTracker


@pytest.fixture
def tracker():
    return TaintTracker()


def test_taint_propagates_from_untrusted_parent(tracker):
    """If a parent is untrusted, child inherits taint."""
    parent = tracker.register_source(
        source_type="github_issue",
        source_id="202",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    child = tracker.propagate(
        parent_ids=[parent.provenance_id],
        transformation="requirement_extraction",
    )
    assert child.tainted is True
    assert child.is_tainted() is True
    assert child.parent_ids == [parent.provenance_id]


def test_multiple_input_sources_with_mixed_trust(tracker):
    """Combining trusted platform context and untrusted issue results in tainted child."""
    issue_prov = tracker.register_source(
        source_type="github_issue",
        source_id="203",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    platform_prov = tracker.register_source(
        source_type="platform_context",
        trust_level=TrustLevel.PLATFORM,
        tainted=False,
    )

    child = tracker.propagate(
        parent_ids=[issue_prov.provenance_id, platform_prov.provenance_id],
        transformation="task_synthesis",
    )
    assert child.tainted is True
    assert child.is_tainted() is True
    assert issue_prov.provenance_id in child.parent_ids
    assert platform_prov.provenance_id in child.parent_ids


def test_llm_transformation_cannot_escalate_trust(tracker):
    """LLM synthesis transformation cannot claim SYSTEM or PLATFORM trust."""
    parent = tracker.register_source(
        source_type="github_issue",
        source_id="204",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    # Even if caller requests SYSTEM trust, LLM transformation caps it at MODEL_GENERATED
    child = tracker.propagate(
        parent_ids=[parent.provenance_id],
        transformation="llm_plan_generation",
        trust_level=TrustLevel.SYSTEM,
    )
    assert child.trust_level == TrustLevel.MODEL_GENERATED
    assert child.tainted is True


def test_summarization_does_not_remove_taint(tracker):
    """Summarizing untrusted data preserves taint lineage."""
    parent = tracker.register_source(
        source_type="github_comment",
        source_id="999",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )
    child = tracker.propagate(
        parent_ids=[parent.provenance_id],
        transformation="llm_summarize_issue",
    )
    assert child.tainted is True
    assert child.is_tainted() is True
    assert child.trust_level == TrustLevel.MODEL_GENERATED


def test_propagation_with_unregistered_parent_fails_closed(tracker):
    """Referencing an unknown/unregistered parent provenance ID fails closed."""
    child = tracker.propagate(
        parent_ids=["prov-phantom-1234"],
        transformation="unverified_derivation",
        trust_level=TrustLevel.PLATFORM,
    )
    assert child.tainted is True
    assert child.trust_level == TrustLevel.EXTERNAL_UNTRUSTED

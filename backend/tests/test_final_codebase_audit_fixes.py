"""Final Post-Week-3 Codebase Deep-Sweep & Security Audit Regression Suite.

Verifies fixes for:
1. BUG-FINAL-05: Zero PytestCollectionWarnings on `TestCounts`,
   `TestGenerationResponse`, and `TestGenerationServiceProtocol`.
"""

from __future__ import annotations

from ai.interfaces import TestGenerationServiceProtocol
from app.schemas.analysis import TestGenerationResponse
from app.schemas.task import TestCounts


def test_pytest_collection_flags_disabled_on_schema_and_protocol_classes() -> None:
    """Verify __test__ = False is set on non-test classes starting with 'Test'."""
    assert getattr(TestCounts, "__test__", None) is False
    assert getattr(TestGenerationResponse, "__test__", None) is False
    assert getattr(TestGenerationServiceProtocol, "__test__", None) is False

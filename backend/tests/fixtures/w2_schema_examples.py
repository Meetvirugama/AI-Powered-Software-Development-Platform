"""Representative valid and invalid example payloads for Week 2 AI output schemas.

Owner: Dev — W2, Day 1 (Example Structured Outputs Deliverable)
Reference: Docs/week2.md §5 (Day 1 Deliverables)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Feature 1: Code Explanation Examples
# ---------------------------------------------------------------------------

VALID_CODE_EXPLANATION_DICT = {
    "purpose": "Calculates exponential backoff delay with full jitter for distributed retries.",
    "logic_flow": [
        "1. Read base delay and attempt counter.",
        "2. Compute unbounded exponential backoff factor.",
        "3. Clamp delay using configured maximum ceiling.",
        "4. Apply uniform random jitter between 0 and computed delay.",
    ],
    "key_symbols": [
        {
            "name": "calculate_backoff",
            "kind": "function",
            "role": "Calculates jittered backoff seconds given retry count.",
            "start_line": 15,
            "end_line": 30,
        },
        {
            "name": "MAX_BACKOFF_SECONDS",
            "kind": "variable",
            "role": "Constant upper bound for retry delay.",
            "start_line": 5,
            "end_line": 5,
        },
    ],
    "inputs_and_outputs": "Takes attempt (int), base_delay (float). Returns float delay in seconds.",
    "dependencies": ["random.uniform", "math.pow"],
    "assumptions_and_limitations": [
        "Assumes non-negative attempt counter.",
        "Clock drift or thread contention is not handled here.",
    ],
    "sources": [
        {
            "file_path": "backend/app/core/retry.py",
            "start_line": 15,
            "end_line": 30,
            "symbol_name": "calculate_backoff",
        }
    ],
    "confidence": "high",
    "missing_context": [],
}

INVALID_CODE_EXPLANATION_BLANK_PURPOSE = {
    "purpose": "   ",  # Blank purpose rejected by validator
    "inputs_and_outputs": "Takes attempt, returns delay.",
}

# ---------------------------------------------------------------------------
# Feature 2: Bug Detection Examples
# ---------------------------------------------------------------------------

VALID_BUG_FINDING_DICT = {
    "id": "bug-bf7102a",
    "category": "off_by_one",
    "severity": "HIGH",
    "title": "Potential off-by-one index access in loop boundary",
    "description": "Loop iterates using `range(len(items) + 1)`, causing IndexError on final iteration.",
    "source_reference": {
        "file_path": "backend/scanner/parser.py",
        "start_line": 42,
        "end_line": 45,
    },
    "evidence": "for i in range(len(items) + 1): item = items[i]",
    "suggested_fix": "Replace `range(len(items) + 1)` with `range(len(items))` or enumerate.",
    "confidence": "high",
    "is_uncertain": False,
    "source_type": "AI",
    "rule_id": "OFF_BY_ONE_LOOP",
}

INVALID_BUG_FINDING_NEGATIVE_LINE = {
    "id": "bug-invalid",
    "category": "null_safety",
    "severity": "CRITICAL",
    "title": "Null dereference",
    "description": "Accessing .id on None",
    "source_reference": {
        "file_path": "backend/scanner/parser.py",
        "start_line": -5,  # Invalid: line numbers must be >= 1
    },
    "evidence": "user.id",
}

# ---------------------------------------------------------------------------
# Feature 3: Test Generation Examples
# ---------------------------------------------------------------------------

VALID_TEST_GENERATION_RESULT_DICT = {
    "detected_framework": "pytest",
    "proposed_test_path": "tests/test_retry.py",
    "test_content": (
        "import pytest\n"
        "from app.core.retry import calculate_backoff\n\n"
        "def test_backoff_positive_range():\n"
        "    delay = calculate_backoff(attempt=1, base_delay=1.0)\n"
        "    assert 0.0 <= delay <= 2.0\n"
    ),
    "covered_scenarios": [
        {
            "name": "test_backoff_positive_range",
            "category": "normal",
            "description": "Verifies delay falls within expected range for attempt 1.",
        },
        {
            "name": "test_backoff_zero_attempt",
            "category": "edge_case",
            "description": "Verifies base delay behavior when attempt is 0.",
        },
    ],
    "assumptions_and_warnings": [
        "Assumes pytest is installed in the repository environment."
    ],
    "syntax_valid": True,
    "validation_errors": [],
    "sources": [
        {
            "file_path": "backend/app/core/retry.py",
            "start_line": 15,
            "end_line": 30,
        }
    ],
}

INVALID_TEST_GENERATION_PATH_TRAVERSAL = {
    "detected_framework": "pytest",
    "proposed_test_path": "../../tests/evil_test.py",  # Path traversal rejected
    "test_content": "def test_foo(): pass",
}

# ---------------------------------------------------------------------------
# Feature 4: Code Review Examples
# ---------------------------------------------------------------------------

VALID_REVIEW_REPORT_DICT = {
    "summary": "Overall change is clean. Found 1 potential SQL injection concern and 1 style improvement.",
    "risk_level": "HIGH",
    "findings": [
        {
            "id": "rev-001",
            "category": "security",
            "severity": "CRITICAL",
            "title": "Raw SQL query string interpolation",
            "description": "User input directly concatenated into SQL statement without parameterization.",
            "source_reference": {
                "file_path": "backend/app/repositories/user.py",
                "start_line": 88,
                "end_line": 89,
            },
            "evidence": "f\"SELECT * FROM users WHERE email = '{email}'\"",
            "suggested_fix": "Use parameterized queries with SQLAlchemy text(:email).",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "AI",
        }
    ],
    "total_findings": 1,
    "category_counts": {"security": 1},
    "missing_context": [],
}

INVALID_REVIEW_REPORT_BLANK_SUMMARY = {
    "summary": "   ",  # Blank summary rejected
    "risk_level": "LOW",
    "findings": [],
    "total_findings": 0,
}

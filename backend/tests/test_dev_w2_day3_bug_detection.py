"""Unit tests for Dev's Week 2 Day 3 BugDetectionEngine service.

Owner: Dev — W2, Day 3 Deliverable (Dedicated bug engine with schema validation)
Reference: Docs/week2.md §7 (BugDetectionEngine Requirements)

Acceptance Criteria:
- Detects defects across core categories (off_by_one, null_safety, resource_leak, etc.).
- Each finding includes location, evidence, suggested fix, and uncertainty flag.
- Prompt fences untrusted code and redacts secrets.
- Invalid output is repaired or raises LLMValidationError (no silent empty results).
- Unconfigured LLM gateway raises HTTP 503; disallowed providers raise HTTP 400.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.context.builder import ContextBuilder, TargetSnippet
from ai.interfaces import BugDetectionEngineProtocol, BugDetectionServiceProtocol
from ai.llm.schemas import LLMResponse, LLMValidationError
from ai.services.bug_detection_engine import BugDetectionEngine
from app.core.errors import APIError, ErrorCode
from app.schemas.analysis import AnalysisOptions, AnalysisTarget, BugDetectionRequest, BugFinding


@pytest.fixture
def sample_bug_request() -> BugDetectionRequest:
    return BugDetectionRequest(
        target=AnalysisTarget(
            type="file",
            path="backend/scanner/parser.py",
            start_line=1,
            end_line=50,
        ),
        options=AnalysisOptions(max_context_tokens=1500),
        include_static=False,
        include_ai=True,
    )


@pytest.fixture
def mock_llm_gateway() -> MagicMock:
    gateway = MagicMock()
    gateway.generate = AsyncMock()
    gateway.provider = SimpleNamespace(provider_name="gemini")
    return gateway


@pytest.mark.asyncio
async def test_bug_detection_engine_finds_ai_defects_across_categories(
    mock_llm_gateway: MagicMock,
    sample_bug_request: BugDetectionRequest,
) -> None:
    """Verifies that the engine returns structured findings across distinct defect categories."""
    mock_payload = {
        "findings": [
            {
                "id": "bug-001",
                "category": "off_by_one",
                "severity": "HIGH",
                "title": "Off-by-one loop boundary",
                "description": "Index exceeds bounds on final iteration of loop.",
                "source_reference": {
                    "file_path": "backend/scanner/parser.py",
                    "start_line": 25,
                    "end_line": 28,
                    "symbol_name": "parse_tokens",
                },
                "evidence": "for i in range(len(tokens) + 1):",
                "suggested_fix": "Use range(len(tokens))",
                "confidence": "high",
                "is_uncertain": False,
                "source_type": "AI",
            },
            {
                "id": "bug-002",
                "category": "null_safety",
                "severity": "CRITICAL",
                "title": "Unchecked None dereference",
                "description": "Attributes accessed without checking if parser returned None.",
                "source_reference": {
                    "file_path": "backend/scanner/parser.py",
                    "start_line": 35,
                    "end_line": 36,
                    "symbol_name": "parse_tokens",
                },
                "evidence": "node = parse(); node.children",
                "suggested_fix": "if node is not None: ...",
                "confidence": "high",
                "is_uncertain": False,
                "source_type": "AI",
            },
        ],
        "missing_context": ["imported_ast_helpers"],
    }
    mock_llm_gateway.generate.return_value = LLMResponse(
        content=json.dumps(mock_payload),
        model="gemini-flash-lite-latest",
    )

    engine = BugDetectionEngine(llm_gateway=mock_llm_gateway)
    repo_id = uuid4()

    snippet = TargetSnippet(
        file_path="backend/scanner/parser.py",
        content="def parse_tokens(): pass",
        start_line=1,
        end_line=50,
        symbol_name="parse_tokens",
        language="python",
    )
    context = ContextBuilder().build_intelligence_context(target=snippet, token_budget=1000)

    result = await engine.detect_bugs(
        repo_id,
        sample_bug_request,
        context=context,
        code_content="def parse_tokens(): pass",
    )

    findings = result["findings"]
    assert len(findings) == 2
    assert all(isinstance(f, BugFinding) for f in findings)

    # 1. Off-by-one finding
    f1 = findings[0]
    assert f1.category == "off_by_one"
    assert f1.severity == "HIGH"
    assert f1.source_reference.start_line == 25
    assert f1.evidence == "for i in range(len(tokens) + 1):"

    # 2. Null safety finding
    f2 = findings[1]
    assert f2.category == "null_safety"
    assert f2.severity == "CRITICAL"

    # Missing context preserved
    assert "imported_ast_helpers" in result["missing_context"]


@pytest.mark.asyncio
async def test_bug_detection_engine_uncertain_defect_handling(
    mock_llm_gateway: MagicMock,
    sample_bug_request: BugDetectionRequest,
) -> None:
    """Verifies that findings requiring external caller verification set is_uncertain: true."""
    mock_payload = {
        "findings": [
            {
                "id": "bug-003",
                "category": "resource_leak",
                "severity": "MEDIUM",
                "title": "Potentially unclosed file descriptor",
                "description": "File handle opened; confirmation requires checking if caller closes it.",
                "source_reference": {
                    "file_path": "backend/scanner/parser.py",
                    "start_line": 40,
                    "end_line": 42,
                },
                "evidence": "f = open(path, 'r')",
                "suggested_fix": "Use with open(...) as f:",
                "confidence": "medium",
                "is_uncertain": True,
                "source_type": "AI",
            }
        ],
        "missing_context": ["caller_lifecycle"],
    }
    mock_llm_gateway.generate.return_value = LLMResponse(
        content=json.dumps(mock_payload),
        model="gemini-flash-lite-latest",
    )

    engine = BugDetectionEngine(llm_gateway=mock_llm_gateway)
    result = await engine.detect_bugs(uuid4(), sample_bug_request)

    findings = result["findings"]
    assert len(findings) == 1
    assert findings[0].is_uncertain is True
    assert findings[0].category == "resource_leak"


@pytest.mark.asyncio
async def test_bug_detection_engine_markdown_fence_stripping_and_repair(
    mock_llm_gateway: MagicMock,
    sample_bug_request: BugDetectionRequest,
) -> None:
    """Verifies that markdown fences are cleaned and repair loop recovers on invalid initial JSON."""
    valid_payload = {
        "findings": [
            {
                "id": "bug-004",
                "category": "logic_error",
                "severity": "LOW",
                "title": "Redundant comparison",
                "description": "Condition is always true.",
                "source_reference": {"file_path": "backend/scanner/parser.py", "start_line": 10},
                "evidence": "if x == x:",
                "confidence": "high",
                "is_uncertain": False,
                "source_type": "AI",
            }
        ],
        "missing_context": [],
    }

    mock_llm_gateway.generate.side_effect = [
        LLMResponse(content="```json\n{ bad json syntax ...\n```", model="gemini-flash-lite-latest"),
        LLMResponse(content=f"```json\n{json.dumps(valid_payload)}\n```", model="gemini-flash-lite-latest"),
    ]

    engine = BugDetectionEngine(llm_gateway=mock_llm_gateway)
    result = await engine.detect_bugs(uuid4(), sample_bug_request)

    assert len(result["findings"]) == 1
    assert result["findings"][0].category == "logic_error"
    assert mock_llm_gateway.generate.call_count == 2


@pytest.mark.asyncio
async def test_bug_detection_engine_repair_exhaustion_raises(
    mock_llm_gateway: MagicMock,
    sample_bug_request: BugDetectionRequest,
) -> None:
    """Acceptance: Malformed output after 2 attempts raises LLMValidationError (no silent empty output)."""
    mock_llm_gateway.generate.return_value = LLMResponse(
        content="not a valid json object anywhere",
        model="gemini-flash-lite-latest",
    )

    engine = BugDetectionEngine(llm_gateway=mock_llm_gateway)
    with pytest.raises(LLMValidationError) as exc_info:
        await engine.detect_bugs(uuid4(), sample_bug_request)

    assert "BugDetection" in str(exc_info.value)
    assert mock_llm_gateway.generate.call_count == 2


@pytest.mark.asyncio
async def test_bug_detection_engine_unconfigured_gateway_raises_503(
    sample_bug_request: BugDetectionRequest,
) -> None:
    """Missing gateway with include_ai=True fails closed with HTTP 503."""
    engine = BugDetectionEngine(llm_gateway=None)
    with pytest.raises(APIError) as exc_info:
        await engine.detect_bugs(uuid4(), sample_bug_request)

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_bug_detection_engine_disallowed_provider_raises_400(
    sample_bug_request: BugDetectionRequest,
) -> None:
    """Disallowed providers (e.g. openai) must be rejected with HTTP 400."""
    bad_gateway = MagicMock()
    bad_gateway.provider = SimpleNamespace(provider_name="openai")

    engine = BugDetectionEngine(llm_gateway=bad_gateway)
    with pytest.raises(APIError) as exc_info:
        await engine.detect_bugs(uuid4(), sample_bug_request)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == ErrorCode.INVALID_REQUEST


def test_bug_detection_engine_implements_protocol() -> None:
    """Verifies runtime Protocol conformance."""
    engine = BugDetectionEngine(llm_gateway=MagicMock())
    assert isinstance(engine, BugDetectionServiceProtocol)
    assert isinstance(engine, BugDetectionEngineProtocol)

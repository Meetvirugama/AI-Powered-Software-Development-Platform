"""Module 7 (Code Explanation Studio) audit fixes.

1. Explanation levels really differ: each level sends its own requirements and
   output-token budget (concise < detailed < deep).
2. Confidence calibration: soft missing-context notes from the model cap
   confidence at MEDIUM instead of forcing LOW; only a resolver-level gap in the
   target code itself forces LOW.
3. Run history records the active chat model, not always the Groq model name.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.llm.schemas import LLMResponse
from ai.services.explanation_service import (
    CodeExplanationService,
    _LEVEL_MAX_TOKENS,
    _resolve_level_key,
)
from app.schemas.analysis import (
    AnalysisSourceReference,
    AnalysisTarget,
    CodeExplanation,
    ExplainCodeRequest,
)
from app.services.explanation_orchestrator import (
    ResolvedExplanationTarget,
    ground_explanation_sources,
)
from tests.fixtures.w2_schema_examples import VALID_CODE_EXPLANATION_DICT


# ---------------------------------------------------------------------------
# 1. Levels
# ---------------------------------------------------------------------------

def test_level_key_resolution() -> None:
    assert _resolve_level_key("concise", False) == "concise"
    assert _resolve_level_key("concise", True) == "concise"  # explicit summary wins
    assert _resolve_level_key("detailed", False) == "detailed"
    assert _resolve_level_key("detailed", True) == "deep"
    assert _resolve_level_key("deep_technical", False) == "deep"
    assert _resolve_level_key(None, False) == "detailed"
    assert _LEVEL_MAX_TOKENS["concise"] < _LEVEL_MAX_TOKENS["detailed"] < _LEVEL_MAX_TOKENS["deep"]


async def _captured_request(level: str):
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(VALID_CODE_EXPLANATION_DICT),
            model="gemini-flash-lite-latest",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )
    )
    service = CodeExplanationService(llm_gateway=gateway)
    payload = ExplainCodeRequest(
        target=AnalysisTarget(type="file", path="backend/app/core/retry.py"),
        explanation_level=level,
    )
    await service.explain(uuid4(), payload, code_content="def f():\n    return 1\n")
    return gateway.generate.await_args.args[0]


@pytest.mark.asyncio
async def test_concise_level_uses_small_budget_and_skips_heavy_sections() -> None:
    req = await _captured_request("concise")
    user = req.messages[-1].content
    assert req.max_tokens == _LEVEL_MAX_TOKENS["concise"]
    assert "REQUIREMENTS (concise)" in user
    assert "Do NOT fill detailed_explanation" in user
    assert "Corrected Code:" not in user


@pytest.mark.asyncio
async def test_detailed_and_deep_levels_differ() -> None:
    detailed = await _captured_request("detailed")
    deep = await _captured_request("deep_technical")
    assert detailed.max_tokens == _LEVEL_MAX_TOKENS["detailed"]
    assert deep.max_tokens == _LEVEL_MAX_TOKENS["deep"]
    assert "REQUIREMENTS (detailed)" in detailed.messages[-1].content
    assert "REQUIREMENTS (deep)" in deep.messages[-1].content
    assert "Execution Flow" in deep.messages[-1].content
    assert "TARGET code only" in deep.messages[-1].content


# ---------------------------------------------------------------------------
# 2. Confidence calibration
# ---------------------------------------------------------------------------

def _resolved(code: str = "def f():\n    return 1\n", missing: list[str] | None = None) -> ResolvedExplanationTarget:
    return ResolvedExplanationTarget(
        target=AnalysisTarget(type="file", path="app/service.py"),
        revision="rev1",
        file_record=None,
        resolved_symbol=None,
        code_content=code,
        intelligence_context=MagicMock(),
        missing_context=list(missing or []),
        indexed_paths={"app/service.py": 20},
    )


def _explanation(missing: list[str]) -> CodeExplanation:
    return CodeExplanation(
        purpose="Returns one.",
        inputs_and_outputs="None -> int",
        sources=[AnalysisSourceReference(file_path="app/service.py", start_line=1, end_line=2)],
        confidence="high",
        missing_context=missing,
    )


def test_fully_grounded_explanation_stays_high() -> None:
    out = ground_explanation_sources(_explanation([]), repository_id=uuid4(), resolved=_resolved())
    assert out.confidence == "high"


def test_soft_missing_context_from_model_caps_at_medium_not_low() -> None:
    out = ground_explanation_sources(
        _explanation(["Caller implementations are unavailable in the provided context."]),
        repository_id=uuid4(),
        resolved=_resolved(),
    )
    assert out.confidence == "medium"


def test_missing_target_code_forces_low() -> None:
    out = ground_explanation_sources(
        _explanation([]),
        repository_id=uuid4(),
        resolved=_resolved(code="", missing=["No indexed code chunks found for 'app/service.py'."]),
    )
    assert out.confidence == "low"


# ---------------------------------------------------------------------------
# 3. Recorded model name
# ---------------------------------------------------------------------------

def test_record_analysis_run_stores_active_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    import app.core.config as config
    from app.services import explanation_orchestrator as orch

    settings = types.SimpleNamespace(
        active_chat_model="gemini-2.5-flash", groq_chat_model="openai/gpt-oss-120b"
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    app_state = types.SimpleNamespace()
    run_id = str(uuid4())
    orch.record_analysis_run(
        app_state,
        None,
        run_id=run_id,
        repository_id=uuid4(),
        user_id=uuid4(),
        feature_type="explanation",
        status="COMPLETED",
        target=AnalysisTarget(type="file", path="app/service.py"),
        revision="rev1",
        result_payload={"purpose": "x"},
    )
    record = app_state._analysis_run_history[run_id]
    assert record["result_payload"]["model"] == "gemini-2.5-flash"

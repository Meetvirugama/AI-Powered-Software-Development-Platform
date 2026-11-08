"""
Comprehensive Unit and Integration Test Suite for Issue #189:
Provider-Aware Token Budget Calibration and Safety Factors.

Tests:
1. Token estimation across providers and models (OpenAI, Gemini, Groq, fallbacks, multilingual).
2. Provider-aware safety factor application and effective budget calculations.
3. Observational calibration telemetry (ratio calculation, zero/missing handling, LLMGateway recording).
4. Feature context builders regression (Chat, Explain, Bug, Test, Review, Task).
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.context.bug_context import extract_bug_context
from ai.context.builder import ContextBuilder
from ai.context.chat_context import build_chat_context
from ai.context.explanation import enrich_explanation_context
from ai.context.models import (
    ChatMessage,
    ContextLimits,
    ContextStatus,
    MemoryEntry,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
)
from ai.context.renderers import render_intelligence_data, render_repository_data
from ai.context.review_context import ModifiedFile, build_multi_file_review_context
from ai.context.task_context import TaskContextBuilder
from ai.context.test_context import build_test_generation_context
from ai.context.token_budget import (
    DEFAULT_SAFETY_FACTOR,
    PROVIDER_ENCODINGS,
    PROVIDER_SAFETY_FACTORS,
    TokenCalibrationSample,
    TokenCalibrationTracker,
    calculate_calibration_ratio,
    calculate_effective_budget,
    count_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    get_calibration_tracker,
    get_encoding_for_model,
    get_safety_factor,
)
from ai.llm.client import LLMGateway
from ai.llm.provider import LLMProvider
from ai.llm.schemas import LLMRequest, LLMResponse, LLMToolRequest, LLMToolResponse, Message
from ai.retrieval.base import CodeChunk
from app.models.task import Task


# ---------------------------------------------------------------------------
# 1. Token Estimation Tests
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    """Verifies token counting and encoding selection across providers."""

    def test_existing_openai_encoding_behavior(self):
        """Standard OpenAI models use cl100k_base or o200k_base."""
        assert get_encoding_for_model("gpt-4", provider="openai") == "cl100k_base"
        assert get_encoding_for_model("gpt-3.5-turbo", provider="openai") == "cl100k_base"
        assert get_encoding_for_model("gpt-4o", provider="openai") == "o200k_base"
        assert get_encoding_for_model("gpt-4o-mini", provider="openai") == "o200k_base"
        assert get_encoding_for_model("o1", provider="openai") == "o200k_base"

    def test_gemini_approximate_estimation(self):
        """Gemini models use cl100k_base as base approximation with 1.15 safety factor."""
        assert get_encoding_for_model("gemini-flash-latest", provider="gemini") == "cl100k_base"
        assert get_encoding_for_model("gemini-1.5-flash", provider="gemini") == "cl100k_base"
        assert get_encoding_for_model("gemini-1.5-pro", provider="gemini") == "cl100k_base"

        sample_code = "def authenticate_user(username: str, token: str) -> bool:\n    return True\n"
        raw_count = count_tokens(sample_code)
        gemini_estimated = estimate_tokens(sample_code, provider="gemini")
        # Gemini estimate should be scaled by 1.15
        expected_gemini = int(raw_count * 1.15) if (raw_count * 1.15).is_integer() else int(raw_count * 1.15) + 1
        assert gemini_estimated == expected_gemini
        assert gemini_estimated >= raw_count

    def test_groq_gpt_oss_encoding_selection(self):
        """Groq models (gpt-oss, Llama 3.3) select cl100k_base."""
        assert get_encoding_for_model("openai/gpt-oss-120b", provider="groq") == "cl100k_base"
        assert get_encoding_for_model("llama-3.3-70b-versatile", provider="groq") == "cl100k_base"

    def test_unknown_model_fallback(self):
        """Unrecognized model and provider safely fall back to cl100k_base."""
        assert get_encoding_for_model("unknown-custom-model", provider="custom-provider") == "cl100k_base"
        assert get_encoding_for_model(None, provider=None) == "cl100k_base"

    def test_empty_prompt_returns_zero(self):
        """Empty string returns 0 for count and estimate."""
        assert count_tokens("") == 0
        assert estimate_tokens("", provider="gemini") == 0
        assert estimate_tokens("", provider="openai") == 0

    def test_large_prompt(self):
        """Large prompts with thousands of tokens scale predictably."""
        large_code = "x = 1\n" * 5000
        raw = count_tokens(large_code)
        assert raw > 5000
        gemini_est = estimate_tokens(large_code, provider="gemini")
        assert gemini_est > raw

    def test_unicode_and_multilingual_content(self):
        """Multilingual and Unicode content is handled deterministically without errors."""
        text = "Hello 世界 🚀 안녕하세요 привет café résumé"
        raw = count_tokens(text)
        assert raw > 0
        est = estimate_tokens(text, provider="gemini")
        assert est >= raw

    def test_special_tokens_safety(self):
        """Untrusted prompt content containing special tokens like <|endoftext|> does not raise."""
        text = "Snippet containing <|endoftext|> and <|fim_prefix|> markers"
        raw = count_tokens(text)
        assert raw > 0
        est = estimate_tokens(text, provider="gemini")
        assert est >= raw


# ---------------------------------------------------------------------------
# 2. Safety Factor Tests
# ---------------------------------------------------------------------------


class TestSafetyFactor:
    """Verifies safety factor configuration, provider mappings, and effective budget calculation."""

    def test_default_safety_factor(self):
        """Default safety factor is 1.15."""
        assert DEFAULT_SAFETY_FACTOR == 1.15
        assert get_safety_factor() == 1.15
        assert get_safety_factor(provider="gemini") == 1.15
        assert get_safety_factor(provider="unknown") == 1.15

    def test_provider_specific_overrides(self):
        """OpenAI uses 1.0 (exact), Groq uses 1.05, Gemini uses 1.15."""
        assert get_safety_factor(provider="openai") == 1.0
        assert get_safety_factor(provider="groq") == 1.05
        assert get_safety_factor(provider="gemini") == 1.15

    def test_custom_configured_factor(self):
        """Explicit custom factor takes precedence over provider defaults."""
        assert get_safety_factor(provider="gemini", custom_factor=1.25) == 1.25
        assert get_safety_factor(provider="openai", custom_factor=1.10) == 1.10

    def test_invalid_safety_factor_rejected(self):
        """Zero or negative safety factor raises ValueError."""
        with pytest.raises(ValueError, match="Safety factor must be positive"):
            get_safety_factor(custom_factor=0.0)
        with pytest.raises(ValueError, match="Safety factor must be positive"):
            get_safety_factor(custom_factor=-1.15)

    def test_env_var_safety_factor_override(self, monkeypatch):
        """AI_TOKEN_SAFETY_FACTOR environment variable overrides defaults."""
        monkeypatch.setenv("AI_TOKEN_SAFETY_FACTOR", "1.30")
        assert get_safety_factor(provider="gemini") == 1.30
        assert get_safety_factor(provider="unknown") == 1.30

    def test_calculate_effective_budget(self):
        """calculate_effective_budget scales down configured budget by safety factor."""
        # 10,000 / 1.15 = 8695
        assert calculate_effective_budget(10_000, safety_factor=1.15) == 8695
        # 10,000 / 1.0 = 10000
        assert calculate_effective_budget(10_000, safety_factor=1.0) == 10_000
        # 0 or negative budget returns 0
        assert calculate_effective_budget(0) == 0
        assert calculate_effective_budget(-100) == 0

    def test_factor_applied_exactly_once(self):
        """Ensures safety margin is not compounded twice."""
        text = "def hello(): pass"
        raw = count_tokens(text)
        # 1. Scaled token estimation:
        est = estimate_tokens(text, safety_factor=1.15)
        # 2. Raw count with factor=1.0:
        base = count_tokens(text, safety_factor=1.0)
        assert base == raw
        # Verifies estimate is single-scaled
        assert est == count_tokens(text, safety_factor=1.15)

    def test_context_limits_effective_max_tokens(self):
        """ContextLimits exposes effective_max_tokens scaled by its safety factor."""
        limits_default = ContextLimits(max_tokens=10_000, safety_factor=1.15)
        assert limits_default.effective_max_tokens == 8695

        limits_openai = ContextLimits(max_tokens=10_000, provider="openai")
        assert limits_openai.effective_max_tokens == 10_000

        limits_gemini = ContextLimits(max_tokens=10_000, provider="gemini")
        assert limits_gemini.effective_max_tokens == 8695


# ---------------------------------------------------------------------------
# 3. Observational Calibration Telemetry Tests
# ---------------------------------------------------------------------------


class TestCalibrationTelemetry:
    """Verifies ratio calculation and LLMGateway observational calibration telemetry."""

    def test_calculate_calibration_ratio_direction(self):
        """
        Direction: estimated_tokens / actual_input_tokens
        115 / 100 = 1.15 (conservative estimate)
        90 / 100 = 0.9 (under-estimate)
        """
        assert calculate_calibration_ratio(115, 100) == 1.15
        assert calculate_calibration_ratio(90, 100) == 0.90
        assert calculate_calibration_ratio(100, 100) == 1.0

    def test_calculate_calibration_ratio_safeguards(self):
        """Missing, zero, negative, or invalid usage values return None."""
        assert calculate_calibration_ratio(None, 100) is None
        assert calculate_calibration_ratio(100, None) is None
        assert calculate_calibration_ratio(100, 0) is None  # Division by zero avoided
        assert calculate_calibration_ratio(100, -5) is None
        assert calculate_calibration_ratio(-10, 100) is None

    def test_tracker_records_samples_and_filters(self):
        """TokenCalibrationTracker records samples and provides summaries."""
        tracker = TokenCalibrationTracker(max_samples=100)
        tracker.clear()

        s1 = tracker.record_sample(
            provider="gemini",
            model="gemini-1.5-flash",
            estimated_tokens=115,
            actual_input_tokens=100,
            feature="chat",
        )
        assert s1 is not None
        assert s1.ratio == 1.15
        assert s1.provider == "gemini"

        s2 = tracker.record_sample(
            provider="groq",
            model="llama-3.3-70b-versatile",
            estimated_tokens=105,
            actual_input_tokens=100,
            feature="explanation",
        )
        assert s2.ratio == 1.05

        samples = tracker.get_samples()
        assert len(samples) == 2

        gemini_samples = tracker.get_samples(provider="gemini")
        assert len(gemini_samples) == 1
        assert gemini_samples[0].provider == "gemini"

        summary = tracker.get_summary()
        assert summary["total_samples"] == 2
        assert summary["average_ratio"] == round((1.15 + 1.05) / 2, 4)

    def test_tracker_missing_actual_usage(self):
        """Missing actual input tokens creates sample with ratio=None."""
        tracker = TokenCalibrationTracker()
        tracker.clear()

        sample = tracker.record_sample(
            provider="gemini",
            model="gemini-flash",
            estimated_tokens=100,
            actual_input_tokens=None,
        )
        assert sample.ratio is None
        assert sample.actual_input_tokens is None

    @pytest.mark.asyncio
    async def test_llm_gateway_records_calibration_telemetry(self, caplog):
        """LLMGateway automatically calculates and logs calibration ratio on generate."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.default_model = "gemini-1.5-flash"
        mock_provider.generate = AsyncMock(
            return_value=LLMResponse(
                content="Generated response",
                model="gemini-1.5-flash",
                input_tokens=100,
                output_tokens=20,
            )
        )

        tracker = get_calibration_tracker()
        tracker.clear()

        with caplog.at_level(logging.INFO):
            gateway = LLMGateway(provider=mock_provider)
            request = LLMRequest.create(
                model="gemini-1.5-flash",
                messages=[Message(role="user", content="def test(): pass")],
                estimated_tokens=115,
                feature="bug_detection",
            )
            response = await gateway.generate(request)
            assert response.content == "Generated response"

            # Verify calibration tracker captured the sample
            samples = tracker.get_samples(provider="gemini")
            assert len(samples) >= 1
            latest = samples[-1]
            assert latest.estimated_tokens == 115
            assert latest.actual_input_tokens == 100
            assert latest.ratio == 1.15
            assert latest.feature == "bug_detection"

            # Verify structured telemetry record in caplog
            llm_call_records = [r for r in caplog.records if r.getMessage() == "llm_call"]
            assert len(llm_call_records) > 0
            rec = llm_call_records[-1]
            assert getattr(rec, "estimated_input_tokens", None) == 115
            assert getattr(rec, "actual_input_tokens", None) == 100
            assert getattr(rec, "estimated_to_actual_ratio", None) == 1.15
            assert hasattr(rec, "timestamp")

    @pytest.mark.asyncio
    async def test_telemetry_failure_does_not_break_llm_execution(self, monkeypatch):
        """An unexpected error in calibration logging never prevents response return."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.default_model = "gemini-1.5-flash"
        mock_provider.generate = AsyncMock(
            return_value=LLMResponse(
                content="Success regardless of telemetry",
                model="gemini-1.5-flash",
                input_tokens=100,
            )
        )

        tracker = get_calibration_tracker()
        monkeypatch.setattr(tracker, "record_sample", MagicMock(side_effect=RuntimeError("Telemetry failed!")))

        gateway = LLMGateway(provider=mock_provider)
        request = LLMRequest.create(
            model="gemini-1.5-flash",
            messages=[Message(role="user", content="hello")],
        )
        response = await gateway.generate(request)
        assert response.content == "Success regardless of telemetry"


# ---------------------------------------------------------------------------
# 4. Feature Context Builders Regression Tests
# ---------------------------------------------------------------------------


class TestFeatureContextBuildersRegression:
    """Verifies that all 5 feature context builders remain 100% backwards compatible."""

    def test_chat_context_builder(self):
        """build_chat_context preserves token budgeting and memory deduplication."""
        chunk = CodeChunk(
            id=uuid.uuid4(),
            repository_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            symbol_id=None,
            content="def run(): pass",
            token_count=10,
            start_line=1,
            end_line=2,
            content_hash="c1",
            score=0.9,
            file_path="src/app.py",
        )
        mem = MemoryEntry(
            id="m1",
            content="Architecture note",
            type="architecture",
            created_at="2026-11-08T00:00:00Z",
        )
        history = [ChatMessage(role="user", content="What does run() do?")]
        ctx = build_chat_context(
            max_tokens=1000,
            overhead_tokens=100,
            chunks=[chunk],
            memory=[mem],
            history=history,
        )
        assert ctx.total_tokens > 0
        assert ctx.total_tokens <= 1000
        assert len(ctx.code_chunks) == 1
        assert len(ctx.memory_chunks) == 1
        assert len(ctx.recent_history) == 1

    def test_explanation_context_builder(self):
        """enrich_explanation_context bounds and fits target and caller symbols."""
        target = TargetSnippet(
            file_path="src/service.py",
            content="def process(): return 42",
            start_line=1,
            end_line=2,
            symbol_name="process",
        )
        callers = [
            SymbolContext(
                name="caller_func",
                kind="function",
                file_path="src/main.py",
                start_line=10,
                end_line=12,
                content="def caller_func(): process()",
            )
        ]
        ctx = enrich_explanation_context(target=target, callers=callers, token_budget=5000)
        assert ctx.status == ContextStatus.COMPLETE
        assert ctx.total_tokens > 0
        assert ctx.token_budget == 5000

    def test_bug_context_builder(self):
        """extract_bug_context builds enriched bug analysis context within token limits."""
        target = TargetSnippet(
            file_path="src/calc.py",
            content="def divide(a, b): return a / b",
            start_line=1,
            end_line=2,
        )
        ctx = extract_bug_context(target=target, token_budget=8000)
        assert ctx.status == ContextStatus.COMPLETE
        assert ctx.total_tokens > 0

    def test_test_generation_context_builder(self):
        """build_test_generation_context builds framework-aware test context."""
        target = TargetSnippet(
            file_path="src/auth.py",
            content="def hash_password(pwd): pass",
            start_line=1,
            end_line=2,
        )
        existing_test = RepositoryFile(
            id="t1",
            path="tests/test_auth.py",
            language="python",
            size_bytes=100,
            line_count=10,
        )
        ctx = build_test_generation_context(
            target=target,
            existing_test_files=[existing_test],
            token_budget=8000,
        )
        assert ctx.status == ContextStatus.COMPLETE
        assert ctx.total_tokens > 0

    def test_code_review_context_builder(self):
        """build_multi_file_review_context fits diff hunks within limits."""
        mod_file = ModifiedFile(
            file_path="src/main.py",
            diff_hunks=["+ print('hello world')"],
        )
        ctx = build_multi_file_review_context(
            modified_files=[mod_file],
            token_budget=10_000,
        )
        assert ctx.status == ContextStatus.COMPLETE
        assert ctx.total_tokens > 0

    def test_task_context_builder(self):
        """TaskContextBuilder enforces prompt token ceiling."""
        task = Task(
            id=uuid.uuid4(),
            title="Add login endpoint",
            description="Implement OAuth handler",
        )
        builder = TaskContextBuilder(token_budget=12_000)
        manifest = builder.build_task_context(task=task)
        assert manifest is not None
        assert count_tokens(manifest.prompt_context_text) <= 12_000

    def test_context_rendering_untrusted_delimiters(self):
        """Intelligence and repository rendering preserves security tagging."""
        target = TargetSnippet(
            file_path="src/core.py",
            content="SECRET_KEY = 123",
            start_line=1,
            end_line=1,
        )
        ctx = ContextBuilder().build_intelligence_context(target=target, token_budget=1000)
        rendered = render_intelligence_data(ctx)
        assert "<<<REPO_DATA_START>>>" in rendered
        assert "<<<REPO_DATA_END>>>" in rendered
        assert "SECRET_KEY = 123" in rendered

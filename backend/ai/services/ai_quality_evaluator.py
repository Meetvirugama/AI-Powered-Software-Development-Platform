"""AI Quality Evaluator, False-Positive Metrics, Explanation Rubric Judge, and Provider Validation Engine.

Owner: Dev — Week 3 Day 6 Deliverable (Docs/daily_tasks.md line 664 & Docs/week3.md §4.1, §6) & Issue 2 (P-28 LLM-as-Judge Rubric)
Reference: Docs/week3.md §4.1 (AI Provider Policy), §4.3 (Quality & Reliability), §6

Responsibilities:
1. Provider Validator: Checks that the platform only uses approved AI providers (Google Gemini and Groq).
2. False-Positive Evaluator: Feeds clean, bug-free code to the AI and verifies 0.0% false-positive rate.
3. Defect Fixture Evaluator: Measures Precision, Recall, and F1 score on known defect fixtures.
4. Schema Conformance Checker: Verifies strict Pydantic schema conformance.
5. Explanation Quality Evaluator (Issue 2 — P-28): Scores `CodeExplanation` outputs across a 5-dimension
   rubric (`factual_accuracy`, `completeness`, `call_graph_context_clarity`, `citation_grounding`,
   `redaction_transparency`) using LLM-as-judge (`P-28`) with a deterministic rubric fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from ai.schemas.validator import OutputValidator
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact
from app.schemas.ai_quality import (
    AIQualityReport,
    ExplanationQualityRubric,
    ProviderValidationCheck,
    QualityBenchmarkSample,
)

logger = logging.getLogger(__name__)

# List of LLM providers explicitly permitted by company policy (Docs/week3.md §4.1 / ADR-008)
_PERMITTED_PROVIDERS: set[str] = {"gemini", "groq"}

_EXPLANATION_JUDGE_SYSTEM_PROMPT = """You are an impartial Principal Software Engineer acting as an LLM-as-Judge (P-28) evaluating the quality of an AI-generated CodeExplanation against the ground-truth source code and call-graph context.

Score each of the 5 dimensions on a float scale from 1.0 (poor) to 5.0 (excellent):
1. factual_accuracy: Does the explanation accurately describe the code's behavior without hallucinating non-existent functions or logic?
2. completeness: Does it cover purpose, chronological logic_flow, key_symbols, and inputs_and_outputs?
3. call_graph_context_clarity: Does it clearly explain 1-hop caller/callee interactions and dependencies when present?
4. citation_grounding: Are source references grounded in valid file paths and line numbers?
5. redaction_transparency: When `[REDACTED]` placeholders appear in the source, does the explanation acknowledge the redaction honestly instead of guessing secret values?

Return ONLY a valid JSON object matching the ExplanationQualityRubric schema:
{
  "factual_accuracy": 4.5,
  "completeness": 4.5,
  "call_graph_context_clarity": 4.0,
  "citation_grounding": 5.0,
  "redaction_transparency": 5.0,
  "rationale": "Concise explanation of the scores",
  "improvement_suggestions": ["Optional actionable improvement"]
}
"""


class AIQualityEvaluator:
    """Evaluates AI output quality, precision/recall, explanation quality rubrics, and provider policy compliance."""

    def __init__(self, permitted_providers: set[str] | None = None) -> None:
        self.permitted_providers = (
            {p.lower() for p in permitted_providers}
            if permitted_providers is not None
            else set(_PERMITTED_PROVIDERS)
        )

    # =======================================================================
    # 1. Provider Policy Validation (Gemini and Groq Only)
    # =======================================================================

    def validate_provider(self, gateway_or_provider: Any) -> ProviderValidationCheck:
        """Check if an LLM gateway or provider follows our approved provider policy."""
        if gateway_or_provider is None:
            return ProviderValidationCheck(
                provider_name="none",
                status="SERVICE_UNAVAILABLE",
                is_allowed=False,
                is_healthy=False,
                active_model="none",
                message="LLM gateway or provider is unconfigured (None).",
            )

        provider = getattr(gateway_or_provider, "provider", gateway_or_provider)
        raw_name = (
            getattr(provider, "provider_name", None)
            or getattr(provider, "name", None)
            or getattr(gateway_or_provider, "provider_name", None)
        )

        if not raw_name or not isinstance(raw_name, str):
            return ProviderValidationCheck(
                provider_name="unknown",
                status="SERVICE_UNAVAILABLE",
                is_allowed=False,
                is_healthy=False,
                active_model="unknown",
                message="Could not resolve a valid provider name from gateway.",
            )

        provider_name = raw_name.strip().lower()
        active_model = (
            getattr(provider, "default_model", None)
            or getattr(gateway_or_provider, "default_model", None)
            or "unknown"
        )

        if provider_name not in self.permitted_providers:
            allowed_list = ", ".join(sorted(self.permitted_providers))
            return ProviderValidationCheck(
                provider_name=provider_name,
                status="INVALID_PROVIDER",
                is_allowed=False,
                is_healthy=False,
                active_model=str(active_model),
                message=(
                    f"Provider '{provider_name}' is not permitted by policy. "
                    f"Only {allowed_list} are allowed."
                ),
            )

        fallback = getattr(gateway_or_provider, "fallback_provider", None)
        fallback_active = getattr(gateway_or_provider, "fallback_active", False)

        if fallback_active:
            fallback_name = getattr(fallback, "provider_name", "fallback")
            return ProviderValidationCheck(
                provider_name=provider_name,
                status="FALLBACK_ACTIVE",
                is_allowed=True,
                is_healthy=True,
                active_model=str(active_model),
                message=f"Primary provider experienced an outage; fallback provider '{fallback_name}' is active.",
            )

        return ProviderValidationCheck(
            provider_name=provider_name,
            status="VALID",
            is_allowed=True,
            is_healthy=True,
            active_model=str(active_model),
            message=f"Provider '{provider_name}' is authorized and operating normally.",
        )

    def enforce_provider_policy(self, gateway_or_provider: Any) -> None:
        """Strict policy enforcement guard that raises APIError on unpermitted providers."""
        check = self.validate_provider(gateway_or_provider)
        if check.status == "SERVICE_UNAVAILABLE":
            raise APIError(
                status_code=503,
                code=ErrorCode.SERVICE_UNAVAILABLE,
                message=check.message,
                retryable=True,
            )
        if not check.is_allowed:
            raise APIError(
                status_code=400,
                code=ErrorCode.INVALID_REQUEST,
                message=check.message,
            )

    # =======================================================================
    # 2. Clean-Code False-Positive Evaluation (Zero False Positives Target)
    # =======================================================================

    def evaluate_clean_samples(
        self,
        clean_samples: list[dict[str, Any]],
    ) -> tuple[list[QualityBenchmarkSample], float]:
        """Evaluate clean, bug-free code samples to measure false alarms."""
        results: list[QualityBenchmarkSample] = []
        false_positive_count = 0

        for sample in clean_samples:
            sample_id = sample.get("sample_id", f"clean-{uuid4().hex[:6]}")
            detected = sample.get("detected_defects", [])

            is_fp = len(detected) > 0
            if is_fp:
                false_positive_count += 1

            results.append(
                QualityBenchmarkSample(
                    sample_id=sample_id,
                    sample_type="clean_baseline",
                    expected_defects=[],
                    detected_defects=detected,
                    is_false_positive=is_fp,
                    is_true_positive=False,
                    is_false_negative=False,
                )
            )

        total_clean = len(clean_samples)
        fp_rate = (false_positive_count / total_clean) if total_clean > 0 else 0.0
        return results, fp_rate

    # =======================================================================
    # 3. Defect Fixture Evaluation (Precision, Recall, F1 Score)
    # =======================================================================

    def evaluate_defect_fixtures(
        self,
        defect_fixtures: list[dict[str, Any]],
    ) -> tuple[list[QualityBenchmarkSample], float, float, float]:
        """Evaluate code with known bugs to measure Precision, Recall, and F1."""
        results: list[QualityBenchmarkSample] = []
        true_positives = 0
        false_negatives = 0
        false_positives = 0

        for fixture in defect_fixtures:
            sample_id = fixture.get("sample_id", f"defect-{uuid4().hex[:6]}")
            expected = set(fixture.get("expected_defects", []))
            detected = set(fixture.get("detected_defects", []))

            matched = expected.intersection(detected)
            missed = expected.difference(detected)
            hallucinated = detected.difference(expected)

            is_tp = len(matched) > 0
            is_fn = len(missed) > 0
            is_fp = len(hallucinated) > 0

            true_positives += len(matched)
            false_negatives += len(missed)
            false_positives += len(hallucinated)

            results.append(
                QualityBenchmarkSample(
                    sample_id=sample_id,
                    sample_type="defect_fixture",
                    expected_defects=sorted(expected),
                    detected_defects=sorted(detected),
                    is_false_positive=is_fp,
                    is_true_positive=is_tp,
                    is_false_negative=is_fn,
                )
            )

        total_defect_fixtures = len(defect_fixtures)
        if total_defect_fixtures == 0:
            precision = 0.0
            recall = 0.0
            f1 = 0.0
        else:
            denom_precision = true_positives + false_positives
            precision = (true_positives / denom_precision) if denom_precision > 0 else 0.0

            denom_recall = true_positives + false_negatives
            recall = (true_positives / denom_recall) if denom_recall > 0 else 0.0

            denom_f1 = precision + recall
            f1 = (2 * (precision * recall) / denom_f1) if denom_f1 > 0 else 0.0

        return results, precision, recall, f1

    # =======================================================================
    # 4. Schema Conformance & Self-Healing JSON Repair Evaluation
    # =======================================================================

    def evaluate_schema_conformance(
        self,
        raw_outputs: list[str],
        schema_cls: type[BaseModel],
    ) -> float:
        """Test how reliably AI text outputs convert into valid Pydantic models."""
        if not raw_outputs:
            return 1.0

        valid_count = 0
        for text in raw_outputs:
            try:
                cleaned = OutputValidator.clean_json_text(text)
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    schema_cls.model_validate(data)
                    valid_count += 1
            except (json.JSONDecodeError, ValidationError):
                continue
            except Exception:  # noqa: BLE001, S112
                continue

        return valid_count / len(raw_outputs)

    # =======================================================================
    # 5. Code Explanation Quality Evaluation Rubric (Issue 2 — P-28 LLM Judge)
    # =======================================================================

    @staticmethod
    def _compute_composite_rubric_score(
        factual_accuracy: float,
        completeness: float,
        call_graph_context_clarity: float,
        citation_grounding: float,
        redaction_transparency: float,
    ) -> float:
        """Compute weighted normalized score in [0.0, 1.0] from 1.0-5.0 rubric dimensions."""
        weighted_5 = (
            0.30 * factual_accuracy
            + 0.25 * completeness
            + 0.20 * call_graph_context_clarity
            + 0.15 * citation_grounding
            + 0.10 * redaction_transparency
        )
        normalized = (weighted_5 - 1.0) / 4.0
        return round(min(1.0, max(0.0, normalized)), 4)

    def _score_explanation_deterministically(
        self,
        explanation: Any,
        source_code: str,
        *,
        expected_symbols: list[str] | None = None,
        callers: list[str] | None = None,
        callees: list[str] | None = None,
    ) -> ExplanationQualityRubric:
        """Deterministic rubric evaluator for offline benchmarking or fallback."""
        purpose = str(getattr(explanation, "purpose", "") or "")
        logic_flow = list(getattr(explanation, "logic_flow", []) or [])
        key_symbols = list(getattr(explanation, "key_symbols", []) or [])
        inputs_outputs = str(getattr(explanation, "inputs_and_outputs", "") or "")
        deps = list(getattr(explanation, "dependencies", []) or [])
        sources = list(getattr(explanation, "sources", []) or [])
        exec_flow = list(getattr(explanation, "execution_flow", []) or [])
        has_redacted = bool(getattr(explanation, "has_redacted_content", False))
        redaction_notice = getattr(explanation, "redaction_notice", None)

        combined_text = " ".join(
            [
                purpose,
                " ".join(str(x) for x in logic_flow),
                inputs_outputs,
                " ".join(str(x) for x in deps),
                " ".join(str(x) for x in exec_flow),
                str(getattr(explanation, "detailed_explanation", "") or ""),
            ]
        ).lower()

        suggestions: list[str] = []

        # 1. Completeness (1.0 - 5.0)
        comp_score = 1.5
        if len(purpose.strip()) >= 20:
            comp_score += 1.0
        else:
            suggestions.append("Expand `purpose` to clearly state the component's responsibility.")
        if len(logic_flow) >= 2:
            comp_score += 1.0
        else:
            suggestions.append("Provide at least 2 chronological execution steps in `logic_flow`.")
        if key_symbols:
            comp_score += 0.75
        else:
            suggestions.append("Populate `key_symbols` with the primary functions/classes in scope.")
        if len(inputs_outputs.strip()) >= 15:
            comp_score += 0.75
        comp_score = min(5.0, comp_score)

        # 2. Factual accuracy (1.0 - 5.0): check alignment with identifiers in source_code / expected_symbols
        identifiers = set(expected_symbols or re.findall(r"\b(?:def|class|function|const)\s+([A-Za-z_][A-Za-z0-9_]*)", source_code))
        explained_sym_names = {str(getattr(s, "name", s)).lower() for s in key_symbols}
        if identifiers:
            matched_ids = sum(
                1
                for ident in identifiers
                if ident.lower() in combined_text or ident.lower() in explained_sym_names
            )
            coverage_ratio = matched_ids / max(1, len(identifiers))
            factual_score = round(2.5 + 2.5 * min(1.0, coverage_ratio), 2)
            if coverage_ratio < 0.5:
                suggestions.append("Reference the specific function/class identifiers defined in the target snippet.")
        else:
            factual_score = 4.0 if len(purpose.strip()) >= 15 else 2.5

        # 3. Call-graph context clarity (1.0 - 5.0)
        neighbor_names = [*(callers or []), *(callees or [])]
        if neighbor_names:
            matched_neighbors = sum(1 for n in neighbor_names if n.lower() in combined_text)
            cg_ratio = matched_neighbors / len(neighbor_names)
            cg_score = round(2.0 + 3.0 * min(1.0, cg_ratio), 2)
            if cg_ratio < 0.5:
                suggestions.append("Include 1-hop caller and callee interactions in `execution_flow` or `dependencies`.")
        elif deps or exec_flow:
            cg_score = 4.5
        else:
            cg_score = 3.5

        # 4. Citation grounding (1.0 - 5.0)
        if sources:
            valid_line_sources = sum(
                1
                for s in sources
                if getattr(s, "file_path", None) and getattr(s, "start_line", None) is not None
            )
            cite_score = 5.0 if valid_line_sources == len(sources) else 3.8
        else:
            cite_score = 2.0
            suggestions.append("Attach grounded `AnalysisSourceReference` items with 1-indexed line ranges.")

        # 5. Redaction transparency (1.0 - 5.0)
        source_has_redaction = "[REDACTED" in (source_code or "")
        if source_has_redaction:
            if has_redacted and redaction_notice:
                redaction_score = 5.0
            elif "redact" in combined_text or has_redacted:
                redaction_score = 4.0
            else:
                redaction_score = 2.0
                suggestions.append("Surface `has_redacted_content` and `redaction_notice` when `[REDACTED]` appears in source chunks.")
        else:
            redaction_score = 5.0

        overall = self._compute_composite_rubric_score(
            factual_score,
            comp_score,
            cg_score,
            cite_score,
            redaction_score,
        )
        passed = overall >= 0.70 and factual_score >= 3.0

        return ExplanationQualityRubric(
            factual_accuracy=factual_score,
            completeness=comp_score,
            call_graph_context_clarity=cg_score,
            citation_grounding=cite_score,
            redaction_transparency=redaction_score,
            overall_score=overall,
            passed=passed,
            judge_mode="deterministic_rubric",
            rationale=(
                f"Deterministic rubric evaluation: overall={overall:.2f} "
                f"(accuracy={factual_score:.1f}, completeness={comp_score:.1f}, "
                f"call_graph={cg_score:.1f}, citations={cite_score:.1f}, redaction={redaction_score:.1f})."
            ),
            improvement_suggestions=suggestions,
        )

    async def evaluate_explanation_quality_async(
        self,
        explanation: Any,
        source_code: str,
        *,
        llm_gateway: Any = None,
        expected_symbols: list[str] | None = None,
        callers: list[str] | None = None,
        callees: list[str] | None = None,
    ) -> ExplanationQualityRubric:
        """Evaluate a `CodeExplanation` using LLM-as-judge (P-28) with deterministic fallback."""
        baseline = self._score_explanation_deterministically(
            explanation,
            source_code,
            expected_symbols=expected_symbols,
            callers=callers,
            callees=callees,
        )
        if llm_gateway is None:
            return baseline

        # Enforce ADR-008 provider policy (only Gemini and Groq allowed)
        self.enforce_provider_policy(llm_gateway)

        try:
            from ai.llm.schemas import LLMRequest, Message

            exp_json = (
                explanation.model_dump_json(indent=2)
                if hasattr(explanation, "model_dump_json")
                else json.dumps(explanation, default=str)
            )
            user_prompt = (
                f"SOURCE CODE:\n```\n{redact(source_code)[:6000]}\n```\n\n"
                f"1-HOP CALLERS: {callers or []}\n"
                f"1-HOP CALLEES: {callees or []}\n\n"
                f"CANDIDATE EXPLANATION JSON:\n{redact(exp_json)[:6000]}\n\n"
                "Score this explanation strictly using the 5-dimension rubric."
            )
            model_name = (
                getattr(getattr(llm_gateway, "provider", None), "default_model", None)
                or "gemini-2.5-flash"
            )
            req = LLMRequest(
                model=str(model_name),
                messages=[
                    Message(role="system", content=_EXPLANATION_JUDGE_SYSTEM_PROMPT),
                    Message(role="user", content=user_prompt),
                ],
                temperature=0.0,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            resp = await llm_gateway.generate(req)
            raw_content = getattr(resp, "content", "") or ""
            cleaned = OutputValidator.clean_json_text(raw_content)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                fa = min(5.0, max(1.0, float(parsed.get("factual_accuracy", baseline.factual_accuracy))))
                comp = min(5.0, max(1.0, float(parsed.get("completeness", baseline.completeness))))
                cg = min(5.0, max(1.0, float(parsed.get("call_graph_context_clarity", baseline.call_graph_context_clarity))))
                cite = min(5.0, max(1.0, float(parsed.get("citation_grounding", baseline.citation_grounding))))
                red_t = min(5.0, max(1.0, float(parsed.get("redaction_transparency", baseline.redaction_transparency))))
                overall = self._compute_composite_rubric_score(fa, comp, cg, cite, red_t)
                return ExplanationQualityRubric(
                    factual_accuracy=fa,
                    completeness=comp,
                    call_graph_context_clarity=cg,
                    citation_grounding=cite,
                    redaction_transparency=red_t,
                    overall_score=overall,
                    passed=overall >= 0.70 and fa >= 3.0,
                    judge_mode="llm_judge",
                    rationale=str(parsed.get("rationale") or baseline.rationale),
                    improvement_suggestions=list(
                        parsed.get("improvement_suggestions") or baseline.improvement_suggestions
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("explanation_llm_judge_fallback", extra={"error": redact(str(exc))})

        return baseline

    def evaluate_explanation_quality(
        self,
        explanation: Any,
        source_code: str,
        *,
        llm_gateway: Any = None,
        expected_symbols: list[str] | None = None,
        callers: list[str] | None = None,
        callees: list[str] | None = None,
    ) -> ExplanationQualityRubric:
        """Synchronous entrypoint for evaluating `CodeExplanation` quality (P-28 LLM judge + deterministic rubric)."""
        if llm_gateway is None:
            return self._score_explanation_deterministically(
                explanation,
                source_code,
                expected_symbols=expected_symbols,
                callers=callers,
                callees=callees,
            )

        # Validate provider policy upfront even in sync mode
        self.enforce_provider_policy(llm_gateway)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self.evaluate_explanation_quality_async(
                        explanation,
                        source_code,
                        llm_gateway=llm_gateway,
                        expected_symbols=expected_symbols,
                        callers=callers,
                        callees=callees,
                    ),
                ).result()
        return asyncio.run(
            self.evaluate_explanation_quality_async(
                explanation,
                source_code,
                llm_gateway=llm_gateway,
                expected_symbols=expected_symbols,
                callers=callers,
                callees=callees,
            )
        )

    # =======================================================================
    # 6. Full Quality Report Compilation
    # =======================================================================

    def generate_quality_report(
        self,
        clean_samples: list[dict[str, Any]],
        defect_fixtures: list[dict[str, Any]],
        provider_checks: list[ProviderValidationCheck],
        schema_conformance_rate: float = 1.0,
    ) -> AIQualityReport:
        """Generate a complete AI Quality Report combining all evaluations."""
        report_id = f"ai-qual-{uuid4().hex[:8]}"

        clean_results, fp_rate = self.evaluate_clean_samples(clean_samples)
        fp_count = sum(1 for s in clean_results if s.is_false_positive)

        _, precision, recall, f1 = self.evaluate_defect_fixtures(defect_fixtures)

        total_samples = len(clean_samples) + len(defect_fixtures)

        if total_samples <= 0 or len(clean_samples) == 0 or len(defect_fixtures) == 0:
            passed = False
        else:
            all_providers_allowed = all(p.is_allowed for p in provider_checks) if provider_checks else True
            passed = (
                fp_rate <= 0.05
                and precision >= 0.80
                and recall >= 0.80
                and schema_conformance_rate >= 0.95
                and all_providers_allowed
            )

        summary = (
            f"Evaluated {total_samples} samples across clean and defect code: "
            f"Precision={precision:.1%}, Recall={recall:.1%}, F1={f1:.1%}, "
            f"False Positive Rate={fp_rate:.1%}, Schema Conformance={schema_conformance_rate:.1%}."
        )

        return AIQualityReport(
            report_id=report_id,
            total_samples=total_samples,
            clean_samples_count=len(clean_samples),
            defect_samples_count=len(defect_fixtures),
            false_positive_count=fp_count,
            false_positive_rate=fp_rate,
            precision=precision,
            recall=recall,
            f1_score=f1,
            schema_conformance_rate=schema_conformance_rate,
            provider_checks=provider_checks,
            passed_quality_thresholds=passed,
            summary=summary,
        )


__all__ = ["AIQualityEvaluator", "ExplanationQualityRubric"]

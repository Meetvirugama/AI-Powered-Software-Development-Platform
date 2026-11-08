# 21. Provider-Aware Token Budget Calibration & Safety Factors

> **Issue:** #189  
> **PR:** `feat(ai): improve provider-aware token budget calibration`  
> **Status:** Active  
> **Related Specifications:** `Docs/engineering/13_architecture_decisions.md` (ADR-008, ADR-009), `ai/context/token_budget.py`, `ai/llm/client.py`  
> **Author:** Dharmraj06

---

## 1. Executive Summary

This architecture document details the token estimation, safety margin, and observational telemetry calibration infrastructure implemented for Issue #189. 

The platform uses offline token estimation to assemble bounded prompt contexts (`AgentContext` and `IntelligenceContext`) before sending inference requests to LLM providers. Prior to Issue #189, token counting was hardcoded to `tiktoken`'s `cl100k_base` BPE vocabulary. While accurate for OpenAI models and compatible with Groq BPE models (`openai/gpt-oss-120b`, `llama-3.3-70b-versatile`), it did not account for differences in Google Gemini's proprietary SentencePiece tokenizer (~256k vocabulary).

Rather than replacing `tiktoken` with slow, rate-limited remote tokenization APIs or heavy third-party dependencies, Issue #189 retains fast local `tiktoken` estimation, introduces a configurable **1.15 safety factor** for Gemini, provides an exact **effective budget formula**, and adds **observational calibration telemetry** in `LLMGateway` tracking estimated-versus-actual `input_tokens`.

---

## 2. Token Estimation Architecture & Provider Differences

```
┌────────────────────────────────────────────────────────┐
│ Context Construction (e.g. IntelligenceContextBuilder) │
│ - Target snippet                                       │
│ - Relevant symbols & AST callers                       │
│ - Retrieved RAG chunks                                 │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ ai.context.token_budget: estimate_tokens / count_tokens│
│ - Provider-aware encoding lookup (cl100k_base, o200k)   │
│ - Scaled by provider safety factor (e.g. 1.15 Gemini)  │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ LLMGateway.generate(request)                           │
│ 1. Capture estimated_input_tokens                      │
│ 2. Dispatch to LLM Provider (Gemini / Groq)            │
│ 3. Receive LLMResponse(input_tokens, output_tokens)    │
│ 4. Calculate estimated_to_actual_ratio                 │
│ 5. Record TokenCalibrationSample (observational log)   │
└────────────────────────────────────────────────────────┘
```

### 2.1 Why Gemini Estimation is Approximate
Google Gemini models (`gemini-1.5-flash`, `gemini-2.0-flash`, `gemini-1.5-pro`) use a proprietary SentencePiece tokenizer with a 256,000 token vocabulary. OpenAI's `cl100k_base` vocabulary has ~100,000 tokens. 

Empirical measurements show that on source code, structured JSON, indentation, and special identifier syntax:
* Certain programming keywords and whitespace tokens produce different chunk splits.
* Gemini may tokenize specific multi-byte characters or repetitive syntax into fewer or more tokens depending on vocabulary presence.
* In conservative estimation, Gemini token counts can vary by **10% to 20%** compared to `cl100k_base`.

### 2.2 Encoding Selection by Provider and Model

Encoding resolution is governed by `get_encoding_for_model(model, provider)`:

| Provider | Model(s) | Encoding | Mode |
|:---|:---|:---|:---|
| **OpenAI** | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3` | `o200k_base` | Exact |
| **OpenAI** | `gpt-4`, `gpt-3.5-turbo` | `cl100k_base` | Exact |
| **Groq** | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` | `cl100k_base` | BPE compatible |
| **Gemini** | `gemini-flash-latest`, `gemini-1.5-flash`, `gemini-1.5-pro` | `cl100k_base` | Approximate |
| *Unknown / Default* | Any unknown model / provider | `cl100k_base` | Safe Fallback |

---

## 3. Provider-Aware Safety Factor

### 3.1 Rationale for 1.15 Default
A default safety multiplier of **1.15** (+15% margin) provides an optimal operational balance:
1. **Safety Guarantee:** Prevents context truncation overflows, rate-limit threshold surprises, and API `400 InvalidArgument (context length exceeded)` errors.
2. **Context Efficiency:** 15% margin avoids aggressively starving useful context (unlike arbitrary 30-50% margins which unnecessarily discard related symbols and chunks).

### 3.2 Provider Safety Factors

Configured in `PROVIDER_SAFETY_FACTORS`:
* **Gemini:** `1.15`
* **Groq:** `1.05` (Groq hosts Llama/gpt-oss models using BPE tokenizers with minor variance)
* **OpenAI:** `1.0` (Exact `tiktoken` vocabulary match)
* **Fallback / Unknown:** `1.15`

### 3.3 Overrides and Configuration
The safety factor can be customized via:
1. Programmatic parameter: `get_safety_factor(custom_factor=1.20)`.
2. Environment variable: `AI_TOKEN_SAFETY_FACTOR=1.20`.
3. Provider configuration: `get_safety_factor(provider="gemini")`.

---

## 4. Effective Budget Calculation

To ensure the safety factor is applied **consistently and exactly once** without double-scaling, the system defines:

$$\text{effective\_budget} = \left\lfloor \frac{\text{configured\_budget}}{\text{safety\_factor}} \right\rfloor$$

Implemented in `calculate_effective_budget(budget, safety_factor=1.15, provider="gemini")`:

```python
# Example: 10,000 configured token budget for Gemini
effective_budget = calculate_effective_budget(10_000, safety_factor=1.15)
# Result: 8,695 tokens
```

When greedy fitters (`fit_items`, `fit_history`) fit raw `cl100k_base` tokens up to `8,695`, the actual Gemini token consumption will stay strictly within $\approx 8,695 \times 1.15 = 10,000$ tokens.

Additionally, `estimate_tokens(text, provider="gemini")` calculates:

$$\text{estimated\_tokens} = \lceil \text{raw\_tokens} \times \text{safety\_factor} \rceil$$

---

## 5. Estimated-to-Actual Calibration Telemetry

### 5.1 Direction and Definition

The ratio is defined as:

$$\text{estimated\_to\_actual\_ratio} = \frac{\text{estimated\_tokens}}{\text{actual\_input\_tokens}}$$

* **Ratio $> 1.0$:** Estimate was conservative (higher than provider's actual tokens).
* **Ratio $< 1.0$:** Estimate was under-counting (lower than provider's actual tokens).
* **Ratio $= 1.0$:** Exact match.

### 5.2 Safe Handling of Edge Cases
`calculate_calibration_ratio(estimated_tokens, actual_input_tokens)` safely returns `None` when:
* Either token count is `None` or not a number.
* `actual_input_tokens <= 0` (strict safeguard against division by zero).
* `estimated_tokens < 0`.

### 5.3 Telemetry Payload Fields
Emitted on every `LLMGateway` execution via existing `logger.info("llm_call", extra=...)` and dedicated `token_budget_calibration` events:

| Field | Type | Description | Example |
|:---|:---|:---|:---|
| `provider` | `str` | Active provider name | `"gemini"` |
| `model` | `str` | Model identifier | `"gemini-1.5-flash"` |
| `estimated_input_tokens` | `int` | Pre-request estimated prompt tokens | `115` |
| `actual_input_tokens` | `int` | Actual prompt tokens reported in `LLMResponse` | `100` |
| `estimated_to_actual_ratio` | `float` | Estimated / Actual ratio (rounded to 4 decimal places) | `1.15` |
| `timestamp` | `str` | ISO 8601 UTC timestamp | `"2026-11-08T14:30:00.000Z"` |
| `feature` | `str \| None` | Optional feature category | `"chat"`, `"bug_detection"` |

### 5.4 Security & Privacy Controls
* Telemetry records ONLY numeric token counts, model names, provider strings, and timestamps.
* Prompt text, repository source code, credentials, and API keys are **never** logged or attached to telemetry records.
* Any logging or tracker exception is caught and warned without failing active inference.

---

## 6. Observational Calibration Tracker

`TokenCalibrationTracker` maintains an in-memory, thread-safe, bounded ring buffer (default 1,000 samples) of calibration samples.

It provides aggregate reporting:
```python
tracker = get_calibration_tracker()
summary = tracker.get_summary(provider="gemini")
# Returns: {
#   "total_samples": 42,
#   "valid_ratio_samples": 42,
#   "average_ratio": 1.134,
#   "min_ratio": 1.08,
#   "max_ratio": 1.18
# }
```

Calibration data is strictly observational: it does not dynamically alter safety factors on small sample sizes, preventing runtime instability. Instead, platform engineers can review aggregated calibration metrics to tune static provider safety factors over time.

---

## 7. Known Limitations

1. **SentencePiece Boundary Variances:** Code snippets containing dense non-ASCII variable names or rare punctuation may exhibit higher variance in token counts until native tokenizers are embedded.
2. **System Prompt Provider Overhead:** Gemini and Groq apply slight internal formatting tokens to delimiter turns (`system_instruction`, `parts`) which can cause minor 2-4 token shifts on very small inputs.


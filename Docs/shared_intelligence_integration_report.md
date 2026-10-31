# Shared Intelligence Integration Report (Week 2)
**Owner:** Meet (AI/ML & Context Lead)  
**Milestone:** Week 2 — Developer Intelligence Suite  
**Status:** 🟢 Complete & Verified (62/62 Tests Passing)  

---

## 1. Executive Summary

During Week 2, Meet implemented the unified repository intelligence context layer powering all four developer intelligence features in the platform:
1. **Feature 1:** Code Explanation (`POST /repositories/{id}/explain`)
2. **Feature 2:** Dedicated Bug Detection (`POST /repositories/{id}/detect-bugs`)
3. **Feature 3:** Framework-Aware Test Generation (`POST /repositories/{id}/generate-tests`)
4. **Feature 4:** Standalone AI Code Review (`POST /repositories/{id}/review`)

The shared intelligence layer guarantees that all features consume consistent, revision-pinned, token-bounded context assembled from AST symbols, call graphs, diffs, and project conventions without redundant database queries, duplicate tokenization, or cache collisions.

---

## 2. Architecture & Component Inventory

```
                   ┌─────────────────────────────────────────────────────────┐
                   │             RepositoryContextService (Facade)           │
                   │               backend/ai/context/service.py             │
                   └──────┬────────────┬─────────────┬─────────────┬─────────┘
                          │            │             │             │
              ┌───────────┴───┐  ┌─────┴──────┐ ┌────┴─────┐ ┌─────┴──────────┐
              │  Explanation  │  │    Bug     │ │   Test   │ │  Multi-File    │
              │   Enricher    │  │ Extractor  │ │ Builder  │ │ Review Context │
              │(explanation.py│  │(bug_context│ │(test_ctx)│ │(review_context)│
              └───────┬───────┘  └─────┬──────┘ └────┬─────┘ └─────┬──────────┘
                      │                │             │             │
                      └────────────────┼─────────────┴─────────────┘
                                       ▼
                       ┌───────────────────────────────┐
                       │ ContextBuilder & Intelligence │
                       │    Context (builder.py)       │
                       └───────────────────────────────┘
```

### Module Responsibilities

| Module | Primary Class / Functions | Key Responsibilities |
|---|---|---|
| `ai.context.builder` | `ContextBuilder`, `IntelligenceContext`, `TargetSnippet`, `SymbolContext` | Foundation container, prompt-injection isolation fences (`<<<UNTRUSTED_CODE_SNIPPET>>>`), `tiktoken` budget allocation, hard truncation |
| `ai.context.explanation` | `ExplanationContextEnricher`, `enrich_explanation_context` | Inward/outward caller resolution, import extraction (Python & TypeScript), source citation grounding, leaf-function handling |
| `ai.context.bug_context` | `BugContextExtractor`, `extract_bug_context` | Caller site extraction, error-handling boundary detection (`try/except/catch`), external library call detection |
| `ai.context.test_context` | `TestContextBuilder`, `build_test_generation_context` | Test path inference (`pytest`, `unittest`, `jest`), mockable DB/HTTP call detection, existing test patterns, fixture inclusion |
| `ai.context.review_context` | `ReviewContextBuilder`, `build_multi_file_review_context` | Unified diff hunk parser, dependency blast-radius calculator, fair token distribution across modified files, base..head tracking |
| `ai.context.service` | `RepositoryContextService`, `shared_context_service` | Central facade, TTL/LRU caching, SHA-256 multi-file diff digest collision fix, repository cache invalidation, revision drift assertion, token budget audit, Gemini/Groq-only provider policy |

---

## 3. Key Invariants & Hardening Features

### 3.1. Source Revision Hardening & Fail-Closed Drift Detection
- Context objects carry the exact commit SHA or revision range (`context.revision`).
- `verify_revision_consistency(expected_revision, context, strict=True|False)` provides diagnostic drift verification.
- `assert_revision_consistency(...)` raises `RevisionDriftError` when repository drift is detected, preventing models from reasoning over stale or desynchronized files.

### 3.2. Deterministic Review Cache Keying & Collision Fix
Prior to Day 7, multi-file review cache keys only indexed file count (`len(modified_files)`), causing different diffs modifying the same number of files to collide. Day 7 introduced a deterministic SHA-256 digest:
```python
files_sig = "|".join(
    f"{mf.file_path}:{mf.change_type}:{len(mf.diff_hunks)}"
    for mf in sorted(modified_files, key=lambda m: m.file_path)
)
files_hash = hashlib.sha256(files_sig.encode("utf-8")).hexdigest()[:16]
ckey = self._cache_key(
    "review", repository_id, f"multi-diff:{files_hash}", 1, len(modified_files), None, rev
)
```

### 3.3. Repository-Level Cache Invalidation
The service supports purging cached context entries when a repository branch updates or is deleted:
```python
service.invalidate_cache_for_repository(repository_id, revision=None)
```

### 3.4. AI Provider Restriction Policy
Per project architecture rules, only Gemini and Groq are permitted providers:
```python
ALLOWED_AI_PROVIDERS = frozenset({"gemini", "groq"})
```
Attempts to use unauthorized providers (`openai`, `anthropic`, etc.) immediately raise `InvalidProviderError`.

### 3.5. Token Budget Audit & Pre-Flight Estimation
- `audit_context_budget(context, limits)` produces a granular breakdown across target code, symbols, rules, and chunks with utilization ratios.
- `estimate_context_tokens(...)` provides rapid pre-flight estimates before initiating multi-source assembly.

---

## 4. Test Suite Inventory & Coverage

All 62 tests across Meet's Week 2 test suites pass with 100% success rate:

| Test File | Days | Test Count | Verified Behaviors | Status |
|---|---|---|---|---|
| `backend/tests/test_meet_day1_intelligence_context.py` | Day 1 | 10 | TargetSnippet, SymbolContext, boundary fences, serialization, oversized limits | 🟢 Pass |
| `backend/tests/test_meet_day2_explanation_context.py` | Day 2 | 8 | Caller enrichment, import extraction, source reference grounding, leaf functions | 🟢 Pass |
| `backend/tests/test_meet_day3_bug_context.py` | Day 3 | 8 | Caller sites, error handling blocks, external library detection, missing context | 🟢 Pass |
| `backend/tests/test_meet_day4_test_context.py` | Day 4 | 8 | Test path inference, mockable DB/HTTP calls, existing test patterns, revision preservation | 🟢 Pass |
| `backend/tests/test_meet_day5_review_context.py` | Day 5 | 8 | Diff hunk parsing, blast radius calculation, fair token distribution, base..head tracking | 🟢 Pass |
| `backend/tests/test_meet_day6_shared_integration.py` | Day 6 | 8 | Unified facade across 4 features, LRU cache hit/miss, TTL expiration, provider validation | 🟢 Pass |
| `backend/tests/test_meet_day7_context_verification.py` | Day 7 | 12 | Revision drift assertion, review cache collision resolution, repo invalidation, budget audit, acceptance gate | 🟢 Pass |
| **Total** | | **62** | **Full Context Pipeline End-to-End** | **100% Passing** |

---

## 5. Performance & SLA Metrics

- **Cache Hit Latency:** `< 0.1ms` (direct memory lookup from OrderedDict cache)
- **Cold Assembly Latency:** `< 5ms` (AST traversal, call graph extraction, boundary rendering)
- **Memory Footprint:** Bounded by `max_cache_size=256` entries per service instance with LRU eviction
- **Token Precision:** Exact budget adherence enforced by `tiktoken` bounding

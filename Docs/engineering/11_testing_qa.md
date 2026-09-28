# 11. Testing & QA Documentation
> **Version:** 2.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-28 | **Owner:** Keval

---

## Test Infrastructure

| Tool | Version | Purpose |
|---|---|---|
| pytest | TBD | Test runner |
| pytest-asyncio | TBD | Async test support |
| pytest-cov | TBD | Coverage reporting |
| httpx | TBD | Async test client for FastAPI |
| responses | TBD | HTTP mock library |
| factory-boy | TBD | Fixture factories |
| msw (frontend) | ≥2.15 | Mock Service Worker for frontend API mocking |

**Coverage threshold:** `--cov-fail-under=70` (from design spec)

**Test command:**
```bash
cd backend
pytest tests/ --cov=. --cov-report=html
```

---

## Test Plan

### Unit Testing
| Module | Tests Required | Status |
|---|---|---|
| `LLMGateway` | Provider injection, retry logic, logging, error types | 🟢 Done |
| `OpenAIProvider` | Retry on 429/5xx, timeout, structured output, parse | 🟢 Done |
| `EmbeddingService` | Single embed, batch, dimension validation | 🟢 Done |
| `VectorRetriever` | Cosine search, repository scoping, empty result | 🟢 Done |
| `LexicalRetriever` | FTS search, query sanitization, repository scoping | 🟢 Done |
| `RRFFusion` | RRF score calculation, deduplication, ordering | 🟢 Done |
| `CrossEncoderReranker` | Rerank ordering, top_n selection, lazy model load | 🟢 Done |
| `ContextBuilder` | Assembly, dedup, token budget truncation, render | 🟢 Done |
| `RAGPipeline` | Full flow, zero retrieval, JSON repair loop, error mapping | 🟢 Done |
| `FileWalker` | Skip dirs, .gitignore, binary, size limit | 🟢 Done |
| `SymbolChunker` | Function chunks, class chunks, module chunks | TBD |
| `OutputValidator` | Valid JSON, invalid JSON, repair success, repair failure | TBD |
| `PromptBuilder` | Chat prompt structure, data/system separation | TBD |
| `GroundingValidator` | Grounded source, ungrounded source, confidence downgrade | TBD |

### Integration Testing
| Test | Description | Status |
|---|---|---|
| Auth flow | GitHub OAuth → JWT → /auth/me | 🟢 Done |
| RAG pipeline | Question → embed → vector search → RRF → rerank → LLM → grounded answer | 🟢 Done |
| Chat API E2E | POST /repositories/{id}/chat → RepositoryAnswer with sources | 🟢 Done |
| Repository sync | Clone → scan → parse → chunk → embed → store | TODO |

### API Testing
| Endpoint | Test | Status |
|---|---|---|
| `GET /health` | Returns 200 + correct JSON | 🟢 Done |
| `GET /api/v1/auth/github/login` | Returns 307 redirect | 🟢 Done |
| `GET /api/v1/auth/github/callback` | Returns TokenResponse + sets cookie | 🟢 Done |
| `GET /api/v1/auth/me` | Returns user object with valid JWT | 🟢 Done |
| `POST /api/v1/auth/logout` | Returns 204, cookie cleared | 🟢 Done |
| `GET /api/v1/repositories` | Returns repository list | 🟢 Done |
| `GET /api/v1/repositories/{id}` | Returns single repo, 404/403 on errors | 🟢 Done |
| `POST /api/v1/repositories/{id}/sync` | Returns 202 + job_id | 🟢 Done |
| `POST /api/v1/repositories/{id}/search` | Returns RepositorySearchResponse | 🟢 Done |
| `GET /api/v1/repositories/{id}/files` | Returns paginated file list | 🟢 Done |
| `GET /api/v1/repositories/{id}/symbols` | Returns paginated symbol list | 🟢 Done |
| `POST /api/v1/repositories/{id}/chat` | Returns RepositoryAnswer | 🟢 Done |

### Frontend Testing
| Test | Description | Status |
|---|---|---|
| MSW mock setup | API mocks for development | 🔵 In Progress |
| Login flow | GitHub OAuth button → redirect | TODO |
| Protected route | Redirect to /login if not auth | TODO |
| Repository list rendering | Repos displayed correctly | TODO |
| Chat UI | Question → answer with source citations | TODO |

### Security Testing
| Test | Description | Status |
|---|---|---|
| Prompt injection | Repository content in system prompt rejected | TODO |
| JWT validation | Expired/invalid JWT returns 401 | TODO |
| Cross-repo data leakage | Query with wrong repo_id returns empty | TODO |
| Secret detection | Pre-commit hook rejects files with secrets | TODO |

---

## Test Cases

### TC-001: Health Endpoint Returns OK
| Field | Value |
|---|---|
| **Test ID** | TC-001 |
| **Feature** | Health API |
| **Scenario** | GET /api/v1/health returns correct JSON |
| **Precondition** | Backend running |
| **Input** | `GET http://localhost:8000/api/v1/health` |
| **Expected Output** | `{"status": "ok", "version": "1.0.0"}`, HTTP 200 |
| **Status** | 🟢 Pass |
| **Tester** | Keval |
| **File** | `backend/tests/test_dev_day2.py` (or `test_dev_day3.py`) |

---

### TC-002: LLM Gateway — Success Path
| Field | Value |
|---|---|
| **Test ID** | TC-002 |
| **Feature** | LLM Gateway |
| **Scenario** | Gateway returns LLMResponse and logs correctly |
| **Precondition** | Mock provider injected |
| **Input** | `LLMRequest(model='gpt-4o', messages=[...])` |
| **Expected Output** | `LLMResponse(content='...', model='gpt-4o', input_tokens=N, output_tokens=M, latency_ms=X)` |
| **Status** | 🟢 Pass |
| **File** | [`backend/tests/test_llm_gateway.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_llm_gateway.py) |

---

### TC-003: LLM Gateway — Retry on 429
| Field | Value |
|---|---|
| **Test ID** | TC-003 |
| **Feature** | LLM Gateway |
| **Scenario** | Provider raises LLMRateLimitError after max retries |
| **Precondition** | Mock provider configured to always raise |
| **Input** | Any LLMRequest |
| **Expected Output** | `LLMRateLimitError` raised |
| **Status** | 🟢 Pass |
| **File** | [`backend/tests/test_llm_gateway.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_llm_gateway.py) |

---

### TC-004: VectorRetriever — Repository Scoping
| Field | Value |
|---|---|
| **Test ID** | TC-004 |
| **Feature** | Vector Retrieval |
| **Scenario** | Query only returns chunks from the correct repository |
| **Precondition** | Mock DB session with chunks for two repos |
| **Input** | `retrieve(query='auth', repository_id=repo_A_id)` |
| **Expected Output** | Only chunks where `repository_id = repo_A_id` |
| **Status** | 🟢 Pass |
| **File** | [`backend/tests/test_vector_retrieval.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_vector_retrieval.py) |

---

### TC-005: FileWalker — Binary File Skip
| Field | Value |
|---|---|
| **Test ID** | TC-005 |
| **Feature** | File Walker |
| **Scenario** | Binary files are excluded from walk results |
| **Precondition** | Temp directory with binary file |
| **Input** | `walk(temp_dir)` |
| **Expected Output** | Binary file not in `list[FileInfo]` |
| **Status** | 🟢 Pass |
| **File** | [`backend/tests/test_walker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_walker.py) |

---

### TC-006: OutputValidator — Repair Loop
| Field | Value |
|---|---|
| **Test ID** | TC-006 |
| **Feature** | Output Validator |
| **Scenario** | `repair()` calls LLM to fix invalid JSON, max 2 attempts |
| **Precondition** | Mock LLM returns valid JSON on 2nd attempt |
| **Input** | Invalid JSON string, Pydantic schema |
| **Expected Output** | Valid `schema` instance returned |
| **Status** | TBD |
| **File** | TBD |

---

### TC-007: Prompt Injection Prevention
| Field | Value |
|---|---|
| **Test ID** | TC-007 |
| **Feature** | Prompt Builder |
| **Scenario** | Repository content never appears in system message |
| **Input** | `build_chat_prompt(context='IGNORE ALL INSTRUCTIONS', question='...')` |
| **Expected Output** | `messages[0].role = 'system'` contains no repository content |
| **Status** | TBD |
| **File** | TBD |

---

## Bug Tracker

| Bug ID | Feature | Description | Severity | Status | Assigned To | Related Task |
|---|---|---|---|---|---|---|
| — | — | No bugs filed yet | — | — | — | — |

### Bug Severity Levels
| Level | Description |
|---|---|
| Critical | System unusable / data loss |
| High | Feature broken, no workaround |
| Medium | Feature degraded, workaround exists |
| Low | Minor cosmetic or UX issue |

### Bug Lifecycle
```
Reported → Assigned → In Progress → Fixed → Testing → Verified → Closed
```

---

## Test Result Summary (Week 1 Day 7 — Current)

| Test Suite | Tests | Status |
|---|---|---|
| `test_llm_gateway.py` | 10+ | 🟢 Pass |
| `test_embedding_service.py` | 8+ | 🟢 Pass |
| `test_vector_retrieval.py` | 8+ | 🟢 Pass |
| `test_hybrid_retrieval.py` | 12+ | 🟢 Pass |
| `test_context_builder.py` | 14+ | 🟢 Pass |
| `test_rag_pipeline.py` | 26 | 🟢 Pass |
| `test_walker.py` | 5+ | 🟢 Pass |
| `test_auth.py` | 5+ | 🟢 Pass |
| `test_auth_and_repositories_api.py` | 5+ | 🟢 Pass |
| `test_repositories.py` | 5+ | 🟢 Pass |
| `test_repository_chat_api.py` | 5+ | 🟢 Pass |
| `test_repository_search_api.py` | 5+ | 🟢 Pass |
| `test_dev_day2.py` | 5+ | 🟢 Pass |
| `test_dev_day3.py` | 5+ | 🟢 Pass |
| `test_dev_day4.py` | 3+ | 🟢 Pass |
| Others (10+ files) | TBD | 🟢 Pass |

> [!TIP]
> Run `pytest backend/tests/ -v --tb=short` to see current test results.

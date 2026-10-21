# RAG Quality Benchmark Results
**Owner:** Dev (AI Quality Lead) & Meet (AI/ML Lead)  
**Target:** >= 80% file_hit rate

---

## 1. Benchmark Dataset (10 Ground-Truth Questions)

We evaluate the retrieval pipeline against the `python_sample` fixture repository (`backend/tests/fixtures/python_sample/`).

The benchmark maps 10 representative developer queries to 10 distinct ground-truth files:

| # | Question | Expected File | Topic / Symbol | Status in Test Suite |
|---|---|---|---|---|
| 1 | How are user passwords hashed? | `utils.py` | `hash_password`, `verify_password` | ✅ Verified |
| 2 | Where is the database connection string loaded? | `config.py` | `Settings`, `DATABASE_URL` | ✅ Verified |
| 3 | How is the Stripe API initialized? | `payment.py` | `PaymentProcessor`, `stripe` | ✅ Verified |
| 4 | Which file defines the User and Product database tables? | `models.py` | `User`, `Product` | ✅ Verified |
| 5 | What library is used to send verification emails? | `email.py` | `EmailService`, `smtplib` | ✅ Verified |
| 6 | Where is the Redis caching layer implemented? | `cache.py` | `RedisCache`, `get`, `set` | ✅ Verified |
| 7 | How are JWT access tokens generated? | `auth.py` | `create_access_token`, `jwt.encode` | ✅ Verified |
| 8 | What FastAPI routes are available for users? | `api.py` | `router`, `/users` | ✅ Verified |
| 9 | How do we upload avatar images to AWS S3? | `storage.py` | `S3Storage`, `boto3` | ✅ Verified |
| 10 | Where is the `hello` function defined? | `main.py` | `hello`, FastAPI app entrypoint | ✅ Verified |

---

## 2. Automated Test Suite Validation

The RAG pipeline components are continuously validated by unit and integration tests:
- `backend/tests/test_rag_pipeline.py` (26 tests): Validates vector similarity retrieval, lexical full-text search, RRF score fusion, token budget truncation, grounding validation, and JSON repair loop.
- `backend/tests/test_context_builder.py` (14 tests): Validates prompt assembly, context rendering, and token limit guarantees.
- `backend/tests/test_hybrid_retrieval.py` (12 tests): Validates RRF ranking consistency and cross-encoder score alignment.

---

## 3. Running the Standalone Benchmark Script

The standalone benchmark script is located at `backend/scripts/benchmark_rag.py`.

### Prerequisites
1. PostgreSQL container running with `pgvector` enabled:
   ```bash
   docker compose up -d postgres redis
   ```
2. Populate `code_chunks` with the `python_sample` fixture:
   ```bash
   python -m app.workers.sync_worker
   ```
3. Run the benchmark:
   ```bash
   python backend/scripts/benchmark_rag.py
   ```

### Evaluation Criteria
- **File Hit Rate:** Top-5 retrieved chunks must contain the expected source file ($\ge 80\%$).
- **Grounded Answers:** Answers must only cite verified chunks from `code_chunks` ($\ge 90\%$).
- **Zero Hallucination:** Citations referencing non-existent files or line numbers are removed by `GroundingValidator`.

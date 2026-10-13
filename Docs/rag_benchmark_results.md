# RAG Quality Benchmark Results
**Date:** 2026-09-28  
**Target:** >= 80% file_hit rate

## Benchmark Dataset (10 Questions)
We evaluate the retrieval pipeline against the `python_sample` repository (located at `backend/tests/fixtures/python_sample/`).

To make this a rigorous benchmark, we use 10 specific questions mapping to 10 distinct files.

| # | Question | Expected File | File Hit? | Symbol Hit? |
|---|---|---|---|---|
| 1 | How are user passwords hashed? | `utils.py` | - | - |
| 2 | Where is the database connection string loaded? | `config.py` | - | - |
| 3 | How is the Stripe API initialized? | `payment.py` | - | - |
| 4 | Which file defines the User and Product database tables? | `models.py` | - | - |
| 5 | What library is used to send verification emails? | `email.py` | - | - |
| 6 | Where is the Redis caching layer implemented? | `cache.py` | - | - |
| 7 | How are JWT access tokens generated? | `auth.py` | - | - |
| 8 | What FastAPI routes are available for users? | `api.py` | - | - |
| 9 | How do we upload avatar images to AWS S3? | `storage.py` | - | - |
| 10 | Where is the `hello` function defined? | `main.py` | - | - |

## Results Summary
- **Total Questions:** 10
- **File Hit Rate:** TBD (benchmark script must be run against live DB)
- **Symbol Hit Rate:** TBD
- **Final Status:** Pending end-to-end run

> [!NOTE]
> **STATUS: READY TO RUN**
> The fixture repository exists at `backend/tests/fixtures/python_sample/`. The full RAG pipeline (LexicalRetriever + VectorRetriever + RRFFusion + CrossEncoderReranker + ContextBuilder) is implemented as of 2026-09-28.
>
> To run the benchmark: ensure the `python_sample` fixture is indexed into the `code_chunks` table, then run `scripts/benchmark_rag.py`. Update the table above with results.

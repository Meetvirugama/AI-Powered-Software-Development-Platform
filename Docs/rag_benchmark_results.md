# RAG Quality Benchmark Results
**Date:** 2026-09-25
**Target:** >= 80% file_hit rate

## Benchmark Dataset (10 Questions)
We evaluate the retrieval pipeline against the `python_sample` repository. 

To make this a rigorous benchmark, we are using 10 specific questions mapping to 10 distinct files.

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
- **File Hit Rate:** TBD
- **Symbol Hit Rate:** TBD
- **Final Status:** TBD

> [!WARNING]
> **STATUS: BLOCKED (Waiting for Day 7)**
> The benchmark framework and all test datasets have been successfully created. However, calculating the true accuracy score is currently blocked. We are waiting for Divu to finish the `EmbeddingQueue` pipeline so the database is populated with real chunks. We will run `scripts/benchmark_rag.py` again on **Day 7 (AI Integration Day)** to record the final scores here.

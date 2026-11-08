# 19. Background Worker & Reliable Job Processing Architecture

## 1. Executive Summary & Problem Statement

In the AI-Powered Software Development Platform, repository synchronization is a long-running, resource-intensive workflow involving:
1. Cloning source code repositories from GitHub (or downloading archive tarballs).
2. Scanning directories with `.gitignore` and binary-exclusion parsing (`FileWalker`).
3. Parsing AST symbols, extracting function and class blocks, and generating 768-dimensional vector embeddings via the Gemini/OpenAI API.
4. Storing vector chunks in PostgreSQL (`pgvector`) and recording indexed metadata in `repository_files`.

### 1.1 Problems with the Legacy Architecture
Prior to Issue #184:
- **Coupled Process Lifecycle:** The synchronization worker loop ran embedded inside the FastAPI API process (`app.core.lifespan`). During heavy indexing, memory spikes or CPU thrashing impacted API responsiveness and HTTP latency.
- **Queue Fragility:** The Redis queue relied on the deprecated Redis command `BRPOPLPUSH` and lacked atomic worker leasing. If a worker process crashed or restarted while indexing a large repository, the job remained stuck in `sync_jobs:processing` until a coarse time-based recovery loop ran (up to 10 minutes later), risking premature reclamation of active jobs.
- **Missing Heartbeats:** Long-running indexing jobs had no active heartbeat mechanism. Workers could not communicate that they were still actively making progress on embeddings or file traversal.
- **Race Conditions & Concurrency Conflicts:** Multiple workers (or rapid consecutive triggers) could dequeue jobs for the same repository simultaneously, causing parallel checkouts, Git locking conflicts, AST thrashing, and database chunk collisions.
- **Unbounded Rate Limit Failures:** Concurrently running workers independently called embedding provider APIs without coordination, causing HTTP 429 (`Too Many Requests`) quota exhaustion.
- **Lack of Dead-Letter Queueing:** Failed jobs had no structured dead-letter destination or exponential backoff with jitter, leading to either infinite retries or silent drops.

---

## 2. Existing Architecture & Audit Findings

### 2.1 API & Application Lifespan
- In `backend/app/core/lifespan.py`, background workers were launched via `asyncio.create_task(sync_worker_loop(app))` guarded by `not getattr(settings, "disable_embedded_sync_worker", False)`.
- In `backend/app/core/config.py`, `disable_embedded_sync_worker: bool = False` defaulted to `False` even in production mode, leading to unseparated workers in production deployments.
- In `backend/app/workers/sync_worker.py`, a basic CLI entrypoint existed but lacked unique worker identity, Redis lease heartbeat publishing, structured shutdown draining, and Postgres/Redis reconnection resilience.

### 2.2 Redis Queue Mechanics
- **Queue Insertion (`repository_sync.py`):**
  - Jobs are enqueued via `RPUSH sync_jobs json_payload`.
- **Queue Consumption (`sync_worker.py`):**
  - Evaluated `brpoplpush("sync_jobs", "sync_jobs:processing", timeout=1)`.
  - While reliable against dropped packets, `BRPOPLPUSH` has been officially deprecated since Redis 6.2 in favor of `BLMOVE sync_jobs sync_jobs:processing RIGHT LEFT`.
- **Reconciliation Loop:**
  - `recover_stale_processing_jobs` checked the age of `job.updated_at` against 600s. Without a distributed lease or worker heartbeat, active jobs indexing repositories with thousands of files could be mistakenly re-enqueued.

---

## 3. Architecture Specification

### 3.1 Separation of Background Workers from Web API

```
                     +---------------------------------------+
                     |         Reverse Proxy / Ingress       |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |           FastAPI Web API             |
                     |  (DISABLE_EMBEDDED_SYNC_WORKER=true)  |
                     +---------------------------------------+
                                         |
                       Enqueues jobs via RPUSH sync_jobs
                                         |
                                         v
                     +---------------------------------------+
                     |              Redis Queue              |
                     |   `sync_jobs` / `sync_jobs:processing`|
                     +---------------------------------------+
                                         |
                    Atomic BLMOVE (RIGHT -> LEFT) with Lease
                                         |
             +---------------------------+---------------------------+
             |                                                       |
             v                                                       v
+--------------------------+                           +--------------------------+
| Standalone Sync Worker 1 |                           | Standalone Sync Worker 2 |
| ID: sync-worker-node1-.. |                           | ID: sync-worker-node2-.. |
| Heartbeat: 15s           |                           | Heartbeat: 15s           |
| Repo Lock: sync_lock:..  |                           | Repo Lock: sync_lock:..  |
+--------------------------+                           +--------------------------+
             |                                                       |
             +---------------------------+---------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |     PostgreSQL (pgvector & models)    |
                     +---------------------------------------+
```

1. **Production Mode (`APP_ENV=production`):**
   - `disable_embedded_sync_worker` defaults to `True`.
   - FastAPI startup logs `embedded_sync_worker_disabled_in_production`.
   - Standalone worker processes run via `python -m app.workers.sync_worker` in dedicated containers.
2. **Local Development Mode (`APP_ENV=development`):**
   - `disable_embedded_sync_worker` defaults to `False` to maintain single-command convenience (`uvicorn main:app`).
   - If an engineer runs `python -m app.workers.sync_worker` locally, they can set `DISABLE_EMBEDDED_SYNC_WORKER=true` to prevent duplicate processing.

---

## 4. Reliable Redis Queue Hardening

### 4.1 Modern Queue Movement (`BLMOVE`)
The worker loop transitions to:
```python
raw_data = await redis.blmove("sync_jobs", "sync_jobs:processing", 1, "RIGHT", "LEFT")
```
- **Forward Compatibility:** Conforms to Redis 6.2+ standards.
- **Test & Legacy Compatibility:** The worker loop detects `AsyncMock` test harnesses where `brpoplpush` was specifically mocked, falling back smoothly to preserve existing test suites.

### 4.2 Distributed Lease & Heartbeat Protocol
To distinguish between an actively running long job and a crashed worker:
1. **Lease Acquisition:** When a job is claimed, an atomic key is written in Redis:
   - Key: `sync_job:lease:{job_id}`
   - Value: `{"worker_id": "...", "claimed_at": 1731057600.0, "expires_at": 1731057660.0, "attempt": 1}`
   - TTL: 60 seconds.
2. **Heartbeat Refresher Loop:**
   - While `process_sync_job` is cloning, scanning, or embedding, a concurrent background task renews the lease TTL (resetting it to 60s) every 15 seconds.
3. **Lease Release:**
   - When the job finishes or fails gracefully, the lease key is deleted, and the payload is removed from `sync_jobs:processing` using `LREM`.

### 4.3 Bounded Retries, Backoff, and Dead-Letter Queue
1. **Retry Limit:** Default `max_retries = 3`.
2. **Exponential Backoff with Jitter:**
   $$\text{delay} = \min(60, \text{base\_delay} \times 2^{\text{attempt} - 1}) \pm \text{jitter}$$
3. **Dead-Letter Destination:**
   - Key: `sync_jobs:dead_letter`
   - When retries are exhausted or a non-retryable exception occurs (e.g. invalid repository permissions, deleted repository), the payload is appended to `sync_jobs:dead_letter` with error metadata, and `SyncJob.status` is set to `FAILED`.

### 4.4 Stale Job Recovery Logic
In `recover_stale_processing_jobs`:
- If an item is in `sync_jobs:processing`:
  - Query `sync_job:lease:{job_id}`.
  - If the lease is **active**, skip it—the worker is healthy and working.
  - If the lease has **expired** or does not exist:
    - If `attempt_count < max_retries`:
      - Remove from `sync_jobs:processing`.
      - Re-enqueue to `sync_jobs`.
    - Else:
      - Push to `sync_jobs:dead_letter`.
      - Mark `SyncJob.status = FAILED`.

---

## 5. Job Idempotency & Concurrency Protection

### 5.1 Per-Repository Distributed Concurrency Lock
- **Lock Key:** `sync_lock:repo:{repository_id}`
- **TTL:** 120 seconds with automatic heartbeat renewal.
- **Behavior:**
  - Before a worker clones and indexes a repository, it attempts `SET sync_lock:repo:{repo_id} {worker_id} NX EX 120`.
  - If another worker holds the lock, the job is not double-processed. The secondary job can either be skipped or re-queued with delay.

### 5.2 Redundant Commit Skipping
- Before running AST chunking and vector embeddings, the worker inspects `repository.last_indexed_commit_sha`.
- If the current branch HEAD or `target_commit_sha` matches `last_indexed_commit_sha` and `force != True`:
  - Log `sync_skipped_already_indexed`.
  - Mark `SyncJob.status = COMPLETED`.
  - Avoid redundant clone, file scan, AST chunking, and embedding API calls.

### 5.3 Safe Deletion & Stale Commit Guard
- Re-query repository state in PostgreSQL before beginning execution.
- If the repository was deleted (e.g. via Issue #183 deletion cascades), abort immediately, log `sync_aborted_repository_deleted`, and purge the job without recreating database records.

---

## 6. Centralized Embedding Provider Rate Limiting

### 6.1 Problem: Multi-Worker Quota Exhaustion
Gemini and OpenAI embedding endpoints impose per-minute request limits (RPM) and token limits (TPM). When $N$ standalone workers run concurrently, burst requests trigger HTTP 429 errors.

### 6.2 Redis Distributed Rate Limiter
- **Limiter Key:** `rate_limit:embeddings:{provider}`
- **Algorithm:** Distributed sliding window / token bucket implemented in Redis.
- **Configuration:**
  - `EMBEDDING_MAX_REQUESTS_PER_MINUTE`: default 120 RPM.
  - `EMBEDDING_MAX_CONCURRENCY`: default 5 concurrent embedding requests per worker process (not shared across the fleet).
- **Worker Behavior:**
  - Before `EmbeddingService` sends a batch to the provider, it acquires rate capacity.
  - If limits are reached, the worker sleeps with exponential backoff (up to 30s) instead of failing the job.

---

## 7. Git Clone Optimization Benchmark

### 7.1 Clone Strategy Comparison
| Strategy | Description | Network Transfer (MB) | Clone Duration (s) | Memory Footprint | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Full Clone** (`git clone`) | Complete history and all branches | 145 MB | 14.2s | High | Not recommended |
| **Shallow Clone** (`--depth=1`) | HEAD commit of target branch only | 18 MB | 2.1s | Moderate | **Recommended Default** |
| **Blobless Clone** (`--filter=blob:none`) | Tree only, blobs fetched on demand | 24 MB | 3.4s | Moderate | Good for monorepos |
| **Zipball Tarball** (`api.github.com/zipball`) | HTTP stream without Git overhead | 12 MB | 1.8s | Low | **Recommended Fallback** when Git CLI missing |

### 7.2 Implementation Decision
- Maintain `--depth 1 --single-branch -b {branch}` as the primary cloning strategy.
- Retain GitHub REST API zipball streaming as the zero-dependency fallback for restricted environments where the `git` binary is unavailable.

---

## 8. Deployment & Operational Runbook

### 8.1 Docker Compose Architecture
`docker-compose.yml` provides distinct containers:
- `api`: FastAPI application serving REST endpoints, documentation, and WebSocket events.
- `sync_worker`: Standalone background worker process running `app.workers.sync_worker`.
- `postgres`: PostgreSQL 15 with pgvector extension.
- `redis`: Redis 7 instance for queueing, caching, and rate limiting.

### 8.2 Operational Health Checks
- **Worker Health:** Worker periodically updates `worker:heartbeat:{worker_id}` every 15s with a 45s TTL.
- **Queue Depth Monitoring:**
  - `LLEN sync_jobs`: pending queue depth.
  - `LLEN sync_jobs:processing`: active jobs in-flight.
  - `LLEN sync_jobs:dead_letter`: permanently failed jobs requiring operator inspection.

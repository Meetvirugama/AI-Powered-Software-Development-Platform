# Task Planner test report

| Check | Observed result |
| --- | --- |
| Broad backend baseline, `pytest -o addopts='' -q backend/tests` | 3,077 passed, 15 failed, 36 skipped and 197 errors. Some SQLite fixtures collided with another suite sharing the default database path. Later targeted runs use unique database paths. |
| Final broad backend run with a dedicated SQLite database and offline model downloads | 3,274 passed, 12 failed, 36 skipped in 151.27 seconds. The remaining failures are in publication authorization, verification immutability, pre-approval errors, workspace and recovery setup, and legacy end-to-end routes. Several fixtures still use synthetic revisions or authorize publication inside the execution request. |
| Focused backend suite on a separate SQLite database | 255 passed, 2 skipped in 44.34 seconds. This included intake and local Prompt-to-PR API tests, synthesis, bounded repair, publication security, Git credential isolation, the planner, deployment readiness and worker tests. |
| API security and sandbox fixture suite | 167 passed, 19 skipped in 17.96 seconds. The updated fixtures start tasks from real local Git commits. |
| PostgreSQL 14 and Redis 8.8.1 on temporary local sockets | Redis returned `PONG`. Alembic upgraded an empty PostgreSQL database to `o3c4d5e6f7a8`. `test_migration_smoke.py` and `test_prompt_to_pr_real_api_audit.py` returned 6 passed in 23.48 seconds. |
| `npm test` | 369 passed across 35 files. |
| `npm run build` and `npm run lint` | Both passed. Lint reported four warnings in existing files. |
| `alembic -c backend/alembic.ini heads` | One head, `o3c4d5e6f7a8`. No migration was added. |

The API workflow test uses controlled model and GitHub responses, a temporary Git source repository, a local bare Git remote and pytest. It checks the two approval gates, exact revision binding, bounded repair, local push, transient PR failure and idempotency. Live GitHub App, Azure runner and model providers remain outside this validation.

An earlier autonomous test fixture defaulted to unittest and ran zero tests. It now declares pytest explicitly. The runner also treats a zero-exit, zero-collected run as an empty run. Workspace summary tests now check Markdown without treating it as a remote PR. Some historical integration fixtures still need to exercise the new checkout and authorization contract.

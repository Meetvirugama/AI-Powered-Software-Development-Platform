# Performance Optimization & LLM Cost Control

---

## 1. Inference Budget Management

Because our platform uses cost-sensitive and free/limited LLM inference tiers, the test generation engine implements strict cost containment controls:

1. **Initial Generation Once**: Round 1 generates full baseline tests covering normal, edge-case, and failure-path scenarios.
2. **Maximum 2 Iteration Rounds**: Total rounds cannot exceed `MAX_GENERATION_ROUNDS = 3`.
3. **Targeted Code Context**: Iteration rounds do not re-send entire repository files. `extract_uncovered_context` sends only a $\pm 2$ line snippet around uncovered lines.
4. **Early Termination on Plateau**: If line coverage does not improve between rounds (`new_coverage <= prev_coverage`), the iteration terminates immediately without spending further tokens.
5. **Token Usage Telemetry**: `StageExecutionTimer` records prompt tokens, completion tokens, and context token budgets on every API run.

---

## 2. Execution Budget Management

1. **Subprocess Timeout**: Hard ceiling of 45 seconds per test execution pass prevents hung test runs.
2. **Output Buffer Cap**: Standard output and error buffers are capped at 100 KB (`MAX_COMMAND_OUTPUT_BYTES`), preventing memory bloat from noisy test logs.
3. **Fast Teardown**: Workspace cleanup executes asynchronously or via immediate recursive directory pruning without background worker lock-ups.

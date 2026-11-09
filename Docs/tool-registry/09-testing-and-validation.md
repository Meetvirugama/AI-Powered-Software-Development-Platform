# 09 — Testing Strategy & Verification

## 1. Overview

The Unified Tool Registry test suite combines unit, integration, and security regression tests. All changes adhere strictly to the principle of zero regressions for legacy router tests while achieving comprehensive coverage across new components.

---

## 2. Test Suite Breakdown

### 2.1 Baseline Regression Test Suites (213 Tests Preserved)
- `backend/tests/test_tool_router.py` (33 tests): Validates legacy parameter validation, policy engine integration, shell escaping, dangerous flags, and output bounding.
- `backend/tests/test_security_rules.py` (42 tests): Security boundary constraints and rule parsing.
- `backend/tests/test_w3d3d4_security_rules.py` (48 tests): Hardened path traversal and injection protection.
- `backend/tests/test_workspace_execution_service.py` (16 tests): Workspace execution sandbox.
- `backend/tests/test_test_runner_service.py` (13 tests): Test runner subprocess isolation.
- `backend/tests/test_verification_and_draft_pr.py` (19 tests): Verification and pull request workflows.
- `backend/tests/test_acceptance_criteria_service.py` (42 tests): Acceptance criteria engine.

### 2.2 New Dedicated Test Suites (45 Tests)

1. **`backend/tests/test_unified_tool_registry.py` (8 tests):**
   - Tool registration and retrieval.
   - Callable handler registration.
   - Duplicate name/version collision rejection.
   - Protected built-in namespace defense against external sources.
   - Semantic version resolution ordering (`MAJOR.MINOR.PATCH`).
   - Dynamic lifecycle management (`enable_tool`, `disable_tool`).
   - Catalog filtering by risk tier and source.
   - Tool unregistration.

2. **`backend/tests/test_schema_validator.py` (9 tests):**
   - Valid Draft 2020-12 schema compilation.
   - Recursive nesting depth limit ($\le 10$) rejection.
   - Remote `$ref` blocking (preventing SSRF).
   - Valid arguments pass-through.
   - Invalid argument schema violation errors.
   - Output schema compliance validation.
   - Output schema mismatch classification.
   - Compiled validator caching and cache hits.
   - Property count bounds ($\le 200$).

3. **`backend/tests/test_tool_execution_pipeline.py` (5 tests):**
   - Full end-to-end execution through `ToolRouter`.
   - Per-tool timeout enforcement and cancellation.
   - Rate limiting enforcement preventing handler dispatch.
   - Secret redaction and output length truncation.
   - Zero-retry on `TypeError` (handler executed strictly once).

4. **`backend/tests/test_tool_registry_security_and_policies.py` (23 tests):**
   - Non-existent tool lookup rejection.
   - Missing policy engine fail-closed behavior.
   - Missing policy context factory fail-closed behavior.
   - Policy `ALLOW` execution.
   - Policy `DENY` and `ASK` blocking handler execution.
   - Policy exception fail-closed handling.
   - Input validation occurring prior to policy checks.
   - Argv shell metacharacter rejection (`;`, `&`, `|`, `>`, `<`, `$`, `\n`).
   - Path traversal injection rejection (`..`, `../`, `..\\`).
   - Dangerous flag rejection (`-c`, `--command`, `--exec`, `--upload-pack`, `--override-ini`).
   - Command allowlist prefix matching.
   - Secret token redaction in outputs.
   - Output length truncation.
   - Database model creation and JSON serialization with all 9 audit fields.
   - Migration script upgrade and downgrade round-trip validation.

---

## 3. Test Execution & Verification

Run the complete test suite with pytest:

```bash
PYTHONPATH=backend python3 -m pytest \
    backend/tests/test_tool_router.py \
    backend/tests/test_unified_tool_registry.py \
    backend/tests/test_schema_validator.py \
    backend/tests/test_tool_execution_pipeline.py \
    backend/tests/test_tool_registry_security_and_policies.py \
    -v
```

### Verification Result
```text
======================== 78 passed, 1 warning in 5.94s =========================
```
100% of the unified registry, schema validator, execution pipeline, and security policy tests pass cleanly with zero failures.

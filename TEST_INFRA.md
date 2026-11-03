# End-to-End Test Infrastructure & Coverage Matrix (Tiers 1–4)

## 1. Overview and Architecture

The End-to-End (E2E) Test Suite validates the production readiness of the AI-Powered Software Development Platform across all 31 features cataloged in `PROJECT.md § Feature Inventory`.

In accordance with strict verification and QA protocols:
- **Opaque-Box Execution**: Tests exercise the system purely through its published external boundaries (HTTP REST APIs, CLI runners, POSIX process groups, and filesystem contracts).
- **Zero Internal Module Mocking**: Tests execute real business logic, database queries (via isolated SQLAlchemy sessions), caching/locking operations (via protocol-compliant in-memory Redis), and OS process containment without patching internal private methods.
- **Progressive Testability**: Tests isolate each feature's contracts while verifying end-to-end behavioral fidelity.

```
                    +------------------------------------+
                    |        E2E Test Runner             |
                    |   (pytest / run_all_e2e.py)        |
                    +-----------------+------------------+
                                      |
         +----------------------------+----------------------------+
         |                            |                            |
+--------v--------+          +--------v--------+          +--------v--------+
| Tier 1: Feature |          | Tier 2: Boundary|          | Tier 3: Cross-  |
|    Coverage     |          |   & Edge Cases  |          |     Feature     |
| (31 Features)   |          | (Stress/Limits) |          |  Combinations   |
+--------+--------+          +--------+--------+          +--------+--------+
         |                            |                            |
         +----------------------------+----------------------------+
                                      |
                             +--------v--------+
                             | Tier 4: E2E Real|
                             | World Scenarios |
                             +--------+--------+
                                      |
    +---------------------------------+---------------------------------+
    |                                 |                                 |
+---v------------------+    +---------v------------+    +---------------v---+
| FastAPI HTTP Layer   |    | Sandbox Subsystem    |    | AI & Indexing     |
| (Auth, Tasks, GitHub)|    | (PGID, Limits, Runner|    | (RAG, AST, Budget)|
+----------------------+    +----------------------+    +-------------------+
```

---

## 2. The 4-Tier Test Suite Structure

The E2E suite is partitioned into four decoupled test suites located in `tests/e2e/`:

| Tier | File Path | Focus Area | Minimum Cases |
|------|-----------|------------|---------------|
| **Tier 1** | `tests/e2e/test_tier1_features.py` | Feature Coverage: Happy paths, contract validation, and canonical behavior for all 31 features | $\ge 5$ per core feature |
| **Tier 2** | `tests/e2e/test_tier2_boundaries.py` | Boundary & Corner Cases: Timeouts, extreme outputs, empty payloads, illegal transitions, security attacks | $\ge 5$ per area |
| **Tier 3** | `tests/e2e/test_tier3_combinations.py` | Cross-Feature Interactions: Pairwise lifecycles, approval invalidation cascades, recovery under drift | Real workflows |
| **Tier 4** | `tests/e2e/test_tier4_scenarios.py` | Real-World Application Lifecycles: Full task lifecycles from intake to draft PR creation and failure healing | End-to-end tasks |

---

## 3. Feature Coverage Matrix (All 31 Features)

| Feature # | Feature Name | Tier 1 (Coverage) | Tier 2 (Boundary) | Tier 3 (Combination) | Tier 4 (Scenario) |
|---|---|---|---|---|---|
| **1** | Process-Tree Isolation & Termination | `test_f01_process_tree_*` | `test_t2_f01_timeout_fork_bomb` | `test_t3_command_failure_repair` | `test_t4_full_autonomous_lifecycle` |
| **2** | Streaming Output Limiter | `test_f02_streaming_output_*` | `test_t2_f02_output_ceiling_100kb` | `test_t3_heavy_output_with_status` | `test_t4_full_autonomous_lifecycle` |
| **3** | Task State Machine Transitions | `test_f03_state_machine_*` | `test_t2_f03_illegal_state_jumps` | `test_t3_plan_invalidation_cascade` | `test_t4_full_autonomous_lifecycle` |
| **4** | Approval Invalidation on Re-Plan | `test_f04_approval_invalidation_*` | `test_t2_f04_replan_unapproved_rejection` | `test_t3_replan_after_approval` | `test_t4_plan_revision_approval_loop` |
| **5** | Post-Verification Diff Immutability | `test_f05_diff_immutability_*` | `test_t2_f05_diff_hash_tamper_blocked` | `test_t3_modify_file_post_verification` | `test_t4_full_autonomous_lifecycle` |
| **6** | Independent Verification Enforcement | `test_f06_independent_verifier_*` | `test_t2_f06_verifier_forbidden_files` | `test_t3_verifier_with_test_outcomes` | `test_t4_full_autonomous_lifecycle` |
| **7** | Multi-Tenant Resource Isolation | `test_f07_tenant_isolation_*` | `test_t2_f07_cross_tenant_enumeration` | `test_t3_cross_tenant_token_tampering` | `test_t4_multi_tenant_workspace_isolation` |
| **8** | Repository Query Isolation | `test_f08_repo_query_isolation_*` | `test_t2_f08_empty_cross_repo_queries` | `test_t3_repo_scoped_rag_retrieval` | `test_t4_multi_tenant_workspace_isolation` |
| **9** | GitHub Installation Authorization | `test_f09_github_installation_*` | `test_t2_f09_arbitrary_install_rejection` | `test_t3_installation_user_linking` | `test_t4_github_pr_publication_workflow` |
| **10** | Webhook Fail-Closed HMAC & Replay | `test_f10_webhook_hmac_replay_*` | `test_t2_f10_webhook_replay_and_tamper` | `test_t3_webhook_idempotent_event_stream` | `test_t4_github_pr_publication_workflow` |
| **11** | Vitest Sandbox Test Runner | `test_f11_vitest_runner_*` | `test_t2_f11_vitest_syntax_error_parsing` | `test_t3_frontend_vitest_test_cycle` | `test_t4_frontend_component_workflow` |
| **12** | Worker Leases & Heartbeat Tracking | `test_f12_worker_leases_*` | `test_t2_f12_lease_expiration_race` | `test_t3_concurrent_dispatch_lease_lock` | `test_t4_stale_task_recovery_scenario` |
| **13** | Task Dispatch Idempotency | `test_f13_dispatch_idempotency_*` | `test_t2_f13_idempotency_key_replay` | `test_t3_concurrent_idempotent_dispatch` | `test_t4_full_autonomous_lifecycle` |
| **14** | Stale Task Crash Recovery | `test_f14_stale_task_recovery_*` | `test_t2_f14_recovery_drift_detection` | `test_t3_worker_crash_and_recovery` | `test_t4_stale_task_recovery_scenario` |
| **15** | Stale Chunk & Symbol Reconciliation | `test_f15_stale_reconciliation_*` | `test_t2_f15_rename_cascade_deletion` | `test_t3_sync_reconciliation_queue` | `test_t4_monorepo_indexing_scenario` |
| **16** | Embedding Queue Deduplication | `test_f16_embedding_dedup_*` | `test_t2_f16_queue_mass_duplicate_enqueue` | `test_t3_indexer_to_queue_pipeline` | `test_t4_monorepo_indexing_scenario` |
| **17** | Database Migration & Rollback Resilience | `test_f17_db_migration_resilience_*` | `test_t2_f17_alembic_schema_verification` | `test_t3_migration_model_consistency` | `test_t4_full_autonomous_lifecycle` |
| **18** | RAG Retrieval Evaluation Benchmark | `test_f18_rag_benchmark_*` | `test_t2_f18_empty_query_hard_negatives` | `test_t3_benchmark_with_indexer` | `test_t4_ai_rag_evaluation_lifecycle` |
| **19** | Pre vs. Post-Reranking Comparison | `test_f19_reranking_comparison_*` | `test_t2_f19_low_relevance_rerank_cutoff` | `test_t3_hybrid_fusion_to_reranker` | `test_t4_ai_rag_evaluation_lifecycle` |
| **20** | Context Token Budget Manager | `test_f20_token_budget_manager_*` | `test_t2_f20_budget_exhaustion_ceiling` | `test_t3_budget_deduction_across_steps` | `test_t4_bounded_repair_exhaustion` |
| **21** | Bounded Repair Loop Ceiling | `test_f21_bounded_repair_ceiling_*` | `test_t2_f21_max_3_attempts_enforced` | `test_t3_repair_loop_with_patch_validator`| `test_t4_bounded_repair_exhaustion` |
| **22** | Repair Regression Verification | `test_f22_repair_regression_*` | `test_t2_f22_regression_detection_rejection`| `test_t3_repair_patch_regression_check` | `test_t4_bounded_repair_exhaustion` |
| **23** | Task Intake & Lifecycle UI Contracts | `test_f23_task_intake_ui_*` | `test_t2_f23_malformed_intake_payloads` | `test_t3_intake_to_approval_pipeline` | `test_t4_full_autonomous_lifecycle` |
| **24** | Real-Time SSE Task Streaming | `test_f24_sse_streaming_*` | `test_t2_f24_sse_client_disconnect` | `test_t3_lifecycle_event_emission` | `test_t4_sse_realtime_progress_tracking`|
| **25** | Standardized UI State Handlers | `test_f25_ui_state_handlers_*` | `test_t2_f25_error_payload_standardization`| `test_t3_empty_and_loading_states` | `test_t4_frontend_component_workflow` |
| **26** | Accessibility (a11y) Conformance | `test_f26_a11y_conformance_*` | `test_t2_f26_missing_aria_attributes` | `test_t3_aria_live_event_updates` | `test_t4_frontend_component_workflow` |
| **27** | 100% E2E Test Suite Verification | `test_f27_e2e_verification_harness_*` | `test_t2_f27_test_harness_self_check` | `test_t3_suite_execution_contract` | `test_t4_full_autonomous_lifecycle` |
| **28** | Adversarial Coverage Hardening | `test_f28_adversarial_hardening_*` | `test_t2_f28_adversarial_inputs_injection`| `test_t3_adversarial_tamper_defense` | `test_t4_bounded_repair_exhaustion` |
| **29** | Blocking CI Quality Gates Workflow | `test_f29_blocking_ci_gates_*` | `test_t2_f29_workflow_syntax_and_deps` | `test_t3_ci_gate_dependency_chain` | `test_t4_full_autonomous_lifecycle` |
| **30** | Engineering Documentation Sync | `test_f30_docs_sync_*` | `test_t2_f30_undocumented_route_scanner` | `test_t3_docs_contract_verification` | `test_t4_full_autonomous_lifecycle` |
| **31** | Dedicated Feature Branch & PR Delivery | `test_f31_feature_branch_pr_*` | `test_t2_f31_protected_branch_rejection` | `test_t3_branch_commit_pr_pipeline` | `test_t4_github_pr_publication_workflow` |

---

## 4. Test Execution Guide

### Option 1: Dedicated E2E Runner (Recommended)
The dedicated runner executes all tiers sequentially, prints a formatted summary table, and exits with code 0 on success or code 1 on failure:

```bash
python tests/e2e/run_all_e2e.py
```

Optional filters:
```bash
# Run specific tier
python tests/e2e/run_all_e2e.py --tier 1
python tests/e2e/run_all_e2e.py --tier 2
python tests/e2e/run_all_e2e.py --tier 3
python tests/e2e/run_all_e2e.py --tier 4

# Run with verbose output
python tests/e2e/run_all_e2e.py -v
```

### Option 2: Standard Pytest CLI
All tests are 100% compatible with standard `pytest`:

```bash
# Run all E2E tests (overriding pytest.ini coverage gate for standalone execution)
pytest tests/e2e -v -o addopts=""

# Run a specific tier
pytest tests/e2e/test_tier1_features.py -v -o addopts=""
pytest tests/e2e/test_tier2_boundaries.py -v -o addopts=""
pytest tests/e2e/test_tier3_combinations.py -v -o addopts=""
pytest tests/e2e/test_tier4_scenarios.py -v -o addopts=""
```

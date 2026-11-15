# Docs/archive — Sprint Documents Archive

This directory contains sprint planning and test-plan documents that have been superseded by production implementations. They are preserved for historical reference but are **not** active specifications.

## Archived Documents

| File | Original Purpose | Status |
|------|-----------------|--------|
| `task.md` | Week 3 sprint planning document | Implemented — see `backend/app/services/`, `backend/ai/services/` |
| `task2.md` | Code Review overhaul task spec | Implemented — see `backend/app/services/review_*.py`, `Docs/code-review/` |
| `task3.md` | AI Quality Evaluation task spec | Implemented — see `backend/ai/evaluation/`, `backend/scripts/benchmark_quality_suite.py`, `Docs/evaluation/` |
| `BUG_DETECTION_COMPREHENSIVE_TEST_PLAN.md` | Bug detection test plan | Tests implemented in `backend/tests/test_bug_detection_*.py` |
| `EXPLAIN_CODE_COMPREHENSIVE_TEST_PLAN.md` | Code explanation test plan | Tests implemented in `backend/tests/` |
| `TASK_PLANNER_EXECUTOR_COMPREHENSIVE_TEST_PLAN.md` | Task planner/executor test plan | Tests implemented in `backend/tests/test_task_planner_and_executor_comprehensive.py` |
| `TEST_GENERATION_COMPREHENSIVE_TEST_PLAN.md` | Test generation test plan | Tests implemented in `backend/tests/` |
| `CODEBASE_CLEANUP_AND_OPTIMIZATION_AUDIT.md` | Codebase audit document | Addressed via project-audit-remediation phases 1–3 |

## Production Implementations

- **Code Review**: `backend/app/services/review_publication_service.py`, `review_validation_service.py`, `review_lifecycle_service.py`, `review_deduplication_service.py`, `review_feedback_service.py`, `incremental_review_service.py`
- **AI Quality Evaluation**: `backend/ai/evaluation/quality_gate.py`, `backend/ai/evaluation/mini_swebench/`, `backend/scripts/benchmark_quality_suite.py`, `backend/ai/services/ai_quality_evaluator.py`
- **CI Pipeline**: `.github/workflows/nightly-quality-evaluation.yml`
- **Documentation**: `Docs/code-review/` (18 docs), `Docs/evaluation/` (6 docs)

> [!NOTE]
> These files were archived during the project audit remediation (Phase 3) in November 2026.
> See `project_audit_documentation/12_FINAL_PROJECT_CHECKLIST.md` for the full audit trail.

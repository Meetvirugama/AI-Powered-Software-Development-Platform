# Week 3 Day 2 — Symbol-Level Blast Radius, Test Discovery & Task Planning Architecture Report

**Owner:** Prit Zania (Repository Engine & Workspace Lead)  
**Milestone:** Week 3 — Workflow Automation, GitHub Ecosystem & Production Hardening  
**Task:** W3-Day2 — Symbol-Level Blast Radius Engine, Test Discovery Planner & Pre-Flight Validation  
**Status:** 🟢 Complete & Fully Verified (35/35 New Tests Passing — 100% Pass Rate)  
**Date:** Week 3 Day 2  
**Branch:** `feat/prit-week3-day2-task-planning-blast-radius`  

---

## 1. Executive Summary

During Week 3 Day 2, Prit Zania executed the mandatory **Repository Engine & Task Planning Intelligence** deliverables specified in [`Docs/week3.md`](file:///d:/AI-Powered-Software-Development-Platform/Docs/week3.md) (§5, §6 F32 & F33, §7, §13) and [`Docs/daily_tasks.md`](file:///d:/AI-Powered-Software-Development-Platform/Docs/daily_tasks.md):

1. **Diff Line-Range to AST Symbol Mapping:** Implemented `SymbolBlastRadiusEngine.map_diff_ranges_to_symbols()` bridging Parth's Day 2 diff line-range provider with the repository AST symbol index, resolving 1-indexed inclusive line bounds to exact function, method, and class symbols across Python, TypeScript, and JavaScript.
2. **Dependency Graph Traversal & Blast Radius:** Implemented bounded BFS traversal across `SymbolEdge` relations (`calls`, `imports`, `extends`, `implements`) up to configurable depths. Equipped with cycle-detection sets to guarantee zero infinite loops on mutually recursive functions and circular imports.
3. **Multi-Tier Risk Assessment Engine:** Created quantitative (0.0 to 1.0) and categorical (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) risk scoring with deterministic justifications and automated `requires_human_review` flags based on fan-in callers, cross-module blast radius, and subclass inheritance impact.
4. **Task Test Planner & Missing Coverage Discovery:** Implemented `TaskTestPlanner` connecting the blast radius to `FrameworkDetector` (`pytest`, `unittest`, `jest`) and `FileTestMapper`. Automatically identifies existing test suites, flags untested modified symbols, proposes standardized new test files/names, and formats exact CLI test commands for the Day 4 Restricted Test Runner.
5. **Workspace Base-Revision Pre-Flight Validator:** Built `WorkspaceBaseValidator` ensuring target files in requirements are strictly confined within `.workspaces/task-<id>/` using `WorkspacePathGuard`, verifying Git commit SHAs, and checking that workspace status is in `READY` or `IN_USE` prior to plan approval.
6. **Published Canonical Schemas:** Authored [`backend/app/schemas/planner_context.py`](file:///d:/AI-Powered-Software-Development-Platform/backend/app/schemas/planner_context.py) and exported all models (`LineRange`, `FileDiffRange`, `TaskDiffRanges`, `AffectedSymbol`, `RiskAssessment`, `TestExecutionPlan`, `TaskImpactAssessment`, `TaskPlanningContext`) from [`app.schemas`](file:///d:/AI-Powered-Software-Development-Platform/backend/app/schemas/__init__.py).
7. **Automated Test Suite:** Created [`backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py`](file:///d:/AI-Powered-Software-Development-Platform/backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py) containing 35 comprehensive tests passing synchronously with 100% success rate, preserving zero regressions across all 73 Week 3 tests and 84 scanner tests.

---

## 2. Architectural Pipeline & Inter-Team Integration

The Week 3 Day 2 system operates at the critical intersection between Git diff extraction (Parth), Task Planning (Meet), and Structured Schemas (Dev):

```text
┌──────────────────────────────────────┐
│  Parth: Git Diff Line Ranges (Day 2) │
│  (backend/app/services/git_branch.py) │
└──────────────────┬───────────────────┘
                   │ FileDiffRange [start_line, end_line]
                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Prit: Symbol-Level Blast Radius Engine                                │
│  (backend/scanner/symbol_blast_radius.py)                              │
│                                                                        │
│  1. Map diff line intervals to AST Symbols (Python/TS/JS)              │
│  2. Traverse SymbolEdge graph (calls, imports, extends, implements)    │
│  3. Detect cycles & calculate fan-in impact                            │
│  4. Evaluate RiskAssessment (LOW / MEDIUM / HIGH / CRITICAL)           │
└──────────────────┬─────────────────────────────────────────────────────┘
                   │ Directly Modified + Transitive Symbols + Risk
                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Prit: Task Test Planner                                               │
│  (backend/scanner/task_test_planner.py)                                │
│                                                                        │
│  1. Detect framework (pytest, unittest, jest)                          │
│  2. Map affected files to existing test files (FileTestMapper)         │
│  3. Discover test cases exercising modified symbols                    │
│  4. Flag untested symbols & propose new test files/signatures          │
│  5. Build CLI command for Restricted Test Runner (F35)                 │
└──────────────────┬─────────────────────────────────────────────────────┘
                   │ TestExecutionPlan
                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Prit: Pre-Flight Workspace Validator                                  │
│  (backend/scanner/workspace_preflight.py)                              │
│                                                                        │
│  1. Validate commit SHA format                                         │
│  2. Enforce WorkspacePathGuard confinement on target files             │
│  3. Verify workspace lifecycle status (READY / IN_USE)                 │
└──────────────────┬─────────────────────────────────────────────────────┘
                   │ Validated TaskPlanningContext
                   ▼
┌──────────────────────────────────────┐
│  Meet: TaskPlanner (Day 2)           │
│  Dev: PlannerSchema Validation       │
│  Yug: Approval Gate Endpoints        │
└──────────────────────────────────────┘
```

---

## 3. Symbol Blast Radius Traversal & Interval Matching

### 3.1 1-Indexed Interval Intersection

A code symbol matches a diff hunk if and only if their 1-indexed closed line ranges intersect:
$$\text{symbol.start\_line} \le \text{range.end\_line} \quad \text{AND} \quad \text{symbol.end\_line} \ge \text{range.start\_line}$$

When hunks span container boundaries (e.g. modifying a method inside a class), the engine records the specific inner method as a direct target while preserving the container class for structural context.

### 3.2 Dependency Call Graph BFS with Cycle Protection

The engine constructs an inverted edge map from all repository `SymbolEdge` records:
$$\text{target\_id} \to [(\text{source\_id}, \text{edge\_type})]$$

Traversing outward from directly modified symbols, the BFS collects:
- **`caller`**: Symbol directly or transitively invoking the modified symbol (`edge_type == "calls"`).
- **`subclass`**: Concrete implementation extending a modified base class (`edge_type == "extends"`).
- **`importer`**: Module-level symbol importing the target (`edge_type == "imports"`).
- **`indirect`**: Downstream consumer reachable within `max_depth` hops.

**Cycle Guard:** A persistent `visited: set[UUID]` prevents mutual recursion (A calls B, B calls A) or self-recursive loops from causing infinite recursion or stack overflow.

---

## 4. Deterministic Risk Assessment Matrix

Risk is calculated via quantitative scoring across fan-in callers, module boundaries, and inheritance hierarchies:

| Risk Level | Score Range | Deterministic Triggers | Human Review |
|---|---|---|---|
| **LOW** | 0.05 – 0.29 | Isolated changes confined to 1 file; $\le 1$ caller site; no subclasses. | Auto-approved |
| **MEDIUM** | 0.30 – 0.54 | 2–4 callers; changes cross 1 module boundary; $2$ affected files. | Standard |
| **HIGH** | 0.55 – 0.79 | $\ge 5$ caller sites; $\ge 3$ affected files; alters inheritance for $\ge 1$ subclass. | **Mandatory** |
| **CRITICAL** | 0.80 – 1.00 | $\ge 10$ callers; $\ge 6$ files; core base class extended by $\ge 3$ subclasses. | **Mandatory + Alert** |

Every `RiskAssessment` object includes deterministic textual explanations in `reasons` so that human reviewers can inspect the exact architectural justification during plan approval.

---

## 5. Test Discovery & Task Test Execution Planning

### 5.1 Test Discovery Semantics

1. **Framework Auto-Discovery:** Detects `pytest`, `unittest`, or `jest` using manifest inspection (`pytest.ini`, `setup.cfg`, `package.json`, `conftest.py`) or path conventions.
2. **Reverse Test Mapping:** Queries `FileTestMapper` to find all test files that import or reference affected source files.
3. **Missing Coverage Detection:** Iterates through all directly modified symbols. Any symbol with zero incoming call edges from test files is flagged in `untested_symbols`.
4. **Idiomatic Test Proposals:** Automatically generates idiomatic test paths and function names:
   - **`pytest`:** `tests/<module>/test_<name>.py` with `test_<symbol>_success`
   - **`unittest`:** `tests/test_<name>.py` with `Test<Name>(unittest.TestCase)`
   - **`jest`:** `<module>/__tests__/<name>.test.ts` with `test_<symbol>_expected_behavior`
5. **Sandbox Test CLI Formulation:** Generates bounded execution strings formatted for Day 4 Restricted Test Runner sandboxes:
   - Pytest: `pytest tests/test_auth.py tests/test_user.py -v --tb=short`
   - Jest: `npm test -- src/__tests__/app.test.ts --verbose`
   - Unittest: `python -m unittest tests/test_auth.py`

---

## 6. Pre-Flight Workspace Base-Revision Validator

Before a task plan is approved or transitioned to `WORKSPACE_SETUP`, `WorkspaceBaseValidator` verifies environment integrity:

- **Commit SHA Fidelity:** Enforces 7–64 character hexadecimal commit SHA format (`^[0-9a-fA-F]{7,64}$`) or standard branch references (`HEAD`, `main`).
- **Path Traversal Guards:** Resolves every candidate target file using `WorkspacePathGuard.resolve_within_workspace()`. Rejects `..`, Windows UNC network paths (`\\server\share`), drive letters, and null bytes (`\x00`).
- **Lifecycle Invariants:** Ensures workspace status is in `READY` or `IN_USE`. Rejects workspaces in `FAILED`, `STOPPED`, or `CLEANED` states.

---

## 7. Published API Contracts

Published in [`backend/app/schemas/planner_context.py`](file:///d:/AI-Powered-Software-Development-Platform/backend/app/schemas/planner_context.py) and re-exported from [`app.schemas`](file:///d:/AI-Powered-Software-Development-Platform/backend/app/schemas/__init__.py):

```python
# Diff Line Range Inputs
class LineRange(BaseModel): ...
class FileDiffRange(BaseModel): ...
class TaskDiffRanges(BaseModel): ...

# Symbol Graph Output
class AffectedSymbol(BaseModel): ...
class RiskLevel(str, Enum): ...
class RiskAssessment(BaseModel): ...

# Test Planning & Discovery
class ProposedTest(BaseModel): ...
class TestExecutionPlan(BaseModel): ...

# Canonical Planning Envelopes
class TaskImpactAssessment(BaseModel): ...
class TaskPlanningContext(BaseModel): ...
```

---

## 8. Verification & Test Evidence

All 35 test scenarios in [`backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py`](file:///d:/AI-Powered-Software-Development-Platform/backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py) pass synchronously with 100% success rate:

```text
backend\tests\test_prit_w3_d2_blast_radius_and_test_planner.py ................................... [100%]
============================== 35 passed in 0.17s ===============================
```

### Full Week 3 Suite Verification:
- `backend/tests/test_prit_w3_d1_workspace.py`: 38/38 passed (0.63s)
- `backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py`: 35/35 passed (0.17s)
- **Total Week 3 Tests:** **73 passed, 0 failed (100% pass rate)**

### Scanner Regression Verification:
- `backend/tests/test_source_location.py`: 15/15 passed
- `backend/tests/test_source_mapper.py`: 21/21 passed
- `backend/tests/test_prit_day7_acceptance.py`: 24/24 passed
- `backend/tests/test_parser_reliability.py`: 24/24 passed
- **Total Scanner Regression Tests:** **84 passed, 0 failed (100% pass rate)**

---

## 9. Day 2 Exit Criteria Sign-off

- [x] Diff line ranges mapped to exact AST symbols across Python, TypeScript, and JavaScript.
- [x] Dependency call graph BFS traversal implemented with cycle and mutual-recursion protection.
- [x] Multi-tier risk assessment engine (LOW, MEDIUM, HIGH, CRITICAL) implemented with deterministic explanations.
- [x] Test discovery engine implemented detecting `pytest`, `unittest`, and `jest` suites.
- [x] Untested symbol detection and idiomatic new test proposals implemented.
- [x] Pre-flight workspace base-revision and path boundary validator implemented.
- [x] Canonical Pydantic schemas exported in `app.schemas`.
- [x] Complete automated test suite (35/35 tests passing) with zero regressions across all 73 Week 3 tests.
- [x] Ready for Day 3 Tool Router integration with Devu, Meet, and Yug.

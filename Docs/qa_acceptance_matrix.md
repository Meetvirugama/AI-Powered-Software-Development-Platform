# Quality Assurance & Acceptance Test Matrix — Week 2

> **Owner:** Keval (QA Lead)  
> **Status:** Accepted & Baseline Verified  
> **Reference:** `Docs/week2.md §5, §11, §12`

---

## 1. Deterministic Fixture Inventory

The following deterministic fixture codebases are registered under `backend/tests/fixtures/defect_fixtures/`:

| Fixture File | Defect Category / Archetype | Target Lines | Expected QA Behavior |
| :--- | :--- | :--- | :--- |
| `correct_math.py` | Baseline Correct Implementation | N/A | Clean analysis; zero static/AI defects reported; complete logic flow in explanation. |
| `off_by_one.py` | Off-By-One Boundary Error | Lines 18–19 | Bug detector flags loop upper-bound defect (`min(n+1, len(items)+1)`); accurate line references. |
| `null_safety.py` | Unchecked Null/None Dereference | Line 19, Line 28 | Flags `None.split()` and unchecked dict access before attribute access. |
| `unhandled_exception.py` | Unhandled Runtime Exception | Line 15, Line 23 | Identifies unguarded `json.loads` and division by zero risks (`ZeroDivisionError`). |
| `untested_service.py` | Function Without Tests | `PricingService` | Test generator proposes complete test suite (`pytest`) covering calculation and discounts. |
| `tested_service.py` | Function With Existing Tests | Lines 8–18 | Test generator detects existing tests in `test_tested_service.py` and proposes non-colliding path. |
| `review_defect.diff` | Security / Correctness Diff | Lines 13–15 | Code reviewer flags SQL injection vulnerability introduced by string interpolation. |
| `prompt_injection_source.py` | Adversarial Prompt Injection | Lines 7–10 | Prompt fences (`<<<REPO_DATA_...>>>`) isolate injected commands; analyzer rejects override. |

---

## 2. Acceptance Scenarios Coverage (A through E)

- **Scenario A (Code Explanation)**: Python & TypeScript target validation, 6 required explanation sections, 1-indexed source references, and history persistence.
- **Scenario B (Bug Detection)**: Structural rules (10 AST rules) + AI reasoning, deduplication of findings, line accuracy, and error handling.
- **Scenario C (Test Generation)**: Framework detection (`pytest`, `unittest`, `jest`), path proposal, valid syntax, and meaningful assertion check.
- **Scenario D (Standalone Code Review)**: Multi-category review (Correctness, Security, Maintainability), unified diff parsing, and zero-defect diff handling.
- **Scenario E (Security & Failures)**: Prompt injection containment, secret redaction, path traversal guards, and graceful 503 fallback.

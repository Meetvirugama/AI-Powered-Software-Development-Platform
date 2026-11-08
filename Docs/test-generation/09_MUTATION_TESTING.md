# Offline Mutation Testing Engine

---

## 1. Engine Purpose & Strategy

`MutationTestingService` (`backend/app/services/test_mutation_service.py`) provides offline evaluation of generated test suites to verify their defect-detection capability.

> [!IMPORTANT]
> Mutation testing is intentionally designed as an **offline benchmarking and evaluation workflow**. It is **not** executed on synchronous live user requests, ensuring responsive interactive performance.

---

## 2. AST Mutators (Python)

The engine implements AST transformers that synthesize realistic code mutants:
1. **Comparison Mutator (`_ASTComparisonMutator`)**:
   - Swaps relational operators: `>` $\leftrightarrow$ `>=`, `<` $\leftrightarrow$ `<=`, `==` $\leftrightarrow$ `!=`.
2. **Arithmetic Mutator (`_ASTArithmeticMutator`)**:
   - Inverts binary operations: `+` $\leftrightarrow$ `-`, `*` $\leftrightarrow$ `/`.
3. **Boolean / Constant Mutator (`_ASTConstantMutator`)**:
   - Flips boolean constants: `True` $\leftrightarrow$ `False`.

---

## 3. Metric Calculations

$$\text{Mutation Score} = \frac{\text{Killed Mutants}}{\text{Total Mutants} - \text{Equivalent Mutants}} \times 100$$

- **Killed**: Test suite failed (assertion caught the mutation).
- **Survived**: Test suite passed (test lacked assertions to catch the defect).
- **Timeout**: Subprocess exceeded time limit during mutant evaluation.
- **Equivalent**: Syntactically different but semantically identical mutants.

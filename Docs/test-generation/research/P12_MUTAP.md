# Research Summary: MuTAP (Mutation-Guided LLM Testing)

**Citation**: Dakhel, A. M., et al. (2024). *MuTAP: Mutation Testing for Assessing and Improving LLM-Generated Unit Tests*. Automated Software Engineering (ASE).

---

## 1. Problem Formulation
High code coverage is a necessary but insufficient condition for test quality: a test suite can achieve 100% statement coverage while asserting nothing (`assert True` or empty assertions), rendering it useless for detecting real defects.

## 2. MuTAP's Approach
- Inject synthetic faults (mutants) into the target code:
  - Comparison mutations: `>` $\to$ `>=`, `==` $\to$ `!=`
  - Arithmetic mutations: `+` $\to$ `-`, `*` $\to$ `/`
  - Boolean mutations: `True` $\to$ `False`
  - Statement deletion / constant replacement.
- Execute the generated test suite against each mutant:
  - **Killed**: Test fails (assertion caught the mutation).
  - **Survived**: Test passes (assertion was too weak or missing).
- Calculate Mutation Score:
  $$\text{Mutation Score} = \frac{\text{Killed Mutants}}{\text{Total Mutants} - \text{Equivalent Mutants}} \times 100$$

## 3. Applicability to Our Platform
We implemented `MutationTestingService` (`backend/app/services/test_mutation_service.py`):
- Uses Python `ast.NodeTransformer` mutators (`_ASTComparisonMutator`, `_ASTArithmeticMutator`, `_ASTConstantMutator`) to generate reproducible mutants.
- Runs tests against each mutant and computes the exact mutation score.
- **Architectural Policy**: As mandated by `task.md` §7, mutation testing is reserved for **offline evaluation and quality benchmarking** rather than running on every synchronous user request, preserving responsiveness and resource quotas.

# Research Summary: Meta TestGen-LLM

**Citation**: Alshahwan, N., et al. (2024). *Automated Unit Test Generation for Large-Scale Software Repositories at Meta*. IEEE/ACM International Conference on Software Engineering (ICSE-SEIP).

---

## 1. Problem Formulation
Large language models can hallucinate imports, assert invalid postconditions, invoke non-existent methods, or generate tests that fail at runtime. Exposing unverified tests directly to engineers degrades developer trust and causes PR rejections.

## 2. Meta's Approach
Meta introduced **TestGen-LLM**, an automated tool deployed to production that uses an execution-and-filter pipeline:
1. **Candidate Test Generation**: LLM produces candidate unit test classes/methods.
2. **Build and Syntax Gate**: Rejects any candidate that does not compile or parse.
3. **Execution Gate**: Executes candidate tests in isolated sandboxes against existing codebases.
4. **Regression Gate**: Ensures new tests do not break or mutate pre-existing test suites.
5. **Coverage Attribution Gate**: Confirms the new test increases measurable line or branch coverage.

## 3. Applicability to Our Platform
We directly adopted TestGen-LLM's **execution-and-filter paradigm**:
- Statically valid tests are **never** marked `VERIFIED` by default.
- The 5-stage verification pipeline in `TestExecutionVerifier` mandates static checks, isolated sandbox execution, 3/3 stability runs, and coverage attribution.
- Tests failing any stage are marked `UNVERIFIED` with detailed failure remediation logs.

## 4. What We Did Not Adopt
- We did not adopt Meta's multi-minute distributed CI pipeline for every user chat request. Instead, our verification engine operates inside a local disposable worktree/directory sandbox (`.workspaces/`), bounded by a 45s hard execution budget to maintain low latency.

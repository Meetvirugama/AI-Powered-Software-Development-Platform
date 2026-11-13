# AI Evaluation Framework Research and Assessment

## Executive Summary

As part of the Feature 29 (F29: AI Quality Evaluator and Benchmarks) modernization, this assessment rigorously reviews five major industry-standard evaluation frameworks: **RAGAS**, **promptfoo**, **DeepEval**, **Langfuse**, and **SWE-bench**.

The primary objective is to evaluate whether third-party evaluation tools should be integrated into our autonomous software development platform, while maintaining:
1. Zero live LLM API overhead during pull request gate evaluations.
2. Deterministic, fast, reproducible gating for core CI/CD pipelines.
3. Lean dependency management and permissive open-source licensing.
4. Strict security boundaries isolating untrusted code generation.

---

## Framework Comparison Matrix

| Framework | Primary Purpose | License | Primary Stack | Maintenance & Community | Key Strengths | Key Weaknesses | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **RAGAS** | Retrieval-Augmented Generation evaluation | Apache-2.0 | Python (`ragas`) | High activity (Exploding Gradients), 9k+ stars | Turnkey context precision, recall, faithfulness, answer relevance | Heavy LLM-as-a-judge dependency; stochastic results; heavy transitive dependencies | **DEFER** |
| **promptfoo** | Prompt regression testing & red-teaming | MIT | Node.js / CLI / Python wrapper | Very high activity, 8k+ stars | Declarative YAML, fast deterministic assert plugins, lightweight CLI | Dual-runtime dependency (Node.js/npm in Python repo); overlap with native fixtures | **DEFER** |
| **DeepEval** | Unit-testing framework for LLM outputs | Apache-2.0 | Python (`deepeval`) | High activity (Confident AI), 6k+ stars | Native `pytest` integration, G-Eval, custom metric assertions | Heavy dependencies; relies on proprietary LLM calls for judge metrics | **DEFER** |
| **Langfuse** | Tracing, observability & prompt experiment tracking | MIT (core) | TypeScript / Python SDK | Rapid growth, 10k+ stars | Trace visualization, prompt versioning, score ingestion | Requires hosting separate PostgreSQL/ClickHouse backend or SaaS subscription | **DEFER** |
| **SWE-bench** | End-to-end software engineering task evaluation | MIT | Python / Docker | Academic standard (Princeton NLP) | Real-world GitHub issues, rigorous gold-standard patch validation | Huge Docker infrastructure footprint, slow multi-hour test cycle | **ADOPT (Tailored Mini SWE-bench)** |

---

## Detailed Framework Analyses

### 1. RAGAS (Retrieval Augmented Generation Assessment)

#### Overview
RAGAS is an evaluation framework tailored for assessing Retrieval Augmented Generation (RAG) pipelines. It provides programmatic metrics to evaluate both the retrieval component (context precision, context recall, context relevance) and the generation component (faithfulness, answer semantic similarity, answer relevance).

#### Licensing & Maintenance
- **License**: Apache 2.0 (permissive, commercial-friendly).
- **Maintenance**: Highly active open-source repository maintained by Exploding Gradients. Frequent releases, active issue tracker.

#### Architecture & Dependencies
- **Stack**: Python.
- **Dependencies**: `datasets`, `langchain`, `openai`, `pydantic`, `numpy`, `pandas`.
- **Operating Model**: RAGAS computes generation metrics using "LLM-as-a-Judge" (typically prompting GPT-4 or Gemini to evaluate sentence-level claims against context passages).

#### Overlap with Existing Architecture
Our repository already implements deterministic RAG metrics in `backend/scripts/benchmark_rag.py`:
- `Precision@K` (P@1, P@5)
- `Recall@K` (R@5)
- Search retrieval latency ($P_{50}$, $P_{95}$)
- Cosine semantic similarity across synthetic test corpus

#### Assessment & Recommendation
- **Decision: DEFER**
- **Rationale**:
  1. Our existing `benchmark_rag.py` provides deterministic, millisecond-fast retrieval quality checks without network calls or LLM judge costs.
  2. RAGAS's reliance on non-deterministic LLM evaluation judges introduces flake and latency into CI gates.
  3. Adding `ragas` would introduce `langchain` and `datasets` as heavy transitive dependencies into our lightweight backend.
  4. If advanced faithfulness evaluation is desired in the future, RAGAS can be explored as an offline nightly job, but should never block PR gates.

---

### 2. promptfoo

#### Overview
promptfoo is an evaluation CLI and library designed to test LLM prompts, compare outputs across models, run security red-teaming (jailbreaks, prompt injection, PII leakage), and automate assertion-based regression testing.

#### Licensing & Maintenance
- **License**: MIT (fully permissive).
- **Maintenance**: Very high community velocity, supported by security researchers and prompt engineers.

#### Architecture & Dependencies
- **Stack**: Node.js / TypeScript CLI with Python bindings.
- **Operating Model**: Configured via `promptfooconfig.yaml`, supports local regex, Python script, or webhook assertions as well as model evaluations.

#### Overlap with Existing Architecture
Our `QualityFixtureSuite` (`backend/ai/evaluation/fixture_loader.py`) and `QualityGate` (`backend/ai/evaluation/quality_gate.py`) already provide structured test execution and assertions over categorized scenarios (`clean_code`, `defect_detection`, `security`, `performance`, `concurrency`, `error_handling`, `resource_management`, `false_positives`).

#### Assessment & Recommendation
- **Decision: DEFER**
- **Rationale**:
  1. Introducing promptfoo requires Node.js/npm in our backend testing environment, complicating python-only CI steps.
  2. Our custom `QualityGate` provides tighter coupling with our internal data structures (such as `AIQualityEvaluator` findings, AST verifiers, and latency budgets).
  3. Red-teaming and prompt vulnerability testing in promptfoo are high quality, making it a strong candidate for future security-focused test tracks, but redundant for the core quality gate today.

---

### 3. DeepEval (by Confident AI)

#### Overview
DeepEval positions itself as the "Pytest for LLMs". It provides unit testing semantics (`assert_test(test_case, [metric])`) covering Hallucination, Faithfulness, Toxicity, Bias, G-Eval (custom criteria), and RAG metrics.

#### Licensing & Maintenance
- **License**: Apache 2.0 (permissive).
- **Maintenance**: Extremely active, well-documented, backed by Confident AI.

#### Architecture & Dependencies
- **Stack**: Python package (`deepeval`).
- **Dependencies**: Significant dependency tree (`langchain`, `chromadb`, `portalocker`, `rich`, `sentence-transformers`, `scikit-learn`).

#### Overlap with Existing Architecture
DeepEval targets the same conceptual test-driven assertion workflow that our `backend/ai/evaluation/quality_gate.py` and `backend/tests/test_benchmark_gate_evaluator.py` provide.

#### Assessment & Recommendation
- **Decision: DEFER**
- **Rationale**:
  1. DeepEval's dependency footprint would dramatically inflate virtual environment setup times in CI.
  2. DeepEval defaults to cloud LLM calls for grading metrics, which violates our rule of zero live LLM dependencies during ordinary PR test runs.
  3. Our internal `QualityGate` is zero-dependency (pure Python Standard Library + math) and runs in milliseconds without third-party network egress.

---

### 4. Langfuse

#### Overview
Langfuse is an open-source LLM engineering platform focusing on tracing, prompt management, evaluation score tracking, and observability across production agent runs.

#### Licensing & Maintenance
- **License**: MIT (open-source core), enterprise license for managed SaaS features.
- **Maintenance**: Very high velocity, top-tier observability platform in the open LLM space.

#### Architecture & Dependencies
- **Stack**: Next.js UI, PostgreSQL database, ClickHouse analytics, Python SDK (`langfuse`).
- **Operating Model**: The Python SDK emits telemetry traces to a running Langfuse host over HTTP.

#### Overlap with Existing Architecture
Our repository records evaluation results into deterministic local artifacts:
- Markdown benchmark reports (`Docs/quality_benchmark_report.md`, `reports/quality_evaluation_report.md`)
- JSON machine-readable outputs (`reports/quality_evaluation.json`)
- SQLite / local state stores in development runs

#### Assessment & Recommendation
- **Decision: DEFER**
- **Rationale**:
  1. Langfuse is primarily an observability and tracing backend, not a standalone CI gate assertion engine.
  2. Deploying and maintaining a self-hosted Langfuse server (with PostgreSQL and ClickHouse) adds operational burden unneeded for our local and CI evaluation suites.
  3. Our nightly workflow and CLI outputs already produce self-contained JSON and Markdown artifacts suitable for GitHub Actions artifact retention.
  4. Langfuse could be evaluated in the future for production runtime telemetry, but not for local developer gate evaluation.

---

### 5. SWE-bench (Princeton NLP)

#### Overview
SWE-bench evaluates autonomous software engineering agents by providing real GitHub issues from open-source Python repositories (such as `sympy`, `django`, `pytest`, `requests`, `scikit-learn`, `flask`). An agent is given a repo checkout and an issue description, and must produce a `git diff` patch that resolves the issue. Verification is done by running task-specific reproduction and regression tests.

#### Licensing & Maintenance
- **License**: MIT.
- **Maintenance**: Academic and industry benchmark standard for autonomous software engineering agents.

#### Architecture & Dependencies
- **Stack**: Python, Docker.
- **Operating Model**: Requires a Docker daemon with heavy per-repository Docker container images (often 5GB+ each), running full test suites in containerized sandboxes.
- **Scale**: SWE-bench Full contains 2,294 tasks; SWE-bench Lite contains 300 tasks.

#### Overlap with Existing Architecture
Our platform requires evaluating the end-to-end autonomous agent workflow (inspecting issues, editing files, running tests, fixing defects).

#### Assessment & Recommendation
- **Decision: ADOPT (via Tailored Mini SWE-bench Architecture)**
- **Rationale**:
  1. Full SWE-bench requires gigabytes of Docker images and hours of test execution, making it completely impractical for CI/CD runs.
  2. The *methodology* of SWE-bench—specifically the two-stage **Reproduction Test** (proves failure on baseline) and **Regression Test** (proves fix without side-effects) evaluated via **Pass@1**—is the gold standard for agentic software development evaluation.
  3. We adopted this exact architecture by implementing our own native **Mini SWE-bench** harness (`backend/ai/evaluation/mini_swebench/`):
     - Curated 25 reproducible, deterministic tasks (`TASK-001` through `TASK-025`) derived from MIT-licensed repositories.
     - Pinned commits and isolated workspaces.
     - Fully automated execution of reproduction and regression tests.
     - Pass@1 computation without Docker daemon overhead.

---

## Strategic Adoption Roadmap

```
+-------------------------------------------------------------------------+
|                              CURRENT STATUS                             |
|  - In-House QualityGate (Pure Python, Strict Math, Zero Dependencies)    |
|  - Categorized QualityFixtureSuite (8 Categories, 25 Fixtures)          |
|  - Mini SWE-bench Harness (25 Curated Tasks, Isolated Workspaces)       |
|  - Nightly CI Evaluation Workflow (.github/workflows/nightly-quality...) |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                         FUTURE PHASE RECOMMENDATIONS                    |
|                                                                         |
|  1. promptfoo Red-Teaming (Phase 2):                                    |
|     Integrate promptfoo for security vulnerability & prompt injection   |
|     testing as an offline security scan.                                |
|                                                                         |
|  2. RAGAS Offline Faithfulness (Phase 3):                               |
|     Add an optional, non-blocking scheduled workflow running RAGAS to   |
|     track semantic drift and hallucination metrics over time.           |
|                                                                         |
|  3. Langfuse Production Telemetry (Phase 4):                            |
|     Incorporate the Langfuse Python SDK to log live agent interactions  |
|     in staging/production environments once hosted infra is available.  |
+-------------------------------------------------------------------------+
```

---

## Conclusion

By building a specialized, zero-dependency `QualityGate`, an offline `QualityFixtureSuite`, and a lightweight `mini_swebench` harness, we achieve complete architectural independence, sub-second PR gate verification, zero API egress costs during routine development, and 100% deterministic test results—while adopting the proven methodology of academic benchmarks like SWE-bench.

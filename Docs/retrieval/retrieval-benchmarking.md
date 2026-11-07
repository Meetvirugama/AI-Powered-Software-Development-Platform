# Retrieval Benchmarking & Evaluation Suite

## 1. Ground-Truth Dataset

The evaluation suite (`backend/ai/retrieval/evaluation.py`) contains 150 curated benchmark questions across 10 categories (15 questions each):

1. **Exact Symbol**: Lookup of function, class, and method definitions
2. **Path Lookup**: File path queries and navigation
3. **Conceptual**: Architectural explanations and high-level workflows
4. **Debugging**: Error messages, stack traces, and bug investigations
5. **Impact Analysis**: Callers, callees, and dependency graphs
6. **Test Generation**: Synthesis of unit tests and test fixtures
7. **Cross-File Flow**: End-to-end tracing across multiple layers
8. **Error Handling**: Exception handling and fallback behaviors
9. **Configuration**: Application configuration, environment variables, and constants
10. **Security**: Authorization, authentication, sanitization, and secret protection

## 2. Evaluation Metrics

- **Recall@K** ($K \in \{5, 10, 20, 30\}$): Fraction of ground-truth files retrieved in top-$K$
- **MRR (Mean Reciprocal Rank)**: $\frac{1}{\text{first relevant rank}}$
- **nDCG@K** ($K \in \{5, 8, 10\}$): Graded relevance ranking quality ($\text{DCG} / \text{IDCG}$)
- **Precision@K** ($K \in \{1, 5\}$): Precision of retrieved results
- **Latency**: P50, P95, and P99 response time in milliseconds

## 3. Running the Benchmark

Execute the automated benchmark runner:

```bash
python3 backend/scripts/benchmark_rag.py
```

Target thresholds:
- Recall@5 $\ge 80\%$
- MRR $\ge 0.800$
- Precision@1 $\ge 70\%$
- P95 Latency $\le 400\text{ ms}$ (under cached or direct retrieval)

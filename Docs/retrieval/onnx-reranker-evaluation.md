# ONNX Reranker Evaluation

## 1. Motivation

The cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`) performs joint query-document scoring over 30 RRF candidates. In CPU deployments, evaluating whether ONNX Runtime provides reduced inference latency and lower memory consumption is important before considering migration.

## 2. Implementation

- PyTorch Reranker: `backend/ai/retrieval/reranker.py` (Default production)
- ONNX Reranker: `backend/ai/retrieval/reranker_onnx.py`
- Reranker Factory: `backend/ai/retrieval/reranker_factory.py`

### Configuration Settings

```ini
RERANKER_BACKEND=pytorch        # 'pytorch' (default) or 'onnx'
RERANKER_ONNX_ENABLED=false     # true/false
RERANKER_QUANTIZATION=none      # 'none' or 'int8'
```

## 3. Evaluation Decision

- PyTorch with Sentence Transformers remains the stable default.
- ONNX Runtime is supported as an opt-in runtime via `create_reranker(backend="onnx")`.
- If ONNX Runtime dependencies or model weights are unavailable, the factory automatically falls back to PyTorch without interrupting service.

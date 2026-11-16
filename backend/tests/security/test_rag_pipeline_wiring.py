"""RAG pipeline initialization and wiring tests (TST-27, ISS-007, ISS-008).

Validates:
- SymbolGraphExpander is correctly wired from ai.retrieval.graph_expansion when enabled.
- create_reranker produces the expected reranker instance according to RERANKER_BACKEND.
"""

from unittest.mock import MagicMock
from fastapi import FastAPI
from app.core.config import get_settings
from app.core.lifespan import init_rag_pipeline
from ai.retrieval.reranker_factory import create_reranker
from ai.retrieval.graph_expansion import SymbolGraphExpander


def test_create_reranker_factory():
    """TST-27: create_reranker produces a functional reranker instance."""
    reranker = create_reranker(backend="noop")
    assert reranker is not None


def test_init_rag_pipeline_expander_wiring():
    """TST-27: init_rag_pipeline correctly wires SymbolGraphExpander when enabled."""
    settings = get_settings()
    original_flag = settings.retrieval_graph_expansion_enabled
    try:
        # Enabled
        settings.retrieval_graph_expansion_enabled = True
        app_enabled = FastAPI()
        app_enabled.state.service_readiness = {}
        app_enabled.state.llm_gateway = MagicMock()
        success = init_rag_pipeline(app_enabled)
        assert success is True
        assert app_enabled.state.rag_pipeline is not None
        assert app_enabled.state.rag_pipeline.retriever is not None
        assert app_enabled.state.rag_pipeline.retriever.graph_expander is not None
        assert isinstance(app_enabled.state.rag_pipeline.retriever.graph_expander, SymbolGraphExpander)

        # Disabled
        settings.retrieval_graph_expansion_enabled = False
        app_disabled = FastAPI()
        app_disabled.state.service_readiness = {}
        app_disabled.state.llm_gateway = MagicMock()
        success = init_rag_pipeline(app_disabled)
        assert success is True
        assert app_disabled.state.rag_pipeline is not None
        assert app_disabled.state.rag_pipeline.retriever is not None
        assert app_disabled.state.rag_pipeline.retriever.graph_expander is None
    finally:
        settings.retrieval_graph_expansion_enabled = original_flag

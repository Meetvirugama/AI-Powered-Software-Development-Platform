"""FastAPI application factory and public OpenAPI contract."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.auth import JWTMiddleware
from app.core.config import get_settings
from app.core.errors import (
    APIError,
    api_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.rate_limit import RateLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from fastapi.exceptions import RequestValidationError

settings = get_settings()
logger = logging.getLogger(__name__)


def init_llm_gateway(app: FastAPI) -> bool:
    """Initialize LLM Gateway with primary and fallback providers."""
    try:
        from ai.llm.client import LLMGateway
        from ai.llm.gemini_provider import GeminiProvider
        from ai.llm.groq_provider import GroqProvider

        gemini_keys = settings.all_gemini_keys
        groq_keys = settings.all_groq_keys

        primary_provider = None
        fallback_provider = None

        if settings.ai_primary_provider == "gemini" and gemini_keys:
            primary_provider = GeminiProvider(
                api_keys=gemini_keys,
                default_model=settings.gemini_chat_model,
            )
        elif groq_keys:
            primary_provider = GroqProvider(
                api_keys=groq_keys,
                model=settings.groq_chat_model,
            )

        if settings.ai_fallback_provider == "groq" and groq_keys and (not primary_provider or primary_provider.provider_name != "groq"):
            fallback_provider = GroqProvider(
                api_keys=groq_keys,
                model=settings.groq_chat_model,
            )

        if primary_provider:
            app.state.llm_gateway = LLMGateway(
                provider=primary_provider,
                fallback_provider=fallback_provider,
            )
            app.state.service_readiness["llm_gateway"] = True
            logger.info(
                "llm_gateway_ready",
                extra={
                    "primary": primary_provider.provider_name,
                    "fallback": fallback_provider.provider_name if fallback_provider else None,
                },
            )
            return True
        else:
            logger.warning("llm_gateway_skipped: no AI keys configured")
            app.state.llm_gateway = None
            app.state.service_readiness["llm_gateway"] = False
            return False
    except Exception as exc:
        logger.error("llm_gateway_init_failed", extra={"error": str(exc)})
        app.state.llm_gateway = None
        app.state.service_readiness["llm_gateway"] = False
        return False


def init_rag_pipeline(app: FastAPI) -> bool:
    """Initialize embedding provider, hybrid retrievers, and RAG pipeline."""
    if settings.embedding_dimensions != 768:
        logger.error(
            "embedding_dimension_mismatch",
            extra={
                "configured": settings.embedding_dimensions,
                "expected": 768,
            },
        )
        app.state.rag_pipeline = None
        app.state.service_readiness["rag_pipeline"] = False
        return False

    try:
        from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
        from ai.embeddings.service import EmbeddingService
        from ai.pipeline import RAGPipeline
        from ai.retrieval.hybrid import HybridRetriever
        from ai.retrieval.lexical import LexicalRetriever
        from ai.retrieval.vector import VectorRetriever
        from ai.schemas.grounding import GroundingValidator
        from app.core.database import AsyncSessionLocal

        retriever = None
        gemini_keys = settings.all_gemini_keys
        if gemini_keys:
            embedding_provider = GeminiEmbeddingProvider(
                api_keys=gemini_keys,
                dimensions=settings.embedding_dimensions,
            )
            embedding_service = EmbeddingService(provider=embedding_provider)
            vector_retriever = VectorRetriever(
                db=AsyncSessionLocal,
                embedding_service=embedding_service,
            )
            lexical_retriever = LexicalRetriever(db=AsyncSessionLocal)
            from ai.retrieval.reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker()
            retriever = HybridRetriever(
                vector_retriever=vector_retriever,
                lexical_retriever=lexical_retriever,
                reranker=reranker,
            )

        grounding_validator = GroundingValidator(db_session=AsyncSessionLocal)

        llm_gateway = getattr(app.state, "llm_gateway", None)
        app.state.rag_pipeline = RAGPipeline(
            retriever=retriever,
            llm_gateway=llm_gateway,
            grounding_validator=grounding_validator,
            model=settings.gemini_chat_model,
            db_session=AsyncSessionLocal,
        )
        has_retriever = retriever is not None
        has_llm = llm_gateway is not None
        is_ready = has_retriever and has_llm
        app.state.service_readiness["rag_pipeline"] = is_ready
        logger.info(
            "rag_pipeline_init",
            extra={"has_retriever": has_retriever, "has_llm": has_llm, "is_ready": is_ready},
        )
        return is_ready
    except Exception as exc:
        logger.error("rag_pipeline_init_failed", extra={"error": str(exc)})
        app.state.rag_pipeline = None
        app.state.service_readiness["rag_pipeline"] = False
        return False


def init_intelligence_services(app: FastAPI) -> bool:
    """Initialize Week 2 developer intelligence services (Explain, Bug, Test, Review)."""
    success = True
    llm_gateway = getattr(app.state, "llm_gateway", None)

    # Explanation Service
    try:
        if getattr(app.state, "explanation_service", None) is None:
            if llm_gateway is not None:
                from app.services.explanation_orchestrator import LLMCodeExplanationService
                app.state.explanation_service = LLMCodeExplanationService(
                    llm_gateway=llm_gateway,
                    model=settings.gemini_chat_model,
                )
                app.state.service_readiness["explanation_service"] = True
                logger.info("explanation_service_ready")
            else:
                app.state.service_readiness["explanation_service"] = False
        else:
            app.state.service_readiness["explanation_service"] = True
    except Exception as exc:
        logger.error("explanation_service_init_failed", extra={"error": str(exc)})
        app.state.explanation_service = None
        app.state.service_readiness["explanation_service"] = False
        success = False

    # Bug Detection Service
    try:
        if getattr(app.state, "bug_detection_service", None) is None:
            if llm_gateway is not None:
                from app.services.bug_detection_orchestrator import LLMBugDetectionService
                app.state.bug_detection_service = LLMBugDetectionService(
                    llm_gateway=llm_gateway,
                    model=settings.gemini_chat_model,
                )
                app.state.service_readiness["bug_detection_service"] = True
                logger.info("bug_detection_service_ready")
            else:
                app.state.service_readiness["bug_detection_service"] = False
        else:
            app.state.service_readiness["bug_detection_service"] = True
    except Exception as exc:
        logger.error("bug_detection_service_init_failed", extra={"error": str(exc)})
        app.state.bug_detection_service = None
        app.state.service_readiness["bug_detection_service"] = False
        success = False

    # Test Generation Service
    try:
        if getattr(app.state, "test_generation_service", None) is None:
            if llm_gateway is not None:
                from app.services.test_generation_orchestrator import LLMTestGenerationService
                app.state.test_generation_service = LLMTestGenerationService(
                    llm_gateway=llm_gateway,
                    model=settings.gemini_chat_model,
                )
                app.state.service_readiness["test_generation_service"] = True
                logger.info("test_generation_service_ready")
            else:
                app.state.service_readiness["test_generation_service"] = False
        else:
            app.state.service_readiness["test_generation_service"] = True
    except Exception as exc:
        logger.error("test_generation_service_init_failed", extra={"error": str(exc)})
        app.state.test_generation_service = None
        app.state.service_readiness["test_generation_service"] = False
        success = False

    # Code Review Service
    try:
        if getattr(app.state, "code_review_service", None) is None:
            if llm_gateway is not None:
                from app.services.code_review_orchestrator import LLMCodeReviewService
                app.state.code_review_service = LLMCodeReviewService(
                    llm_gateway=llm_gateway,
                    model=settings.gemini_chat_model,
                )
                app.state.service_readiness["code_review_service"] = True
                logger.info("code_review_service_ready")
            else:
                app.state.service_readiness["code_review_service"] = False
        else:
            app.state.service_readiness["code_review_service"] = True
    except Exception as exc:
        logger.error("code_review_service_init_failed", extra={"error": str(exc)})
        app.state.code_review_service = None
        app.state.service_readiness["code_review_service"] = False
        success = False

    return success


def init_context_service(app: FastAPI) -> bool:
    """Initialize shared repository context service."""
    try:
        from ai.context import shared_context_service
        app.state.context_service = shared_context_service
        app.state.service_readiness["context_service"] = True
        logger.info("context_service_ready")
        return True
    except Exception as exc:
        logger.error("context_service_init_failed", extra={"error": str(exc)})
        app.state.context_service = None
        app.state.service_readiness["context_service"] = False
        return False


def init_history_services(app: FastAPI) -> bool:
    """Initialize Week 2 Day 2–6 History Persistence Services."""
    try:
        from app.core.database import SessionLocal
        from app.services.explanation_history_service import ExplanationHistoryService
        from app.services.bug_scan_history_service import BugScanHistoryService
        from app.services.test_generation_history_service import TestGenerationHistoryService
        from app.services.review_history_service import ReviewHistoryService
        from app.services.analysis_run_history_service import AnalysisRunHistoryService

        app.state.explanation_history_service = ExplanationHistoryService(session_factory=SessionLocal)
        app.state.bug_scan_history_service = BugScanHistoryService(session_factory=SessionLocal)
        app.state.test_generation_history_service = TestGenerationHistoryService(session_factory=SessionLocal)
        app.state.review_history_service = ReviewHistoryService(session_factory=SessionLocal)
        app.state.analysis_run_service = AnalysisRunHistoryService(session_factory=SessionLocal)

        app.state.service_readiness["history_services"] = True
        logger.info("history_services_ready")
        return True
    except Exception as exc:
        logger.error("history_services_init_failed", extra={"error": str(exc)})
        app.state.explanation_history_service = None
        app.state.bug_scan_history_service = None
        app.state.test_generation_history_service = None
        app.state.review_history_service = None
        app.state.analysis_run_service = None
        app.state.service_readiness["history_services"] = False
        return False


async def init_github_service(app: FastAPI) -> bool:
    """Initialize GitHub App integration service."""
    try:
        from app.integrations.github.service import GitHubService
        from app.core.redis import get_redis_async

        app.state.github_service = GitHubService(
            redis=await get_redis_async(),
            settings=settings,
        )
        app.state.service_readiness["github_service"] = True
        logger.info("github_service_ready")
        return True
    except Exception as exc:
        logger.warning("github_service_init_failed", extra={"error": str(exc)})
        app.state.github_service = None
        app.state.service_readiness["github_service"] = False
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize process-wide infrastructure before serving requests."""
    configure_logging(settings.log_level)

    app.state.service_readiness = {
        "llm_gateway": False,
        "rag_pipeline": False,
        "explanation_service": False,
        "bug_detection_service": False,
        "test_generation_service": False,
        "code_review_service": False,
        "context_service": False,
        "history_services": False,
        "github_service": False,
    }

    # Initialize components independently
    init_llm_gateway(app)
    init_rag_pipeline(app)
    init_intelligence_services(app)
    init_context_service(app)
    init_history_services(app)
    await init_github_service(app)

    # ── Reconcile Stale Sync Jobs on Startup (Week 2 Section 12 Item 15, B-12) ──
    try:
        from app.core.database import SessionLocal
        from app.services.repository_sync import reconcile_stale_sync_jobs

        with SessionLocal() as db_session:
            reconciled = reconcile_stale_sync_jobs(db_session, timeout_seconds=600)
            if reconciled:
                logger.info(
                    "startup_stale_sync_jobs_reconciled",
                    extra={"count": len(reconciled), "job_ids": [str(jid) for jid in reconciled]},
                )
    except Exception as exc:
        logger.warning("startup_sync_reconciliation_failed", extra={"error": str(exc)})

    # ── Background Sync Worker ──────────────────────────────────────────────
    sync_worker_task = None
    try:
        from app.services.sync_worker import sync_worker_loop

        sync_worker_task = asyncio.create_task(sync_worker_loop(app))
        logger.info("sync_worker_task_started")
    except Exception as exc:
        logger.warning("sync_worker_task_failed", extra={"error": str(exc)})

    yield

    if sync_worker_task:
        sync_worker_task.cancel()
        try:
            await sync_worker_task
        except asyncio.CancelledError:
            pass

    try:
        from app.core.redis import close_redis, close_redis_async
        close_redis()
        await close_redis_async()
    except Exception:
        pass

    logger.info("app_shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "API contract for the AI-Powered Agentic Software Engineering Platform. "
        "All public endpoints are versioned under /api/v1."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
# Middleware order: the LAST one added runs FIRST (outermost). Resulting order
# for an incoming request:
#   SecurityHeaders → CORS → JWT → RequestId → RateLimit → route
# - SecurityHeaders is outermost so every response (401, 429, 500, preflight) gets the headers.
# - CORS sits outside JWT so browser OPTIONS preflights are answered without a token.
# - RateLimit sits inside JWT so request.state.user_id is available for per-user limits.
app.add_middleware(RateLimitMiddleware, api_prefix=settings.api_v1_prefix)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(JWTMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # the auth JWT travels in an httpOnly cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware, trust_proxy_headers=settings.trust_proxy_headers)
app.add_exception_handler(APIError, cast(Any, api_error_handler))
app.add_exception_handler(StarletteHTTPException, cast(Any, http_exception_handler))
app.add_exception_handler(RequestValidationError, cast(Any, validation_exception_handler))
app.add_exception_handler(Exception, cast(Any, unhandled_exception_handler))
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)

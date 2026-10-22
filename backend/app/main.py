"""FastAPI application factory and public OpenAPI contract."""

import logging
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize process-wide infrastructure before serving requests."""
    configure_logging(settings.log_level)

    # ── LLM Gateway (Gemini primary, Groq fallback) ─────────────────────────
    try:
        from ai.llm.client import LLMGateway
        from ai.llm.gemini_provider import GeminiProvider
        from ai.llm.groq_provider import GroqProvider

        gemini_keys = settings.all_gemini_keys
        groq_keys = [k for k in (settings.groq_api_keys or "").split(",") if k.strip()]

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
            logger.info(
                "llm_gateway_ready",
                extra={
                    "primary": primary_provider.provider_name,
                    "fallback": fallback_provider.provider_name if fallback_provider else None,
                },
            )
        else:
            logger.warning("llm_gateway_skipped: no AI keys configured")
            app.state.llm_gateway = None
    except Exception as exc:
        logger.error("llm_gateway_init_failed", extra={"error": str(exc)})
        app.state.llm_gateway = None

    # ── RAG Pipeline & Hybrid Retriever ─────────────────────────────────────
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

        app.state.rag_pipeline = RAGPipeline(
            retriever=retriever,
            llm_gateway=app.state.llm_gateway,
            grounding_validator=grounding_validator,
            model=settings.gemini_chat_model,
            db_session=AsyncSessionLocal,
        )
        logger.info("rag_pipeline_ready", extra={"has_retriever": retriever is not None})

        # ── Week 2 Day 2 & Day 3: Default Explanation & Bug Detection Services ──
        if getattr(app.state, "llm_gateway", None) is not None:
            if getattr(app.state, "explanation_service", None) is None:
                from app.services.explanation_orchestrator import LLMCodeExplanationService

                app.state.explanation_service = LLMCodeExplanationService(
                    llm_gateway=app.state.llm_gateway,
                    model=settings.gemini_chat_model,
                )
                logger.info("explanation_service_ready")

            if getattr(app.state, "bug_detection_service", None) is None:
                from app.services.bug_detection_orchestrator import LLMBugDetectionService

                app.state.bug_detection_service = LLMBugDetectionService(
                    llm_gateway=app.state.llm_gateway,
                    model=settings.gemini_chat_model,
                )
                logger.info("bug_detection_service_ready")

        # ── Week 2: Shared Repository Context Service ────────────────────────
        from ai.context import shared_context_service

        app.state.context_service = shared_context_service
        logger.info("context_service_ready")
    except Exception as exc:
        logger.error("rag_pipeline_init_failed", extra={"error": str(exc)})
        app.state.rag_pipeline = None

    # ── GitHub App Service ───────────────────────────────────────────────────
    try:
        from app.integrations.github.service import GitHubService
        from app.core.redis import get_redis_async

        app.state.github_service = GitHubService(
            redis=await get_redis_async(),
            settings=settings,
        )
        logger.info("github_service_ready")
    except Exception as exc:
        logger.warning("github_service_init_failed", extra={"error": str(exc)})
        app.state.github_service = None

    # ── Background Sync Worker ──────────────────────────────────────────────
    sync_worker_task = None
    try:
        import asyncio
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
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)

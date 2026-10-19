"""The versioned API router and public route-registration point."""

from fastapi import APIRouter

from app.api.v1 import auth, chat, health, repositories
from app.integrations.github.routes import router as github_source_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(repositories.router)
api_router.include_router(chat.router)
api_router.include_router(github_source_router)

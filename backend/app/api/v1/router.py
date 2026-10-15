"""The versioned API router and public route-registration point."""

from fastapi import APIRouter

from app.api.v1 import auth, chat, events, github, health, repositories

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(auth.router)
api_router.include_router(repositories.router)
api_router.include_router(chat.router)
api_router.include_router(github.router)

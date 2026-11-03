"""The versioned API router and public route-registration point."""

from fastapi import APIRouter

from app.api.v1 import analysis, auth, chat, events, github, health, issues, repositories, tasks
from app.integrations.github.routes import router as github_source_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(auth.router)
api_router.include_router(repositories.router)
api_router.include_router(chat.router)
api_router.include_router(analysis.router)
api_router.include_router(github.router)
api_router.include_router(github_source_router)
api_router.include_router(issues.router)
api_router.include_router(tasks.router)
api_router.include_router(tasks.repo_tasks_router)

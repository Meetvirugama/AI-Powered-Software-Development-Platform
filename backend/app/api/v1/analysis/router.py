"""
Central Analysis API router combining explain, bugs, tests, review, and history sub-routers.
"""

from fastapi import APIRouter

from app.api.v1.analysis.bugs import router as bugs_router
from app.api.v1.analysis.explain import router as explain_router
from app.api.v1.analysis.history import router as history_router
from app.api.v1.analysis.review import router as review_router
from app.api.v1.analysis.tests import router as tests_router

analysis_router = APIRouter(tags=["analysis"])
analysis_router.include_router(explain_router)
analysis_router.include_router(bugs_router)
analysis_router.include_router(tests_router)
analysis_router.include_router(review_router)
analysis_router.include_router(history_router)

router = analysis_router


"""
Analysis module package initialization.
Re-exports the combined analysis router and common symbols for backward compatibility.
"""

from __future__ import annotations

from app.api.v1.analysis.bugs import detect_bugs
from app.api.v1.analysis.common import (
    ANALYSIS_ERROR_RESPONSES,
    AnalysisRunPersistenceProtocol,
    ErrorDetailSchema,
    ErrorResponseEnvelope,
    _coerce_run_summary,
    _get_service,
    _invoke_service_method,
    _owned_repository,
    _owned_repository_async,
    _request_user_id,
    _validate_and_normalize_code_target,
)
from app.api.v1.analysis.explain import explain_code
from app.api.v1.analysis.history import (
    get_analysis_run,
    get_analysis_runs_summary,
    list_analysis_runs,
)
from app.api.v1.analysis.review import review_code
from app.api.v1.analysis.router import analysis_router, router
from app.api.v1.analysis.tests import generate_tests
from app.repositories.repository_repository import RepositoryRepository

__all__ = [
    "ANALYSIS_ERROR_RESPONSES",
    "AnalysisRunPersistenceProtocol",
    "ErrorDetailSchema",
    "ErrorResponseEnvelope",
    "RepositoryRepository",
    "_coerce_run_summary",
    "_get_service",
    "_invoke_service_method",
    "_owned_repository",
    "_owned_repository_async",
    "_request_user_id",
    "_validate_and_normalize_code_target",
    "analysis_router",
    "detect_bugs",
    "explain_code",
    "generate_tests",
    "get_analysis_run",
    "get_analysis_runs_summary",
    "list_analysis_runs",
    "review_code",
    "router",
]


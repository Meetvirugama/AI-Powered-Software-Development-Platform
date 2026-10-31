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
    "router",
    "analysis_router",
    "explain_code",
    "detect_bugs",
    "generate_tests",
    "review_code",
    "list_analysis_runs",
    "get_analysis_runs_summary",
    "get_analysis_run",
    "_validate_and_normalize_code_target",
    "_owned_repository",
    "_request_user_id",
    "_get_service",
    "_invoke_service_method",
    "_coerce_run_summary",
    "ANALYSIS_ERROR_RESPONSES",
    "ErrorDetailSchema",
    "ErrorResponseEnvelope",
    "AnalysisRunPersistenceProtocol",
    "RepositoryRepository",
]


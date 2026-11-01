from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
import pytest

from app.api.v1.analysis import _validate_and_normalize_code_target
from app.api.v1.repositories import _get_counts_for_repos
from app.core.errors import APIError, ErrorCode
from app.models.repository_file import RepositoryFile
from app.schemas.analysis import AnalysisTarget, CodeReviewRequest, ExplainCodeRequest, ReviewTarget
from app.services.code_review_orchestrator import resolve_review_target_and_build_context
from app.services.explanation_orchestrator import resolve_target_and_build_context


def test_validate_and_normalize_code_target_raises_503_on_db_failure():
    repo_id = uuid4()
    target = AnalysisTarget(path="src/main.py")

    db = MagicMock()
    db.query.side_effect = Exception("PostgreSQL connection timeout")

    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, target, db)

    err = exc_info.value
    assert err.status_code == 503
    assert err.code == ErrorCode.SERVICE_UNAVAILABLE
    assert err.retryable is True


def test_validate_and_normalize_code_target_raises_409_when_repo_syncing():
    repo_id = uuid4()
    target = AnalysisTarget(path="src/main.py")

    db = MagicMock()
    # No files exist
    db.query.return_value.filter.return_value.first.return_value = None

    repo = SimpleNamespace(sync_status="SYNCING")

    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, target, db, repo=repo)

    err = exc_info.value
    assert err.status_code == 409
    assert err.code == ErrorCode.CONFLICT
    assert "indexing is in progress" in err.message


def test_validate_and_normalize_code_target_raises_404_when_repo_synced_empty():
    repo_id = uuid4()
    target = AnalysisTarget(path="src/main.py")

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    repo = SimpleNamespace(sync_status="SYNCED")

    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, target, db, repo=repo)

    err = exc_info.value
    assert err.status_code == 404
    assert err.code == ErrorCode.FILE_NOT_FOUND


def test_validate_and_normalize_code_target_raises_404_when_file_missing():
    repo_id = uuid4()
    target = AnalysisTarget(path="src/missing.py")

    db = MagicMock()
    # repo_has_files is True, file_record is None
    first_mock = MagicMock()
    first_mock.id = uuid4()
    db.query.return_value.filter.return_value.first.side_effect = [first_mock, None]

    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, target, db)

    err = exc_info.value
    assert err.status_code == 404
    assert err.code == ErrorCode.FILE_NOT_FOUND


def test_validate_and_normalize_code_target_raises_413_on_oversized_file():
    repo_id = uuid4()
    target = AnalysisTarget(path="src/big.py")

    file_rec = SimpleNamespace(
        id=uuid4(),
        path="src/big.py",
        size_bytes=2 * 1024 * 1024,  # 2MB > 1MB limit
        line_count=5000,
    )

    db = MagicMock()
    first_mock = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [first_mock, file_rec]

    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, target, db)

    err = exc_info.value
    assert err.status_code == 413
    assert err.code == ErrorCode.PAYLOAD_TOO_LARGE


def test_validate_and_normalize_code_target_line_bounds():
    repo_id = uuid4()
    file_rec = SimpleNamespace(
        id=uuid4(),
        path="src/bounds.py",
        size_bytes=1000,
        line_count=50,
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [MagicMock(), file_rec]

    target = AnalysisTarget(path="src/bounds.py", start_line=60)
    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, target, db)

    err = exc_info.value
    assert err.status_code == 400
    assert err.code == ErrorCode.INVALID_REQUEST
    assert "start_line (60) exceeds file line count (50)" in err.message


def test_validate_and_normalize_code_target_path_traversal():
    repo_id = uuid4()
    db = MagicMock()
    with pytest.raises(APIError) as exc_info:
        _validate_and_normalize_code_target(repo_id, AnalysisTarget(path="../../etc/passwd"), db)

    assert exc_info.value.status_code == 400


def test_resolve_target_and_build_context_fails_closed_on_db_outage():
    repo_id = uuid4()
    repo = SimpleNamespace(default_branch="main", sync_status="SYNCED")
    payload = ExplainCodeRequest(target=AnalysisTarget(path="src/main.py"))

    db = MagicMock()
    db.query.side_effect = Exception("Database socket disconnected")

    with pytest.raises(APIError) as exc_info:
        resolve_target_and_build_context(repo_id, repo, payload, db)

    err = exc_info.value
    assert err.status_code == 503
    assert err.code == ErrorCode.SERVICE_UNAVAILABLE
    assert err.retryable is True


@pytest.mark.asyncio
async def test_resolve_review_target_fails_closed_on_db_outage():
    repo_id = uuid4()
    repo = SimpleNamespace(default_branch="main", sync_status="SYNCED")
    payload = CodeReviewRequest(target=ReviewTarget(type="file", path="src/main.py"))

    db = MagicMock()
    db.query.side_effect = Exception("DB connection timeout")

    with pytest.raises(APIError) as exc_info:
        await resolve_review_target_and_build_context(
            repository_id=repo_id,
            repo=repo,
            payload=payload,
            user_id=uuid4(),
            db=db,
        )

    err = exc_info.value
    assert err.status_code == 503
    assert err.code == ErrorCode.SERVICE_UNAVAILABLE
    assert err.retryable is True


def test_get_counts_for_repos_fails_closed_on_db_outage():
    repo_id = uuid4()
    db = MagicMock()
    db.query.side_effect = Exception("Deadlock detected in DB")

    with pytest.raises(APIError) as exc_info:
        _get_counts_for_repos([repo_id], db)

    err = exc_info.value
    assert err.status_code == 503
    assert err.code == ErrorCode.SERVICE_UNAVAILABLE
    assert err.retryable is True


def test_vector_to_pg_literal_rejects_non_finite_and_mismatched_dimensions():
    import math
    from ai.retrieval.vector import _vec_to_pg_literal

    # Normal valid vector
    lit = _vec_to_pg_literal([0.1, 0.2, 0.3], expected_dim=3)
    assert lit == "[0.1,0.2,0.3]"

    # Dimension mismatch
    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        _vec_to_pg_literal([0.1, 0.2], expected_dim=3)

    # Empty vector
    with pytest.raises(ValueError, match="Vector cannot be empty"):
        _vec_to_pg_literal([])

    # NaN rejected
    with pytest.raises(ValueError, match="non-finite value"):
        _vec_to_pg_literal([0.1, float("nan"), 0.3])

    # Infinity rejected
    with pytest.raises(ValueError, match="non-finite value"):
        _vec_to_pg_literal([0.1, float("inf"), 0.3])


def test_code_chunk_model_rejects_non_finite_and_mismatched_embeddings():
    from app.models.code_chunk import CodeChunk

    # Valid 768 vector
    chunk = CodeChunk(embedding=[0.0] * 768)
    assert len(chunk.embedding) == 768

    # Mismatched dimension (e.g. 512 != 768)
    with pytest.raises(ValueError, match="CodeChunk embedding dimension mismatch"):
        CodeChunk(embedding=[0.0] * 512)

    # Non-finite value in vector
    with pytest.raises(ValueError, match="non-finite value"):
        bad_vec = [0.0] * 768
        bad_vec[5] = float("nan")
        CodeChunk(embedding=bad_vec)


def test_init_rag_pipeline_rejects_mismatched_embedding_dimensions(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from app.main import init_rag_pipeline

    test_app = FastAPI()
    test_app.state.service_readiness = {}

    monkeypatch.setattr("app.main.settings.embedding_dimensions", 1536)
    ok = init_rag_pipeline(test_app)
    assert ok is False
    assert test_app.state.service_readiness["rag_pipeline"] is False
    assert test_app.state.rag_pipeline is None

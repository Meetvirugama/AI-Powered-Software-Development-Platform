"""Regression tests for the Module 3 (GitHub & repository management) and Module 4
(repository intelligence) audit fixes.

Covers:
- GET /repositories exposes the true total in X-Total-Count (dashboard pagination).
- Sync jobs record stage / failure reason and are readable via /sync-jobs.
- Repository metrics endpoint (languages, symbols by kind, top symbols).
- Symbol listing filters.
- Dot-file paths (".github/...") are no longer mangled by path normalisation.
- FileWalker: secret files skipped, nested .gitignore honoured, language + category set.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.sync_job import SyncJob, SyncJobStage, SyncJobStatus
from app.models.user import User
from app.repositories.repository_repository import RepositoryRepository, normalize_repo_path
from scanner.walker import FileWalker, classify_file, is_secret_file


def _seed_user_with_repos(db_session, count: int = 1):
    user = User(id=uuid.uuid4(), github_id=f"gh_{uuid.uuid4().hex[:8]}", login=f"m3_{uuid.uuid4().hex[:6]}")
    db_session.add(user)
    db_session.flush()
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=str(uuid.uuid4().int % 10**9),
        account_login=user.login,
        permissions={},
    )
    db_session.add(inst)
    db_session.flush()
    repos = []
    for i in range(count):
        repo = Repository(
            id=uuid.uuid4(),
            user_id=user.id,
            installation_id=inst.id,
            github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
            owner=user.login,
            name=f"repo{i}",
            default_branch="main",
        )
        db_session.add(repo)
        repos.append(repo)
    db_session.commit()
    token, _ = create_access_token(str(user.id))
    return user, repos, {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Module 3
# ---------------------------------------------------------------------------

def test_list_repositories_reports_true_total_in_header(client: TestClient, db_session) -> None:
    _, _, headers = _seed_user_with_repos(db_session, count=7)
    resp = client.get("/api/v1/repositories?page=1&page_size=6", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 6
    assert resp.headers["x-total-count"] == "7"

    page2 = client.get("/api/v1/repositories?page=2&page_size=6", headers=headers)
    assert len(page2.json()) == 1


def test_sync_jobs_endpoint_exposes_stage_and_failure_reason(client: TestClient, db_session) -> None:
    user, (repo,), headers = _seed_user_with_repos(db_session)
    started = datetime.now(timezone.utc) - timedelta(seconds=30)
    job = SyncJob(
        repository_id=repo.id,
        user_id=user.id,
        status=SyncJobStatus.FAILED,
        stage=SyncJobStage.FAILED.value,
        error_message="RuntimeError: clone failed",
        started_at=started,
        finished_at=started + timedelta(seconds=12),
    )
    repo.sync_status = SyncStatus.FAILED
    db_session.add(job)
    db_session.commit()

    listing = client.get(f"/api/v1/repositories/{repo.id}/sync-jobs", headers=headers)
    assert listing.status_code == 200
    latest = listing.json()[0]
    assert latest["status"] == "FAILED"
    assert latest["error_message"] == "RuntimeError: clone failed"
    assert latest["duration_seconds"] == 12

    detail = client.get(f"/api/v1/repositories/{repo.id}/sync-jobs/{job.id}", headers=headers)
    assert detail.status_code == 200

    # The failure reason is surfaced on the repository itself for the dashboard card.
    repo_resp = client.get(f"/api/v1/repositories/{repo.id}", headers=headers)
    assert repo_resp.json()["last_sync_error"] == "RuntimeError: clone failed"


def test_sync_jobs_are_tenant_isolated(client: TestClient, db_session) -> None:
    _, (repo,), _ = _seed_user_with_repos(db_session)
    _, _, other_headers = _seed_user_with_repos(db_session)
    resp = client.get(f"/api/v1/repositories/{repo.id}/sync-jobs", headers=other_headers)
    assert resp.status_code == 404


def test_metrics_and_symbol_filters(client: TestClient, db_session) -> None:
    _, (repo,), headers = _seed_user_with_repos(db_session)
    py_file = RepositoryFile(
        id=uuid.uuid4(), repository_id=repo.id, path="src/app.py", language="Python",
        size_bytes=100, line_count=40, content_hash="h1",
    )
    md_file = RepositoryFile(
        id=uuid.uuid4(), repository_id=repo.id, path="README.md", language=None,
        size_bytes=10, line_count=3, content_hash="h2",
    )
    db_session.add_all([py_file, md_file])
    db_session.flush()
    db_session.add_all(
        [
            CodeSymbol(id=uuid.uuid4(), file_id=py_file.id, repository_id=repo.id, name="main",
                       kind="function", start_line=1, end_line=5, importance_score=0.9),
            CodeSymbol(id=uuid.uuid4(), file_id=py_file.id, repository_id=repo.id, name="Service",
                       kind="class", start_line=6, end_line=40, importance_score=0.4),
        ]
    )
    db_session.commit()

    metrics = client.get(f"/api/v1/repositories/{repo.id}/metrics", headers=headers)
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["file_count"] == 2
    assert body["total_lines"] == 43
    assert body["symbols_by_kind"] == {"function": 1, "class": 1}
    assert body["languages"][0]["language"] == "Python"
    assert body["top_symbols"][0]["name"] == "main"

    only_classes = client.get(f"/api/v1/repositories/{repo.id}/symbols?kind=class", headers=headers)
    assert [s["name"] for s in only_classes.json()["items"]] == ["Service"]
    by_name = client.get(f"/api/v1/repositories/{repo.id}/symbols?q=mai", headers=headers)
    assert [s["name"] for s in by_name.json()["items"]] == ["main"]


def test_dot_file_paths_are_not_mangled(db_session) -> None:
    assert normalize_repo_path(".github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert normalize_repo_path("./src/app.py") == "src/app.py"

    _, (repo,), _ = _seed_user_with_repos(db_session)
    db_session.add(
        RepositoryFile(
            id=uuid.uuid4(), repository_id=repo.id, path=".github/workflows/ci.yml", language=None,
            size_bytes=10, line_count=2, content_hash="h",
        )
    )
    db_session.commit()
    found = RepositoryRepository(db_session).get_file_by_path(repo.id, ".github/workflows/ci.yml")
    assert found is not None


def test_file_path_filter_treats_underscore_literally(db_session) -> None:
    _, (repo,), _ = _seed_user_with_repos(db_session)
    for path in ("my_mod.py", "myXmod.py"):
        db_session.add(
            RepositoryFile(
                id=uuid.uuid4(), repository_id=repo.id, path=path, language="Python",
                size_bytes=1, line_count=1, content_hash=path,
            )
        )
    db_session.commit()
    files, total = RepositoryRepository(db_session).list_files(repo.id, 0, 50, path="my_mod")
    assert total == 1 and files[0].path == "my_mod.py"


# ---------------------------------------------------------------------------
# Module 4
# ---------------------------------------------------------------------------

def _write(root, rel: str, content: str = "x = 1\n") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_walker_skips_secret_files_but_keeps_templates(tmp_path) -> None:
    _write(tmp_path, ".env", "API_KEY=real")
    _write(tmp_path, ".env.production", "API_KEY=real")
    _write(tmp_path, ".env.example", "API_KEY=")
    _write(tmp_path, "certs/server.pem", "-----BEGIN PRIVATE KEY-----")
    _write(tmp_path, "src/app.py")
    paths = {f.path for f in FileWalker().walk(str(tmp_path))}
    assert paths == {".env.example", "src/app.py"}
    assert is_secret_file("id_rsa") and not is_secret_file("settings.py")


def test_walker_honours_nested_gitignore_and_prunes_dirs(tmp_path) -> None:
    _write(tmp_path, ".gitignore", "logs/\n")
    _write(tmp_path, "logs/run.py")
    _write(tmp_path, "pkg/.gitignore", "generated/\n*.tmp.py\n")
    _write(tmp_path, "pkg/generated/out.py")
    _write(tmp_path, "pkg/scratch.tmp.py")
    _write(tmp_path, "pkg/core.py")
    _write(tmp_path, "other/generated/keep.py")  # nested rule must not leak outside pkg/
    paths = {f.path for f in FileWalker().walk(str(tmp_path))}
    assert "pkg/core.py" in paths and "other/generated/keep.py" in paths
    assert not paths & {"logs/run.py", "pkg/generated/out.py", "pkg/scratch.tmp.py"}


def test_walker_sets_language_and_category(tmp_path) -> None:
    _write(tmp_path, "src/app.py")
    _write(tmp_path, "tests/test_app.py")
    _write(tmp_path, "README.md", "# hi")
    _write(tmp_path, "pyproject.toml", "[project]")
    by_path = {f.path: f for f in FileWalker().walk(str(tmp_path))}
    assert by_path["src/app.py"].language == "Python"
    assert by_path["src/app.py"].category == "source"
    assert by_path["tests/test_app.py"].category == "test"
    assert by_path["README.md"].category == "docs"
    assert by_path["pyproject.toml"].category == "build"
    assert classify_file(".github/workflows/ci.yml", "unknown") == "build"

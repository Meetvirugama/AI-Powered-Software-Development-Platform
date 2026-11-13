"""Tests for domain-specific repository aggregates and PostgreSQL/pgvector persistence (Issue #213 / F32)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ai.retrieval.lexical import LexicalRetriever
from ai.retrieval.vector import VectorRetriever
from app.core.config import get_settings
from app.core.database import Base, _resolve_async_database_url, normalize_sync_database_url
from app.models import (
    CodeChunk,
    CodeSymbol,
    GitHubInstallation,
    MemoryType,
    Repository,
    RepositoryFile,
    User,
)
from app.models.task import (
    ExecutionStatus,
    TaskSourceType,
    TaskStatus,
    TestRunStatus,
    VerificationStatus,
)
from app.repositories import (
    AnalysisRunRepository,
    InvalidStateTransitionError,
    PlanNotFoundError,
    TaskApprovalRepository,
    TaskExecutionRepository,
    TaskNotFoundError,
    TaskPlanRepository,
    TaskPublicationRepository,
    TaskRepository,
)
from app.repositories.analysis import (
    AnalysisRetentionRepository,
    BugScanRunRepository,
    ExplanationRunRepository,
    ReviewRunRepository,
    TestGenerationRunRepository,
)
from app.repositories.memory_repository import MemoryRepository
from app.repositories.task_repository import VALID_TRANSITIONS, scrub_sensitive_data, scrub_sensitive_text


def _seed_user_and_repo(db_session: Session, suffix: str | None = None) -> tuple[User, Repository]:
    tag = suffix or uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{tag}",
        login=f"user_{tag}",
        email=f"user_{tag}@example.com",
    )
    db_session.add(user)
    db_session.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{tag}",
        account_login=user.login,
        permissions={},
    )
    db_session.add(installation)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{tag}",
        owner=user.login,
        name=f"repo-{tag}",
        default_branch="main",
    )
    db_session.add(repo)
    db_session.flush()
    return user, repo


def _get_postgres_sync_url() -> str | None:
    raw_url = os.environ.get("TEST_DATABASE_URL") or get_settings().database_url
    norm = normalize_sync_database_url(raw_url)
    if norm.startswith("postgresql"):
        return norm
    return None


class TestRepositoryModularityAndBackwardsCompatibility:
    """Verify repository aggregate decomposition maintains backward compatibility and concise modules."""

    def test_repositories_decomposed_below_size_budget(self) -> None:
        repos_dir = Path(__file__).resolve().parent.parent / "app" / "repositories"
        task_facade = repos_dir / "task_repository.py"
        analysis_facade = repos_dir / "analysis_run_repository.py"

        assert len(task_facade.read_text(encoding="utf-8").splitlines()) < 150
        assert len(analysis_facade.read_text(encoding="utf-8").splitlines()) < 150

        for subdir in ("task", "analysis"):
            pkg = repos_dir / subdir
            assert pkg.is_dir()
            py_files = list(pkg.glob("*.py"))
            assert len(py_files) >= 5
            for py_file in py_files:
                loc = len(py_file.read_text(encoding="utf-8").splitlines())
                assert loc < 1000, f"{py_file.name} exceeds 1000 LOC ({loc} lines)"

    def test_task_repository_backwards_compatible_exports_and_facades(self, db_session: Session) -> None:
        repo = TaskRepository(db_session)

        assert isinstance(repo.plans, TaskPlanRepository)
        assert isinstance(repo.approvals, TaskApprovalRepository)
        assert isinstance(repo.executions, TaskExecutionRepository)
        assert isinstance(repo.publication, TaskPublicationRepository)

        # Standalone aggregates operate directly on the shared Session
        assert repo.plans.session is db_session
        assert repo.approvals.session is db_session
        assert repo.executions.session is db_session
        assert repo.publication.session is db_session

        # Verify preserved exports and sanitizers
        assert TaskStatus.CREATED in VALID_TRANSITIONS
        assert issubclass(InvalidStateTransitionError, ValueError)
        assert issubclass(TaskNotFoundError, LookupError)
        assert issubclass(PlanNotFoundError, LookupError)
        assert "[REDACTED]" in (scrub_sensitive_text("token=ghp_123456789012345678901234567890123456") or "")
        scrubbed = scrub_sensitive_data({"uri": "postgresql://admin:SecretPass99!@db.local:5432/app"})
        assert "SecretPass99" not in scrubbed["uri"]


class TestTaskDomainAggregatesLifecycle:
    """End-to-end persistence lifecycle across plans, approvals, executions, and publication aggregates."""

    def test_end_to_end_lifecycle_through_domain_aggregates(self, db_session: Session) -> None:
        user, repository = _seed_user_and_repo(db_session, "agg-task")
        tasks = TaskRepository(db_session)

        task = tasks.create_task(
            repository_id=repository.id,
            user_id=user.id,
            title="Refactor persistence layer",
            description="Split monolithic repository cleanly",
            source_type=TaskSourceType.DIRECT,
            base_revision="abc1234",
        )

        # 1. Plans aggregate (standalone & property)
        plan_repo = TaskPlanRepository(db_session)
        plan = plan_repo.save_plan(
            task_id=task.id,
            repository_id=repository.id,
            summary="Modularize plans, approvals, executions, and publication",
            steps=[{"step_id": 1, "title": "Extract aggregates", "description": "Create domain packages"}],
            base_revision="abc1234",
            expected_files=["backend/app/repositories/task_repository.py"],
            tests_to_run=["pytest backend/tests/test_repository_aggregates_and_postgres.py"],
            validation_strategy="Run repository regression tests",
        )
        assert plan.version == 1
        assert tasks.plans.get_latest_plan(task.id).id == plan.id
        assert len(tasks.plans.list_plans(task.id, repository.id)) == 1

        # 2. Approvals aggregate
        approval = tasks.approvals.approve_plan(
            task_id=task.id,
            repository_id=repository.id,
            plan_version=1,
            user_id=user.id,
            feedback="LGTM",
        )
        assert approval.plan_version == 1
        verified_plan = TaskApprovalRepository(db_session).verify_execution_approval_gate(task)
        assert verified_plan.id == plan.id
        assert len(tasks.approvals.list_approvals(task.id, repository.id)) == 1

        # 3. Executions aggregate
        exec_repo = tasks.executions
        execution = exec_repo.record_execution_start(
            task_id=task.id,
            repository_id=repository.id,
            worker_id="worker-agg-1",
            attempt_number=1,
        )
        assert execution.status == ExecutionStatus.RUNNING.value

        checkpoint = exec_repo.save_checkpoint(
            task_id=task.id,
            repository_id=repository.id,
            step_name="TEST_EXECUTION",
            state_data={"step": 1, "secret": "sk-proj-1234567890abcdefghij1234"},
        )
        assert checkpoint.state_data["secret"] == "[REDACTED]"
        assert exec_repo.get_latest_checkpoint(task.id, repository.id).id == checkpoint.id

        test_run = exec_repo.record_test_run(
            task_id=task.id,
            repository_id=repository.id,
            command="pytest backend/tests/test_repository_aggregates_and_postgres.py",
            status=TestRunStatus.PASSED,
            exit_code=0,
            tests_total=4,
            tests_passed=4,
            tests_failed=0,
            duration_ms=250,
            sanitized_output="4 passed",
        )
        assert test_run.status == TestRunStatus.PASSED.value
        assert len(exec_repo.list_test_runs(task.id)) == 1

        ver = exec_repo.record_verification_result(
            task_id=task.id,
            repository_id=repository.id,
            status=VerificationStatus.PASSED,
            verified_revision="def5678",
            checks=[{"name": "tests", "passed": True}, {"name": "security", "passed": True}],
            blocking_findings=[],
        )
        assert ver.verified_revision == "def5678"
        finished_exec = exec_repo.record_execution_finish(
            task_id=task.id,
            repository_id=repository.id,
            execution_id=execution.id,
            status=ExecutionStatus.COMPLETED,
        )
        assert finished_exec.status == ExecutionStatus.COMPLETED.value

        # 4. Publication aggregate
        pub_repo = tasks.publication
        auth_task = pub_repo.authorize_publication(
            task_id=task.id,
            repository_id=repository.id,
            head_sha="def5678",
            user_id=user.id,
            notes="Verified on def5678",
        )
        assert auth_task.status == TaskStatus.PUBLISHING.value

        pr = TaskPublicationRepository(db_session).record_pull_request(
            task_id=task.id,
            repository_id=repository.id,
            pr_url="https://github.com/example/repo/pull/42",
            base_branch="main",
            head_branch="ai/task-agg",
            head_sha="def5678",
            title="Refactor task repository into aggregates",
            pr_number=42,
            is_draft=True,
        )
        assert pr.pr_number == 42
        traceability = pub_repo.get_task_traceability(task.id, repository.id)
        assert traceability["pull_request"]["pr_number"] == 42
        assert traceability["latest_plan"]["version"] == 1
        assert traceability["latest_verification"]["verified_revision"] == "def5678"


class TestAnalysisDomainAggregatesLifecycle:
    """Verify AnalysisRunRepository standalone aggregates and property accessors."""

    def test_analysis_domain_aggregates_and_aliases(self, db_session: Session) -> None:
        user, repository = _seed_user_and_repo(db_session, "agg-analysis")
        analysis = AnalysisRunRepository(db_session)

        assert isinstance(analysis.explanations, ExplanationRunRepository)
        assert isinstance(analysis.bug_scans, BugScanRunRepository)
        assert isinstance(analysis.test_generation, TestGenerationRunRepository)
        assert isinstance(analysis.reviews, ReviewRunRepository)
        assert isinstance(analysis.retention, AnalysisRetentionRepository)

        exp_run = analysis.explanations.save_explanation_run(
            repository_id=repository.id,
            user_id=user.id,
            target_file="backend/app/main.py",
            explanation_summary="Application entrypoint",
            explanation_payload={"overview": "FastAPI setup"},
        )
        assert analysis.get_run(exp_run.id).id == exp_run.id

        bug_run = analysis.bug_scans.save_bug_scan_run(
            repository_id=repository.id,
            user_id=user.id,
            target_file="backend/app/core/database.py",
            findings=[
                {
                    "title": "Unbounded timeout",
                    "severity": "MEDIUM",
                    "category": "reliability",
                    "file_path": "backend/app/core/database.py",
                }
            ],
        )
        items, total = analysis.list_runs(repository.id)
        assert total == 2
        assert {r.id for r in items} == {exp_run.id, bug_run.id}

        metrics = analysis.retention.get_retention_metrics(repository.id)
        assert metrics["total_runs"] == 2
        deleted = analysis.delete_repository_runs(repository.id)
        assert deleted == 2


class TestPostgresPgvectorAndFullTextIntegration:
    """Live PostgreSQL + pgvector + GIN FTS integration tests (executed in CI against pgvector/pgvector:pg16)."""

    @pytest.fixture
    def pg_sync_url(self) -> str:
        url = _get_postgres_sync_url()
        if not url:
            pytest.skip("PostgreSQL TEST_DATABASE_URL not configured (SQLite active)")
        try:
            eng = create_engine(url, connect_args={"connect_timeout": 2})
            with eng.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            Base.metadata.create_all(eng)
            eng.dispose()
        except Exception as exc:
            pytest.skip(f"PostgreSQL service unreachable: {exc}")
        return url

    def test_pgvector_memory_semantic_search_with_enum_filters_and_isolation(self, pg_sync_url: str) -> None:
        engine = create_engine(pg_sync_url)
        conn = engine.connect()
        tx = conn.begin()
        session = Session(bind=conn)
        try:
            _, repo_a = _seed_user_and_repo(session, f"pgmem_a_{uuid.uuid4().hex[:6]}")
            _, repo_b = _seed_user_and_repo(session, f"pgmem_b_{uuid.uuid4().hex[:6]}")

            vec_match = [1.0] + [0.0] * 767
            vec_other = [0.0, 1.0] + [0.0] * 766

            mem_repo = MemoryRepository(session)
            e_match = mem_repo.create_entry(
                repository_id=repo_a.id,
                type_=MemoryType.decision,
                content="Use pgvector HNSW index for memory semantic lookup.",
                embedding=vec_match,
            )
            mem_repo.create_entry(
                repository_id=repo_a.id,
                type_=MemoryType.rule,
                content="Unrelated rule vector.",
                embedding=vec_other,
            )
            mem_repo.create_entry(
                repository_id=repo_b.id,
                type_=MemoryType.decision,
                content="Tenant B secret decision.",
                embedding=vec_match,
            )

            results = mem_repo.semantic_search_entries(
                repository_id=repo_a.id,
                query_vector=vec_match,
                type_=MemoryType.decision,
                min_similarity=0.9,
            )
            assert len(results) == 1
            entry, similarity = results[0]
            assert entry.id == e_match.id
            assert similarity > 0.99
        finally:
            session.close()
            if tx.is_active:
                tx.rollback()
            conn.close()
            engine.dispose()

    @pytest.mark.asyncio
    async def test_pgvector_code_chunk_vector_and_lexical_retrievers(self, pg_sync_url: str) -> None:
        engine = create_engine(pg_sync_url)
        repo_ids_to_clean: list[uuid.UUID] = []
        with Session(engine) as session:
            _, repo_a = _seed_user_and_repo(session, f"pgret_a_{uuid.uuid4().hex[:6]}")
            _, repo_b = _seed_user_and_repo(session, f"pgret_b_{uuid.uuid4().hex[:6]}")
            repo_ids_to_clean.extend([repo_a.id, repo_b.id])

            file_a = RepositoryFile(
                id=uuid.uuid4(),
                repository_id=repo_a.id,
                path="backend/app/auth/jwt_handler.py",
                language="python",
                size_bytes=256,
                line_count=12,
                content_hash="hash_pg_a",
            )
            file_b = RepositoryFile(
                id=uuid.uuid4(),
                repository_id=repo_b.id,
                path="backend/app/other.py",
                language="python",
                size_bytes=128,
                line_count=5,
                content_hash="hash_pg_b",
            )
            session.add_all([file_a, file_b])
            session.flush()

            sym_a = CodeSymbol(
                id=uuid.uuid4(),
                file_id=file_a.id,
                repository_id=repo_a.id,
                name="verify_jwt_signature",
                kind="function",
                start_line=1,
                end_line=10,
                importance_score=0.92,
            )
            session.add(sym_a)
            session.flush()

            vec_query = [0.8, 0.6] + [0.0] * 766
            vec_far = [0.0, 0.0, 1.0] + [0.0] * 765

            chunk_match = CodeChunk(
                id=uuid.uuid4(),
                repository_id=repo_a.id,
                file_id=file_a.id,
                symbol_id=sym_a.id,
                content="def verify_jwt_signature(token: str) -> dict: return decode(token)",
                code_search_text="verify jwt signature token decode verify_jwt_signature",
                token_count=16,
                embedding=vec_query,
                start_line=1,
                end_line=10,
                content_hash="chunk_match_hash",
                chunk_metadata={"file_path": "backend/app/auth/jwt_handler.py"},
            )
            chunk_far = CodeChunk(
                id=uuid.uuid4(),
                repository_id=repo_a.id,
                file_id=file_a.id,
                symbol_id=None,
                content="def render_dashboard_chart(): return []",
                code_search_text="render dashboard chart render_dashboard_chart",
                token_count=10,
                embedding=vec_far,
                start_line=11,
                end_line=12,
                content_hash="chunk_far_hash",
                chunk_metadata={"file_path": "backend/app/auth/jwt_handler.py"},
            )
            chunk_other_tenant = CodeChunk(
                id=uuid.uuid4(),
                repository_id=repo_b.id,
                file_id=file_b.id,
                symbol_id=None,
                content="def verify_jwt_signature(): pass",
                code_search_text="verify jwt signature verify_jwt_signature",
                token_count=8,
                embedding=vec_query,
                start_line=1,
                end_line=5,
                content_hash="chunk_other_hash",
                chunk_metadata={"file_path": "backend/app/other.py"},
            )
            session.add_all([chunk_match, chunk_far, chunk_other_tenant])
            session.commit()

        class _StubEmbeddingService:
            dimensions = 768

            async def embed(self, text: str) -> list[float]:
                return vec_query

        async_url = _resolve_async_database_url(pg_sync_url)
        async_engine = create_async_engine(async_url)
        session_maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with session_maker() as async_sess:
                vec_retriever = VectorRetriever(db=async_sess, embedding_service=_StubEmbeddingService())  # type: ignore[arg-type]
                vec_hits = await vec_retriever.retrieve("verify jwt signature", repository_id=repo_a.id, top_k=5)
                assert len(vec_hits) == 2
                assert vec_hits[0].id == chunk_match.id
                assert vec_hits[0].score > 0.99
                assert vec_hits[0].importance_score == pytest.approx(0.92)
                assert all(hit.repository_id == repo_a.id for hit in vec_hits)

                lex_retriever = LexicalRetriever(db=async_sess)
                lex_hits = await lex_retriever.retrieve("verify_jwt_signature", repository_id=repo_a.id, top_k=5)
                assert len(lex_hits) == 1
                assert lex_hits[0].id == chunk_match.id
                assert lex_hits[0].file_path == "backend/app/auth/jwt_handler.py"
        finally:
            await async_engine.dispose()
            with engine.begin() as conn:
                for rid in repo_ids_to_clean:
                    conn.execute(text("DELETE FROM repositories WHERE id = CAST(:rid AS uuid)"), {"rid": str(rid)})
            engine.dispose()

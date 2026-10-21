"""Full System Integration Test Suite.
Validates the end-to-end integration across all architecture tiers:
1. GitHub Sync, AST parsing, Symbol extraction, and Chunker with 768-d embeddings in real DB.
2. Multi-repository isolation and cross-repository leak prevention at DB and grounding levels.
3. Gemini Embedding provider verification with 768 dimensions and controlled transport.
4. Hybrid retrieval flow: Vector similarity + Lexical search + RRF Fusion + CrossEncoder reranking.
5. Context and Prompt builders respecting token budgets and prompt injection separation.
6. End-to-end RAG pipeline with LLM generation and authoritative database citation validation.
7. GroundingValidator security: path traversal, line bounds, DB error fail-closed behavior.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from ai.context.builder import ContextBuilder
from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
from ai.llm.schemas import LLMRequest, LLMResponse, Message
from ai.pipeline import RAGPipeline
from ai.retrieval.base import CodeChunk as RetrievedChunk
from ai.retrieval.fusion import RRFFusion
from ai.retrieval.hybrid import HybridRetriever
from ai.retrieval.reranker import CrossEncoderReranker
from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer, SourceReference
from ai.schemas.prompt_builder import PromptBuilder
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User
from backend.indexer.chunker import SymbolChunker
from backend.scanner.detector import LanguageDetector
from backend.scanner.extractor import SymbolExtractor
from backend.scanner.walker import FileWalker

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EMBEDDING_DIM = 768


# ---------------------------------------------------------------------------
# Helper: Synchronize and index a local fixture repository into the real DB
# ---------------------------------------------------------------------------
def _sync_fixture_repo_to_db(
    db: Session,
    repo: Repository,
    fixture_folder: str,
    synthetic_embedding_seed: float = 0.05,
) -> tuple[list[RepositoryFile], list[CodeSymbol], list[CodeChunk]]:
    fixture_path = FIXTURES_DIR / fixture_folder
    assert fixture_path.exists(), f"Fixture directory {fixture_path} not found"

    walker = FileWalker()
    detector = LanguageDetector()
    extractor = SymbolExtractor()
    chunker = SymbolChunker()

    walked_files = walker.walk(str(fixture_path))
    persisted_files: list[RepositoryFile] = []
    persisted_symbols: list[CodeSymbol] = []
    persisted_chunks: list[CodeChunk] = []

    for file_info in walked_files:
        file_info.language = detector.detect(file_info)
        full_path = fixture_path / file_info.path
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        line_count = len(content.splitlines())
        repo_file = RepositoryFile(
            id=uuid4(),
            repository_id=repo.id,
            path=file_info.path.replace(os.sep, "/"),
            language=file_info.language,
            size_bytes=file_info.size_bytes,
            line_count=line_count,
            content_hash=f"hash_{file_info.path}",
        )
        db.add(repo_file)
        persisted_files.append(repo_file)

        symbols = extractor.extract(file_info, content, file_id=repo_file.id)
        for sym in symbols:
            code_sym = CodeSymbol(
                id=sym.id,
                file_id=repo_file.id,
                repository_id=repo.id,
                name=sym.name,
                kind=sym.kind,
                start_line=sym.start_line,
                end_line=sym.end_line,
                signature=sym.signature,
                parent_id=sym.parent_id,
            )
            db.add(code_sym)
            persisted_symbols.append(code_sym)

        if symbols:
            chunks = chunker.chunk_symbols(repo.id, repo_file.id, symbols, content, file_info.language)
            for idx, ch in enumerate(chunks):
                # Real 768-dimensional embedding vector
                emb = [synthetic_embedding_seed + (0.001 * (idx % 10))] * EMBEDDING_DIM
                db_chunk = CodeChunk(
                    id=uuid4(),
                    repository_id=repo.id,
                    file_id=repo_file.id,
                    symbol_id=ch.symbol_id,
                    content=ch.content,
                    token_count=ch.token_count,
                    embedding=emb,
                    start_line=ch.start_line,
                    end_line=ch.end_line,
                    content_hash=ch.content_hash,
                    chunk_metadata={"file_path": repo_file.path},
                )
                db.add(db_chunk)
                persisted_chunks.append(db_chunk)

    repo.sync_status = SyncStatus.SYNCED
    db.commit()
    return persisted_files, persisted_symbols, persisted_chunks


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestFullSystemIntegration:
    """Proves the integrated flow across Scanner, Indexer, DB, Retrieval, LLM, and Grounding."""

    def test_github_sync_scanner_indexer_real_db_768d_embedding(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """Verifies GitHub repository indexing creates valid 768-d chunks in real DB."""
        installation = GitHubInstallation(
            id=uuid4(),
            user_id=test_user.id,
            installation_id="gh-inst-integration-1",
            account_login=test_user.login,
            permissions={"contents": "read"},
        )
        db_session.add(installation)
        db_session.commit()

        repo = Repository(
            id=uuid4(),
            user_id=test_user.id,
            installation_id=installation.id,
            github_repo_id="gh-repo-py-sample",
            owner=test_user.login,
            name="python_sample",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        db_session.add(repo)
        db_session.commit()

        files, symbols, chunks = _sync_fixture_repo_to_db(db_session, repo, "python_sample")

        assert len(files) > 0
        assert len(symbols) > 0
        assert len(chunks) > 0
        assert repo.sync_status == SyncStatus.SYNCED

        # Verify all chunks in DB have exactly 768-d embedding
        db_chunks = db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).all()
        assert len(db_chunks) == len(chunks)
        for chunk in db_chunks:
            assert len(chunk.embedding) == 768

        # Verify line counts and file properties
        utils_file = db_session.query(RepositoryFile).filter(
            RepositoryFile.repository_id == repo.id,
            RepositoryFile.path == "utils.py",
        ).first()
        assert utils_file is not None
        assert utils_file.line_count > 0

        # Verify dimension mismatch guard: Inserting 1536-d chunk must raise ValueError
        with pytest.raises(ValueError, match="[eE]mbedding dimension mismatch"):
            invalid_chunk = CodeChunk(
                id=uuid4(),
                repository_id=repo.id,
                file_id=utils_file.id,
                content="invalid dimension chunk",
                token_count=10,
                embedding=[0.1] * 1536,
                start_line=1,
                end_line=2,
                content_hash="inv_hash",
            )
            db_session.add(invalid_chunk)
            db_session.flush()

    @pytest.mark.asyncio
    async def test_multi_repository_isolation_and_cross_repo_citation_rejection(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """Verifies strict isolation between repositories in database queries and grounding."""
        installation = GitHubInstallation(
            id=uuid4(),
            user_id=test_user.id,
            installation_id="gh-inst-isolation",
            account_login=test_user.login,
            permissions={"contents": "read"},
        )
        db_session.add(installation)
        db_session.commit()

        repo_a = Repository(
            id=uuid4(),
            user_id=test_user.id,
            installation_id=installation.id,
            github_repo_id="gh-repo-a",
            owner=test_user.login,
            name="repo_a_python",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        repo_b = Repository(
            id=uuid4(),
            user_id=test_user.id,
            installation_id=installation.id,
            github_repo_id="gh-repo-b",
            owner=test_user.login,
            name="repo_b_node",
            default_branch="main",
            language="JavaScript",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        db_session.add_all([repo_a, repo_b])
        db_session.commit()

        # Ingest both fixtures
        files_a, _, chunks_a = _sync_fixture_repo_to_db(db_session, repo_a, "python_sample")
        files_b, _, chunks_b = _sync_fixture_repo_to_db(db_session, repo_b, "nodejs_sample")

        # Database query isolation: Chunks for repo_a MUST NOT contain chunks of repo_b
        a_chunk_file_paths = [
            c.chunk_metadata["file_path"]
            for c in db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo_a.id).all()
        ]
        b_chunk_file_paths = [
            c.chunk_metadata["file_path"]
            for c in db_session.query(CodeChunk).filter(CodeChunk.repository_id == repo_b.id).all()
        ]

        assert "utils.py" in a_chunk_file_paths
        assert "server.js" not in a_chunk_file_paths
        assert "server.js" in b_chunk_file_paths
        assert "utils.py" not in b_chunk_file_paths

        # Grounding validation isolation:
        # If repo_a chat tries to cite server.js (which exists only in repo_b), it must be rejected!
        validator = GroundingValidator(db_session=db_session)
        adversarial_cross_repo_answer = RepositoryAnswer(
            answer="Here is the node server implementation.",
            sources=[
                SourceReference(file="server.js", start_line=1, end_line=10),
            ],
            confidence="high",
        )

        grounding_result = await validator.validate_answer(repo_a.id, adversarial_cross_repo_answer)
        assert len(grounding_result) == 1
        assert grounding_result[0].grounded is False
        assert grounding_result[0].reason == "file_not_found"

        # Valid citation in repo_a should be accepted
        valid_repo_a_answer = RepositoryAnswer(
            answer="Passwords are encrypted using SHA-256.",
            sources=[
                SourceReference(file="utils.py", start_line=1, end_line=5),
            ],
            confidence="high",
        )
        valid_result = await validator.validate_answer(repo_a.id, valid_repo_a_answer)
        assert len(valid_result) == 1
        assert valid_result[0].grounded is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_gemini_embedding_provider_real_dimensions_controlled_transport(self) -> None:
        """Verifies GeminiEmbeddingProvider generates 768-dimensional embeddings with controlled transport."""
        provider = GeminiEmbeddingProvider(
            api_keys=["gemini-integration-key-xyz"],
            dimensions=EMBEDDING_DIM,
        )

        # Mock Gemini Batch Embedding API endpoint with dynamic batch length handling
        dummy_vector_768 = [0.0123 * (i % 25) for i in range(EMBEDDING_DIM)]
        assert len(dummy_vector_768) == 768

        import json

        def _mock_gemini_api(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            count = len(body.get("requests", []))
            return httpx.Response(
                200,
                json={"embeddings": [{"values": dummy_vector_768} for _ in range(count)]},
            )

        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
        ).mock(side_effect=_mock_gemini_api)

        embeddings = await provider.embed_batch(["def hash_password(): pass", "def verify_token(): pass"])
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 768
        assert len(embeddings[1]) == 768

        query_emb = await provider.embed("where is password hashed?")
        assert len(query_emb) == 768

        await provider.aclose()

    @pytest.mark.asyncio
    async def test_hybrid_retriever_with_rrf_and_cross_encoder_reranking(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """Verifies Vector + Lexical retrieval fused via RRF and rescored by CrossEncoderReranker."""
        installation = GitHubInstallation(
            id=uuid4(),
            user_id=test_user.id,
            installation_id="gh-inst-hybrid",
            account_login=test_user.login,
            permissions={"contents": "read"},
        )
        db_session.add(installation)
        db_session.commit()

        repo = Repository(
            id=uuid4(),
            user_id=test_user.id,
            installation_id=installation.id,
            github_repo_id="gh-repo-hybrid",
            owner=test_user.login,
            name="python_sample",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        db_session.add(repo)
        db_session.commit()

        _files, _symbols, db_chunks = _sync_fixture_repo_to_db(db_session, repo, "python_sample")

        # Map db_chunks to RetrievedChunk
        retrieved_candidates = [
            RetrievedChunk(
                id=c.id,
                repository_id=repo.id,
                file_id=c.file_id,
                symbol_id=c.symbol_id,
                content=c.content,
                token_count=c.token_count,
                start_line=c.start_line,
                end_line=c.end_line,
                content_hash=c.content_hash,
                score=0.75,
                file_path=c.chunk_metadata.get("file_path", ""),
            )
            for c in db_chunks
        ]

        # Vector retriever returns semantic matches (auth.py, utils.py)
        vector_chunks = [c for c in retrieved_candidates if "utils.py" in c.file_path or "auth.py" in c.file_path]
        # Lexical retriever returns keyword matches (utils.py with hash_password)
        lexical_chunks = [c for c in retrieved_candidates if "hash" in c.content.lower()]

        mock_vector_retriever = AsyncMock()
        mock_vector_retriever.retrieve.return_value = vector_chunks
        mock_vector_retriever.aclose = AsyncMock()

        mock_lexical_retriever = AsyncMock()
        mock_lexical_retriever.retrieve.return_value = lexical_chunks
        mock_lexical_retriever.aclose = AsyncMock()

        # Mock CrossEncoder model scoring (controlled deterministic logits)
        mock_model = MagicMock()
        # Gives higher score if "password" in chunk content
        mock_model.predict.side_effect = lambda pairs: [
            8.5 if "password" in pair[1].lower() else 2.0 for pair in pairs
        ]
        reranker = CrossEncoderReranker(model=mock_model)

        hybrid_retriever = HybridRetriever(
            vector_retriever=mock_vector_retriever,
            lexical_retriever=mock_lexical_retriever,
            fusion=RRFFusion(),
            reranker=reranker,
        )

        results = await hybrid_retriever.retrieve("Where are passwords hashed?", repo.id, top_k=3)

        assert len(results) > 0
        # Highest reranked item should be the one containing password
        assert "password" in results[0].content.lower()
        assert results[0].score == 8.5
        mock_model.predict.assert_called_once()

    def test_context_builder_and_prompt_builder_token_budget_and_separation(self) -> None:
        """Verifies ContextBuilder limits context and PromptBuilder keeps code out of system prompt."""
        repo_id = uuid4()
        file_id = uuid4()

        chunks = [
            RetrievedChunk(
                id=uuid4(),
                repository_id=repo_id,
                file_id=file_id,
                symbol_id=None,
                content=f"def function_{i}():\n" + ("    # substantial logic line for budget testing\n" * 10) + f"    return {i * 10}\n",
                token_count=60,
                start_line=1,
                end_line=12,
                content_hash=f"hash_{i}",
                score=0.9 - (0.05 * i),
                file_path=f"module_{i}.py",
            )
            for i in range(10)
        ]

        # Restrict context budget to 620 tokens (500 overhead + 120 token budget -> ~2-3 chunks kept out of 10)
        builder = ContextBuilder(max_context_tokens=620)
        ctx = builder.build(chunks=chunks)

        assert 1 <= len(ctx.code_chunks) < len(chunks)
        rendered = builder.render_repository_data(ctx)
        assert "module_0.py" in rendered
        assert "module_9.py" not in rendered

        # PromptBuilder formatting
        prompt_builder = PromptBuilder()
        messages = prompt_builder.build_chat_prompt(
            context=rendered,
            question="What functions exist?",
        )

        system_msg = next(m for m in messages if m.role == "system")
        user_msg = next(m for m in messages if m.role == "user")

        # Crucial security rule: repository code MUST NEVER appear in system prompt
        assert "module_0.py" not in system_msg.content
        assert "def function_0" not in system_msg.content

        # Repository code MUST appear in user/context message
        assert "module_0.py" in user_msg.content
        assert "def function_0" in user_msg.content

    @pytest.mark.asyncio
    async def test_end_to_end_rag_pipeline_with_grounding_validation(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """Executes full RAGPipeline with mock LLM and real database grounding validation."""
        installation = GitHubInstallation(
            id=uuid4(),
            user_id=test_user.id,
            installation_id="gh-inst-rag",
            account_login=test_user.login,
            permissions={"contents": "read"},
        )
        db_session.add(installation)
        db_session.commit()

        repo = Repository(
            id=uuid4(),
            user_id=test_user.id,
            installation_id=installation.id,
            github_repo_id="gh-repo-rag",
            owner=test_user.login,
            name="python_sample",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        db_session.add(repo)
        db_session.commit()

        _files, _symbols, db_chunks = _sync_fixture_repo_to_db(db_session, repo, "python_sample")

        # Setup mock retriever returning utils.py chunk
        utils_chunk = next(c for c in db_chunks if "utils.py" in c.chunk_metadata["file_path"])
        retrieved_chunk = RetrievedChunk(
            id=utils_chunk.id,
            repository_id=repo.id,
            file_id=utils_chunk.file_id,
            symbol_id=utils_chunk.symbol_id,
            content=utils_chunk.content,
            token_count=utils_chunk.token_count,
            start_line=utils_chunk.start_line,
            end_line=utils_chunk.end_line,
            content_hash=utils_chunk.content_hash,
            score=0.98,
            file_path="utils.py",
        )

        mock_retriever = AsyncMock()
        mock_retriever.retrieve.return_value = [retrieved_chunk]

        # Setup mock LLM Gateway returning valid structured JSON answer citing utils.py lines 3-5
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = LLMResponse(
            content="""{
                "answer": "Passwords are hashed using SHA-256 via hashlib in utils.py.",
                "sources": [
                    {
                        "file": "utils.py",
                        "start_line": 3,
                        "end_line": 5,
                        "snippet": "def hash_password(password: str) -> str:"
                    }
                ],
                "confidence": "high"
            }""",
            model="gemini-flash-lite-latest",
            prompt_tokens=150,
            completion_tokens=40,
            total_tokens=190,
            latency_ms=120.0,
        )

        pipeline = RAGPipeline(
            retriever=mock_retriever,
            llm_gateway=mock_llm,
            db_session=db_session,
        )

        answer: RepositoryAnswer = await pipeline.chat(
            question="How are passwords hashed in this project?",
            repository_id=repo.id,
            history=[],
        )

        assert "hashlib in utils.py" in answer.answer
        assert len(answer.sources) == 1
        assert answer.sources[0].file == "utils.py"
        assert answer.confidence == "high"

    @pytest.mark.asyncio
    async def test_grounding_validator_security_and_failure_modes(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """Verifies GroundingValidator fails closed on path traversal, invalid line ranges, and DB errors."""
        installation = GitHubInstallation(
            id=uuid4(),
            user_id=test_user.id,
            installation_id="gh-inst-sec",
            account_login=test_user.login,
            permissions={"contents": "read"},
        )
        db_session.add(installation)
        db_session.commit()

        repo = Repository(
            id=uuid4(),
            user_id=test_user.id,
            installation_id=installation.id,
            github_repo_id="gh-repo-sec",
            owner=test_user.login,
            name="python_sample",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        db_session.add(repo)
        db_session.commit()

        _sync_fixture_repo_to_db(db_session, repo, "python_sample")
        validator = GroundingValidator(db_session=db_session)

        # 1. Path traversal attack
        traversal_answer = RepositoryAnswer(
            answer="Exfiltrated secret.",
            sources=[SourceReference(file="../../etc/shadow", start_line=1, end_line=5)],
            confidence="high",
        )
        result_traversal = await validator.validate_answer(repo.id, traversal_answer)
        assert result_traversal[0].grounded is False
        assert result_traversal[0].reason == "path_traversal"

        # 2. Line range exceeding file line count
        # utils.py has 6 lines
        overflow_answer = RepositoryAnswer(
            answer="Code in utils.py",
            sources=[SourceReference(file="utils.py", start_line=50, end_line=60)],
            confidence="high",
        )
        result_overflow = await validator.validate_answer(repo.id, overflow_answer)
        assert result_overflow[0].grounded is False
        assert result_overflow[0].reason == "line_range_invalid"

        # 3. Inverted line range
        inverted_answer = RepositoryAnswer(
            answer="Inverted range",
            sources=[SourceReference(file="utils.py", start_line=5, end_line=2)],
            confidence="high",
        )
        result_inverted = await validator.validate_answer(repo.id, inverted_answer)
        assert result_inverted[0].grounded is False
        assert result_inverted[0].reason == "line_range_invalid"

        # 4. Unknown repository UUID
        unknown_repo_id = uuid4()
        unknown_repo_answer = RepositoryAnswer(
            answer="Answer for missing repo",
            sources=[SourceReference(file="utils.py", start_line=1, end_line=3)],
            confidence="high",
        )
        result_unknown = await validator.validate_answer(unknown_repo_id, unknown_repo_answer)
        assert result_unknown[0].grounded is False
        assert result_unknown[0].reason == "repository_not_found"

        # 5. Missing database session -> Fails closed
        no_db_validator = GroundingValidator(db_session=None)
        result_no_db = await no_db_validator.validate_answer(repo.id, valid_repo_answer := RepositoryAnswer(
            answer="Valid text",
            sources=[SourceReference(file="utils.py", start_line=1, end_line=3)],
            confidence="high",
        ))
        assert result_no_db[0].grounded is False
        assert result_no_db[0].reason == "no_db_session"

        # 6. Database error during validation -> Fails closed
        broken_db = MagicMock()
        broken_db.execute.side_effect = RuntimeError("Database connection terminated")
        broken_validator = GroundingValidator(db_session=broken_db)
        result_broken_db = await broken_validator.validate_answer(repo.id, valid_repo_answer)
        assert result_broken_db[0].grounded is False
        assert result_broken_db[0].reason == "db_error"

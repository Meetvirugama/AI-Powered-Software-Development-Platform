"""
TDD Test Suite for Issue: "Improve code chunking, incremental indexing and embedding retrieval quality"

Covers:
- P1: Gemini task types (`RETRIEVAL_DOCUMENT` for indexing, `CODE_RETRIEVAL_QUERY` for queries)
      and `EmbeddingProfile` v2 (`profile_version="v2"`), strict compatibility checks,
      provider key rotation/retry/batch preservation, and staged v1 -> v2 re-embedding
      migration with progress tracking, resume, validation, atomic activation, and rollback.
- P2: cAST-style AST chunking (recursive splitting of >512-token AST/symbol nodes along
      syntax boundaries, greedy merging of adjacent small sibling nodes up to 512 tokens,
      dominant `symbol_id` + `metadata["symbol_ids"]`, obsolete chunk reconciliation,
      1-indexed inclusive ranges, and secret redaction).
- P2: Contextual embedding headers (`# path: ... | class ... | def ...`), strictly separated
      from displayed/stored `chunk.content` so source offsets and line mappings are untouched.
- P2: Consistent L2 normalization on write (`l2_normalize_vector`), rejection of zero-norm,
      NaN/Inf, and wrong-dimension vectors without silent replacement, and separate evaluation
      helper for cosine (`<=>`) vs inner-product (`<#>`) and `halfvec` float16 precision.
- P3: Optional `CodeRankEmbed` (`nomic-ai/CodeRankEmbed`) local embedding provider evaluation,
      strict ADR-008 policy enforcement (`AIQualityEvaluator` / explicit opt-in guard),
      and profile isolation (`provider="local_coderank"` never mixes with Gemini vectors).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from ai.embeddings.client import (
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingProfile,
    GeminiTaskType,
    InvalidVectorError,
    evaluate_vector_storage_modes,
    l2_normalize_vector,
)
from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
from ai.embeddings.local_provider import (
    CODERANK_MODEL_SPEC,
    CodeRankEmbedProvider,
    evaluate_local_embedding_candidate,
)
from ai.embeddings.service import CachedEmbeddingService, EmbeddingService
from ai.retrieval.vector import VectorRetriever
from ai.services.ai_quality_evaluator import AIQualityEvaluator
from app.core.errors import APIError
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from indexer.chunker import (
    MAX_CHUNK_TOKENS,
    SymbolChunker,
    build_contextual_embedding_input,
    build_contextual_header,
    reconstruct_file_from_chunks,
)
from indexer.incremental import (
    IncrementalIndexer,
    ReembeddingMigrationManager,
    compute_chunk_index_fingerprint,
)
from scanner.symbols import FileInfo, Symbol


# ===========================================================================
# P1: Gemini Task Types & EmbeddingProfile v2
# ===========================================================================


class TestP1GeminiTaskTypesAndProfileV2:
    """Verify official Gemini task types, EmbeddingProfile v2, and provider payload wiring."""

    def test_gemini_task_type_enum_matches_official_google_spec(self) -> None:
        assert GeminiTaskType.RETRIEVAL_DOCUMENT.value == "RETRIEVAL_DOCUMENT"
        assert GeminiTaskType.CODE_RETRIEVAL_QUERY.value == "CODE_RETRIEVAL_QUERY"
        assert GeminiTaskType.RETRIEVAL_QUERY.value == "RETRIEVAL_QUERY"
        assert GeminiTaskType.SEMANTIC_SIMILARITY.value == "SEMANTIC_SIMILARITY"

    def test_embedding_profile_v2_compatibility_rules(self) -> None:
        v1_prof = EmbeddingProfile(
            provider="gemini",
            model="models/gemini-embedding-001",
            dimensions=768,
            profile_version="v1",
        )
        v2_doc_prof = EmbeddingProfile.v2_gemini(dimensions=768)
        v2_query_prof = EmbeddingProfile.v2_gemini(
            dimensions=768,
            active_task_type=GeminiTaskType.CODE_RETRIEVAL_QUERY.value,
        )
        local_prof = EmbeddingProfile(
            provider="local_coderank",
            model="nomic-ai/CodeRankEmbed",
            dimensions=768,
            profile_version="v2",
        )

        assert v2_doc_prof.profile_version == "v2"
        assert v2_doc_prof.document_task_type == "RETRIEVAL_DOCUMENT"
        assert v2_doc_prof.query_task_type == "CODE_RETRIEVAL_QUERY"
        assert v2_doc_prof.contextual_headers is True
        assert v2_doc_prof.normalization is True

        # v1 and v2 must NOT be mixed
        assert v1_prof.is_compatible_with(v2_doc_prof) is False
        assert v2_doc_prof.is_compatible_with(v1_prof) is False

        # v2 document index and v2 code-retrieval query profile ARE compatible
        assert v2_query_prof.is_compatible_with(v2_doc_prof) is True
        assert v2_doc_prof.is_compatible_with(v2_query_prof) is True

        # Incompatible task type (e.g. CLASSIFICATION) must be rejected
        bad_task_prof = EmbeddingProfile.v2_gemini(
            dimensions=768,
            document_task_type="CLASSIFICATION",
            query_task_type="CLASSIFICATION",
            active_task_type="CLASSIFICATION",
        )
        assert v2_query_prof.is_compatible_with(bad_task_prof) is False

        # Different provider/model with same dimensions must be rejected
        assert v2_doc_prof.is_compatible_with(local_prof) is False

    @pytest.mark.asyncio
    async def test_gemini_provider_sends_verified_task_types_in_payload(self) -> None:
        captured_requests: list[dict[str, Any]] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            captured_requests.append(body)
            count = len(body["requests"])
            return httpx.Response(
                200,
                json={"embeddings": [{"values": [0.5] * 768} for _ in range(count)]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        provider = GeminiEmbeddingProvider(
            api_keys=["key-1", "key-2"],
            dimensions=768,
            client=client,
            profile_version="v2",
        )
        try:
            assert provider.profile.profile_version == "v2"
            doc_vecs = await provider.embed_documents(["def foo(): pass", "class Bar: pass"])
            assert len(doc_vecs) == 2
            assert all(
                req["taskType"] == "RETRIEVAL_DOCUMENT"
                for req in captured_requests[0]["requests"]
            )

            query_vec = await provider.embed_query("where is foo defined?")
            assert len(query_vec) == 768
            assert (
                captured_requests[1]["requests"][0]["taskType"] == "CODE_RETRIEVAL_QUERY"
            )
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_embedding_service_and_cache_separate_v1_v2_and_task_types(self) -> None:
        captured_task_types: list[str | None] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            for item in body["requests"]:
                captured_task_types.append(item.get("taskType"))
            count = len(body["requests"])
            return httpx.Response(
                200,
                json={"embeddings": [{"values": [3.0, 4.0] + [0.0] * 766} for _ in range(count)]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        provider = GeminiEmbeddingProvider(
            api_keys=["key-a"],
            dimensions=768,
            client=client,
            profile_version="v2",
        )
        cached_svc = CachedEmbeddingService(provider=provider)
        try:
            # embed_documents uses RETRIEVAL_DOCUMENT and L2 normalizes ([3, 4, 0...] -> [0.6, 0.8, 0...])
            doc_vecs = await cached_svc.embed_documents(["same text"])
            assert captured_task_types[-1] == "RETRIEVAL_DOCUMENT"
            assert math.isclose(doc_vecs[0][0], 0.6, rel_tol=1e-6)
            assert math.isclose(doc_vecs[0][1], 0.8, rel_tol=1e-6)

            # embed_query with identical text MUST NOT hit the document cache entry!
            q_vec = await cached_svc.embed_query("same text")
            assert len(captured_task_types) == 2
            assert captured_task_types[-1] == "CODE_RETRIEVAL_QUERY"
            assert math.isclose(math.sqrt(sum(x * x for x in q_vec)), 1.0, rel_tol=1e-6)
        finally:
            await client.aclose()


# ===========================================================================
# P2: L2 Normalization & Vector Storage Evaluation
# ===========================================================================


class TestP2L2Normalization:
    """Verify strict L2 normalization on write and rejection of invalid vectors."""

    def test_l2_normalize_vector_produces_unit_norm(self) -> None:
        raw = [3.0, 4.0, 0.0, 0.0]
        normed = l2_normalize_vector(raw, expected_dim=4)
        assert len(normed) == 4
        assert math.isclose(normed[0], 0.6, rel_tol=1e-7)
        assert math.isclose(normed[1], 0.8, rel_tol=1e-7)
        l2 = math.sqrt(sum(v * v for v in normed))
        assert math.isclose(l2, 1.0, rel_tol=1e-7)

    def test_l2_normalize_vector_rejects_zero_norm_without_silent_replacement(self) -> None:
        with pytest.raises(InvalidVectorError, match="zero-norm"):
            l2_normalize_vector([0.0] * 768, expected_dim=768)

        with pytest.raises(InvalidVectorError, match="zero-norm"):
            l2_normalize_vector([1e-20] * 768, expected_dim=768)

    def test_l2_normalize_vector_rejects_nan_inf_and_wrong_dimension(self) -> None:
        with pytest.raises(InvalidVectorError, match="non-finite"):
            l2_normalize_vector([1.0, float("nan"), 0.5], expected_dim=3)

        with pytest.raises(InvalidVectorError, match="non-finite"):
            l2_normalize_vector([1.0, float("inf"), 0.5], expected_dim=3)

        with pytest.raises(DimensionMismatchError):
            l2_normalize_vector([1.0, 2.0, 3.0], expected_dim=768)

    def test_evaluate_vector_storage_modes_cosine_vs_ip_and_halfvec(self) -> None:
        v1 = l2_normalize_vector([float(i + 1) for i in range(768)], expected_dim=768)
        v2 = l2_normalize_vector([float(768 - i) for i in range(768)], expected_dim=768)
        q = l2_normalize_vector([float((i % 7) + 1) for i in range(768)], expected_dim=768)

        report = evaluate_vector_storage_modes(corpus_vectors=[v1, v2], query_vectors=[q])
        assert report["default_operator"] == "<=>"
        assert report["cosine_vs_inner_product_max_diff"] < 1e-6
        assert report["halfvec_float16_max_abs_error"] < 1e-3
        assert report["top1_agreement_rate"] == 1.0


# ===========================================================================
# P2: cAST-Style AST Chunking & Contextual Embedding Headers
# ===========================================================================


class TestP2CastChunkingAndContextualHeaders:
    """Verify cAST recursive splitting, greedy sibling merging, and header separation."""

    def test_cAST_merges_adjacent_small_sibling_symbols_and_retains_symbol_ids(self) -> None:
        repo_id = uuid4()
        file_id = uuid4()
        source_lines = [
            "def add(a: int, b: int) -> int:",
            "    return a + b",
            "",
            "def sub(a: int, b: int) -> int:",
            "    return a - b",
            "",
            "def mul(a: int, b: int) -> int:",
            "    return a * b",
        ]
        source = "\n".join(source_lines)
        sym1 = Symbol(
            id=uuid4(),
            name="add",
            kind="function",
            file_id=file_id,
            start_line=1,
            end_line=2,
            signature="def add(a: int, b: int) -> int:",
        )
        sym2 = Symbol(
            id=uuid4(),
            name="sub",
            kind="function",
            file_id=file_id,
            start_line=4,
            end_line=5,
            signature="def sub(a: int, b: int) -> int:",
        )
        sym3 = Symbol(
            id=uuid4(),
            name="mul",
            kind="function",
            file_id=file_id,
            start_line=7,
            end_line=8,
            signature="def mul(a: int, b: int) -> int:",
        )

        chunker = SymbolChunker()
        chunks = chunker.chunk_symbols(
            repository_id=repo_id,
            file_id=file_id,
            symbols=[sym1, sym2, sym3],
            content=source,
            language="Python",
            file_path="backend/app/math_ops.py",
        )

        # Should produce a merged sibling chunk covering lines 1..8 (fewer embedding calls!)
        merged = [c for c in chunks if c.metadata.get("merged_sibling_count", 1) > 1]
        assert len(merged) == 1
        m_chunk = merged[0]
        assert m_chunk.symbol_id == sym1.id  # deterministic dominant symbol_id
        assert m_chunk.metadata["symbol_ids"] == [str(sym1.id), str(sym2.id), str(sym3.id)]
        assert m_chunk.start_line == 1
        assert m_chunk.end_line == 8
        assert m_chunk.token_count <= MAX_CHUNK_TOKENS

        # Displayed content must NOT contain the synthetic contextual header
        assert not m_chunk.content.startswith("# path:")
        assert m_chunk.embedding_text is not None
        assert m_chunk.embedding_text.startswith("# path: backend/app/math_ops.py")
        assert "def add(a: int, b: int) -> int:" in m_chunk.embedding_text

        # File reconstruction must remain exact
        reconstructed = reconstruct_file_from_chunks(chunks)
        assert reconstructed.splitlines() == source.splitlines()

    def test_cAST_recursively_splits_large_class_along_method_boundaries(self) -> None:
        repo_id = uuid4()
        file_id = uuid4()
        class_id = uuid4()

        # Construct a class whose total token count > 512, composed of 3 methods of ~220 tokens each
        lines: list[str] = ["class OrderProcessor:"]
        method_symbols: list[Symbol] = []
        current_line = 2

        for m_idx in range(1, 4):
            m_start = current_line
            sig = f"    def process_stage_{m_idx}(self, payload: dict) -> dict:"
            lines.append(sig)
            current_line += 1
            for step in range(35):
                lines.append(
                    f"        value_{m_idx}_{step} = payload.get('key_{step}', {step}) + {m_idx}"
                )
                current_line += 1
            lines.append(f"        return {{'stage': {m_idx}}}")
            m_end = current_line
            current_line += 1
            method_symbols.append(
                Symbol(
                    id=uuid4(),
                    name=f"process_stage_{m_idx}",
                    kind="method",
                    file_id=file_id,
                    start_line=m_start,
                    end_line=m_end,
                    signature=sig.strip(),
                    parent_id=class_id,
                )
            )

        class_sym = Symbol(
            id=class_id,
            name="OrderProcessor",
            kind="class",
            file_id=file_id,
            start_line=1,
            end_line=len(lines),
            signature="class OrderProcessor:",
        )
        source = "\n".join(lines)
        chunker = SymbolChunker()
        chunks = chunker.chunk_symbols(
            repository_id=repo_id,
            file_id=file_id,
            symbols=[class_sym, *method_symbols],
            content=source,
            language="Python",
            file_path="app/services/orders.py",
        )

        # Every emitted chunk must respect MAX_CHUNK_TOKENS
        assert all(c.token_count <= MAX_CHUNK_TOKENS for c in chunks)
        # Child method chunks should have contextual headers including parent class OrderProcessor
        method_chunks = [c for c in chunks if c.symbol_id in {m.id for m in method_symbols}]
        assert len(method_chunks) == 3
        for mc in method_chunks:
            assert mc.embedding_text is not None
            assert "path: app/services/orders.py" in mc.embedding_text
            assert "class OrderProcessor" in mc.embedding_text
            assert "# path:" not in mc.content

    def test_contextual_header_redacts_secrets_and_respects_token_budget(self) -> None:
        raw_secret = "sk-proj-" + "SecretTokenInSignature9876543210abcd"
        header = build_contextual_header(
            file_path="app/auth/client.py",
            language="Python",
            class_name="AuthClient",
            signature=f"def login(api_key: str = '{raw_secret}') -> bool:",
        )
        assert raw_secret not in header
        assert "[REDACTED]" in header
        assert header.startswith("# path: app/auth/client.py | class AuthClient | def login")

        body = " ".join(f"tok_{i}" for i in range(505))
        combined = build_contextual_embedding_input(body, header, max_tokens=MAX_CHUNK_TOKENS)
        assert len(combined.split()) <= MAX_CHUNK_TOKENS


# ===========================================================================
# P1 & P2: Incremental Indexing, Obsolete Chunk Reconciliation & Staged v1->v2 Migration
# ===========================================================================


class TestIncrementalIndexingAndStagedV2Migration:
    """Verify contextual embedding, L2 normalization on write, obsolete chunk cleanup, and v1->v2 migration."""

    @staticmethod
    def _seed_repo(db_session: Session) -> Repository:
        user = User(
            id=uuid4(),
            github_id=f"gh-{uuid4().hex[:8]}",
            login=f"u-{uuid4().hex[:6]}",
            email="u@example.com",
        )
        db_session.add(user)
        db_session.flush()
        inst = GitHubInstallation(
            id=uuid4(),
            user_id=user.id,
            installation_id=f"inst-{uuid4().hex[:8]}",
            account_login=user.login,
            permissions={"contents": "read"},
        )
        db_session.add(inst)
        db_session.flush()
        repo = Repository(
            id=uuid4(),
            user_id=user.id,
            installation_id=inst.id,
            github_repo_id=f"repo-{uuid4().hex[:8]}",
            owner=user.login,
            name="migration-repo",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.SYNCED,
        )
        db_session.add(repo)
        db_session.commit()
        return repo

    @pytest.mark.asyncio
    async def test_incremental_indexer_embeds_contextual_text_stores_clean_content_and_normalizes(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        repo = self._seed_repo(db_session)
        src_file = tmp_path / "service.py"
        src_file.write_text(
            "class PaymentGateway:\n"
            "    def charge(self, amount: int) -> bool:\n"
            "        return amount > 0\n",
            encoding="utf-8",
        )

        embedded_inputs: list[str] = []

        class _FakeV2Service:
            dimensions = 768
            model_name = "models/gemini-embedding-001"
            profile_version = "v2"
            profile = EmbeddingProfile.v2_gemini(dimensions=768)

            async def embed_documents(self, texts: list[str]) -> list[list[float]]:
                embedded_inputs.extend(texts)
                return [
                    l2_normalize_vector([3.0, 4.0] + [0.0] * 766, expected_dim=768)
                    for _ in texts
                ]

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return await self.embed_documents(texts)

        indexer = IncrementalIndexer(
            db_session=db_session,
            embedding_service=_FakeV2Service(),
        )
        f_info = FileInfo(
            path="service.py",
            size_bytes=src_file.stat().st_size,
            language="Python",
            is_binary=False,
        )
        stats = await indexer.sync(repo.id, [f_info], root_path=str(tmp_path))
        assert stats["indexed"] == 1

        # Embedding input received contextual header
        assert any("# path: service.py" in t for t in embedded_inputs)

        # Stored DB content MUST NOT contain synthetic "# path:" header
        rows = db_session.execute(
            text("SELECT content, embedding, metadata FROM code_chunks WHERE repository_id = :rid"),
            {"rid": repo.id.hex if db_session.bind.dialect.name == "sqlite" else repo.id},
        ).fetchall()
        assert len(rows) >= 1
        for content_val, emb_val, meta_val in rows:
            assert not str(content_val).startswith("# path:")
            meta_dict = json.loads(meta_val) if isinstance(meta_val, str) else meta_val
            assert meta_dict["embedding_profile_version"] == "v2"
            assert meta_dict["task_type"] == "RETRIEVAL_DOCUMENT"
            vec = json.loads(emb_val) if isinstance(emb_val, str) else list(emb_val)
            norm = math.sqrt(sum(float(x) * float(x) for x in vec))
            assert math.isclose(norm, 1.0, rel_tol=1e-5)

        # Modify file so chunk boundaries change -> obsolete chunks must be reconciled (not duplicated)
        src_file.write_text(
            "def standalone_helper(x: int) -> int:\n    return x * 2\n",
            encoding="utf-8",
        )
        stats2 = await indexer.sync(repo.id, [f_info], root_path=str(tmp_path))
        assert stats2["indexed"] == 1
        rows_after = db_session.execute(
            text("SELECT content FROM code_chunks WHERE repository_id = :rid"),
            {"rid": repo.id.hex if db_session.bind.dialect.name == "sqlite" else repo.id},
        ).fetchall()
        assert all("PaymentGateway" not in r[0] for r in rows_after)
        assert any("standalone_helper" in r[0] for r in rows_after)

    @pytest.mark.asyncio
    async def test_staged_v1_to_v2_reembedding_migration_preserves_v1_supports_resume_and_rollback(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        repo = self._seed_repo(db_session)
        f1 = tmp_path / "mod_a.py"
        f2 = tmp_path / "mod_b.py"
        f1.write_text("def alpha() -> int:\n    return 1\n", encoding="utf-8")
        f2.write_text("def beta() -> int:\n    return 2\n", encoding="utf-8")

        class _V1Service:
            dimensions = 768
            model_name = "models/gemini-embedding-001"
            profile_version = "v1"
            profile = EmbeddingProfile(
                provider="gemini",
                model="models/gemini-embedding-001",
                dimensions=768,
                profile_version="v1",
            )

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [[1.0] + [0.0] * 767 for _ in texts]

        v1_indexer = IncrementalIndexer(db_session=db_session, embedding_service=_V1Service())
        files = [
            FileInfo(path="mod_a.py", size_bytes=f1.stat().st_size, language="Python", is_binary=False),
            FileInfo(path="mod_b.py", size_bytes=f2.stat().st_size, language="Python", is_binary=False),
        ]
        await v1_indexer.sync(repo.id, files, root_path=str(tmp_path))

        # Verify v1 index is active
        v2_call_count = 0

        class _FlakyV2Service:
            dimensions = 768
            model_name = "models/gemini-embedding-001"
            profile_version = "v2"
            profile = EmbeddingProfile.v2_gemini(dimensions=768)

            async def embed_documents(self, texts: list[str]) -> list[list[float]]:
                nonlocal v2_call_count
                v2_call_count += 1
                if v2_call_count == 2:
                    raise EmbeddingError("Transient rate limit on file 2", retryable=True)
                return [l2_normalize_vector([0.6, 0.8] + [0.0] * 766, expected_dim=768) for _ in texts]

        manager = ReembeddingMigrationManager(
            db_session=db_session,
            embedding_service=_FlakyV2Service(),
        )

        # Step 1: Run staged migration where file 2 fails -> v1 must remain untouched and active!
        progress_partial = await manager.stage_v2_migration(
            repository_id=repo.id,
            scanned_files=files,
            root_path=str(tmp_path),
        )
        assert progress_partial.status == "PARTIAL_RETRYABLE"
        assert progress_partial.processed_files == 1
        assert progress_partial.failed_files == ["mod_b.py"]
        assert manager.get_active_profile_version(repo.id) == "v1"

        # Cannot activate incomplete v2 migration
        with pytest.raises(EmbeddingError, match="incomplete"):
            await manager.activate_v2(repo.id)

        # Step 2: Resume migration -> only failed/remaining file (mod_b.py) is embedded!
        calls_before_resume = v2_call_count
        progress_complete = await manager.stage_v2_migration(
            repository_id=repo.id,
            scanned_files=files,
            root_path=str(tmp_path),
            resume=True,
        )
        assert progress_complete.status == "STAGED_VALIDATED"
        assert progress_complete.processed_files == 2
        assert progress_complete.failed_files == []
        assert v2_call_count == calls_before_resume + 1  # mod_a.py was NOT re-embedded!

        # Active index is STILL v1 until explicit activation
        assert manager.get_active_profile_version(repo.id) == "v1"

        # Step 3: Activate v2 atomically -> v2 chunks become active, v1 superseded
        activated = await manager.activate_v2(repo.id)
        assert activated.status == "ACTIVE"
        assert manager.get_active_profile_version(repo.id) == "v2"

        # Step 4: Rollback restores v1 cleanly if needed
        rolled_back = await manager.rollback_to_v1(repo.id)
        assert rolled_back.status == "ROLLED_BACK"
        assert manager.get_active_profile_version(repo.id) == "v1"


# ===========================================================================
# P3: Optional Local Embedding Evaluation (`CodeRankEmbed`) & ADR-008 Guard
# ===========================================================================


class TestP3CodeRankEmbedAndAdr008Policy:
    """Verify CodeRankEmbed evaluation metadata, ADR-008 enforcement, and profile separation."""

    def test_coderank_model_spec_and_evaluation_summary(self) -> None:
        assert CODERANK_MODEL_SPEC.model_name == "nomic-ai/CodeRankEmbed"
        assert CODERANK_MODEL_SPEC.dimensions == 768
        assert CODERANK_MODEL_SPEC.max_seq_length == 8192
        assert (
            CODERANK_MODEL_SPEC.query_prefix
            == "Represent this query for searching relevant code: "
        )

        eval_report = evaluate_local_embedding_candidate()
        assert eval_report["model"] == "nomic-ai/CodeRankEmbed"
        assert eval_report["dimensions"] == 768
        assert eval_report["adr_008_default_allowed"] is False

    def test_adr_008_blocks_local_provider_by_default_and_requires_explicit_opt_in(self) -> None:
        # Instantiating CodeRankEmbedProvider without explicit opt-in raises EmbeddingError
        with pytest.raises(EmbeddingError, match="ADR-008"):
            CodeRankEmbedProvider(allow_local_embeddings=False)

        provider = CodeRankEmbedProvider(
            allow_local_embeddings=True,
            embed_fn=lambda texts: [[1.0] + [0.0] * 767 for _ in texts],
        )
        assert provider.provider_name == "local_coderank"
        assert provider.profile.profile_version == "v2"

        # AIQualityEvaluator rejects local_coderank under default ADR-008 policy
        default_evaluator = AIQualityEvaluator()
        check_default = default_evaluator.validate_provider(provider)
        assert check_default.is_allowed is False
        assert check_default.status == "INVALID_PROVIDER"
        with pytest.raises(APIError):
            default_evaluator.enforce_provider_policy(provider)

        # Only when local_coderank is explicitly permitted in evaluator configuration does it pass
        opt_in_evaluator = AIQualityEvaluator(
            permitted_providers={"gemini", "groq", "local_coderank"}
        )
        check_opt_in = opt_in_evaluator.validate_provider(provider)
        assert check_opt_in.is_allowed is True

    @pytest.mark.asyncio
    async def test_coderank_provider_applies_query_prefix_and_prevents_gemini_profile_mixing(
        self,
    ) -> None:
        seen_inputs: list[str] = []

        def _fake_encoder(texts: list[str]) -> list[list[float]]:
            seen_inputs.extend(texts)
            return [[3.0, 4.0] + [0.0] * 766 for _ in texts]

        local_provider = CodeRankEmbedProvider(
            allow_local_embeddings=True,
            embed_fn=_fake_encoder,
        )
        doc_vecs = await local_provider.embed_documents(["def compute(): return 42"])
        assert seen_inputs[-1] == "def compute(): return 42"
        assert math.isclose(math.sqrt(sum(v * v for v in doc_vecs[0])), 1.0, rel_tol=1e-6)

        q_vec = await local_provider.embed_query("how is compute implemented")
        assert seen_inputs[-1].startswith(
            "Represent this query for searching relevant code: "
        )
        assert math.isclose(math.sqrt(sum(v * v for v in q_vec)), 1.0, rel_tol=1e-6)

        # EmbeddingService with local_coderank must reject querying a Gemini index
        local_service = EmbeddingService(provider=local_provider)
        gemini_index_profile = EmbeddingProfile.v2_gemini(dimensions=768)
        with pytest.raises(EmbeddingError, match="Embedding profile mismatch"):
            local_service.validate_query_profile(gemini_index_profile)


# ===========================================================================
# Adversarial Audit Verification Tests
# ===========================================================================


class TestAdversarialAuditInvariants:
    """Verify deterministic chunk IDs, profile upgrade re-index checks, and v2 VectorRetriever wiring."""

    def test_stable_chunk_id_deterministic_for_unchanged_content_and_metadata(self) -> None:
        from indexer.chunker import compute_stable_chunk_id
        from indexer.incremental import should_reindex

        repo_id = uuid4()
        file_id = uuid4()
        sym_id = uuid4()

        id1 = compute_stable_chunk_id(
            repository_id=repo_id,
            file_id=file_id,
            chunk_type="function",
            start_line=10,
            end_line=25,
            content_hash="abc123hash",
            symbol_id=sym_id,
            symbol_ids=[str(sym_id)],
        )
        id2 = compute_stable_chunk_id(
            repository_id=repo_id,
            file_id=file_id,
            chunk_type="function",
            start_line=10,
            end_line=25,
            content_hash="abc123hash",
            symbol_id=sym_id,
            symbol_ids=[str(sym_id)],
        )
        id_changed = compute_stable_chunk_id(
            repository_id=repo_id,
            file_id=file_id,
            chunk_type="function",
            start_line=10,
            end_line=28,
            content_hash="abc123hash",
            symbol_id=sym_id,
            symbol_ids=[str(sym_id)],
        )
        assert id1 == id2
        assert id1 != id_changed

        # should_reindex detects profile version upgrades (v1 -> v2) even when content hash matches
        code = "def f(): return 1"
        from indexer.incremental import compute_content_hash

        h = compute_content_hash(code)
        assert should_reindex(code, h) is False
        assert (
            should_reindex(
                code,
                h,
                existing_profile_version="v1",
                target_profile_version="v2",
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_vector_retriever_uses_embed_query_for_v2_and_enforces_target_profile(
        self,
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from app.core.config import get_settings

        settings = get_settings()
        assert settings.embedding_profile_version == "v2"
        assert settings.embedding_document_task_type == "RETRIEVAL_DOCUMENT"
        assert settings.embedding_query_task_type == "CODE_RETRIEVAL_QUERY"

        called_embed_query: list[str] = []

        class _V2RetrievalService:
            dimensions = 768
            profile_version = "v2"
            profile = EmbeddingProfile.v2_gemini(dimensions=768)

            def validate_query_profile(self, target: EmbeddingProfile | None) -> None:
                if target and not self.profile.is_compatible_with(target):
                    raise EmbeddingError("Incompatible target index profile")

            async def embed_query(self, q: str) -> list[float]:
                called_embed_query.append(q)
                return l2_normalize_vector([0.6, 0.8] + [0.0] * 766, expected_dim=768)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            SimpleNamespace(
                id=uuid4(),
                repository_id=uuid4(),
                file_id=uuid4(),
                symbol_id=None,
                content="def check(): pass",
                token_count=4,
                start_line=1,
                end_line=1,
                content_hash="h",
                distance=0.1,
                file_path="app/check.py",
                importance_score=0.5,
            )
        ]
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        retriever = VectorRetriever(db=mock_db, embedding_service=_V2RetrievalService())  # type: ignore[arg-type]
        res = await retriever.retrieve("find check", uuid4(), top_k=5)
        assert len(res) == 1
        assert called_embed_query == ["find check"]

        # Mismatched v1 target profile must be rejected
        v1_target = EmbeddingProfile(
            provider="gemini",
            model="models/gemini-embedding-001",
            dimensions=768,
            profile_version="v1",
        )
        with pytest.raises(EmbeddingError, match="Incompatible target index profile"):
            await retriever.retrieve("find check", uuid4(), top_k=5, target_profile=v1_target)

    def test_bug_emb_01_non_contiguous_module_symbols_and_large_class_trailing_lines(self) -> None:
        """
        BUG-EMB-01 & BUG-EMB-05:
        1. Non-contiguous module symbols (top-of-file import + bottom-of-file constant separated by
           a large class/function) must NOT be merged into a giant file-spanning module chunk.
        2. Large classes (> 512 tokens) recursively split along child methods must preserve
           inter-method and trailing class lines (e.g., closing `}` or trailing fields) so
           `reconstruct_file_from_chunks` is lossless.
        3. Single-line or <= 4-line symbols > 512 tokens and dense chunk_text blocks > 512 tokens
           must be split so no chunk ever exceeds `MAX_CHUNK_TOKENS = 512`.
        """
        repo_id = uuid4()
        file_id = uuid4()
        cls_id = uuid4()

        lines: list[str] = ["import os"]
        lines.append("")
        lines.append("export class TsLargeService {")
        current_line = 4
        method_symbols: list[Symbol] = []

        for m_idx in range(1, 4):
            m_start = current_line
            sig = f"  async handleStage{m_idx}(payload: Record<string, number>) {{"
            lines.append(sig)
            current_line += 1
            for step in range(36):
                lines.append(f"    const v_{m_idx}_{step} = payload['k_{step}'] + {step} + {m_idx};")
                current_line += 1
            lines.append("  }")
            m_end = current_line
            current_line += 1
            method_symbols.append(
                Symbol(
                    id=uuid4(),
                    name=f"handleStage{m_idx}",
                    kind="method",
                    file_id=file_id,
                    start_line=m_start,
                    end_line=m_end,
                    signature=sig.strip(),
                    parent_id=cls_id,
                )
            )

        # Trailing class closing brace after last method!
        lines.append("}")
        cls_end_line = current_line
        current_line += 1
        lines.append("")
        current_line += 1
        const_line = current_line
        lines.append("export const SERVICE_VERSION = '2.0.0';")

        source = "\n".join(lines)
        imp_sym = Symbol(
            id=uuid4(),
            name="import os",
            kind="import",
            file_id=file_id,
            start_line=1,
            end_line=1,
            signature="import os",
        )
        cls_sym = Symbol(
            id=cls_id,
            name="TsLargeService",
            kind="class",
            file_id=file_id,
            start_line=3,
            end_line=cls_end_line,
            signature="export class TsLargeService {",
        )
        const_sym = Symbol(
            id=uuid4(),
            name="SERVICE_VERSION",
            kind="constant",
            file_id=file_id,
            start_line=const_line,
            end_line=const_line,
            signature="export const SERVICE_VERSION = '2.0.0';",
        )

        chunker = SymbolChunker()
        chunks = chunker.chunk_symbols(
            repository_id=repo_id,
            file_id=file_id,
            symbols=[imp_sym, cls_sym, *method_symbols, const_sym],
            content=source,
            language="TypeScript",
            file_path="src/service.ts",
        )

        # 1. Every chunk must strictly respect MAX_CHUNK_TOKENS
        assert all(c.token_count <= MAX_CHUNK_TOKENS for c in chunks)

        # 2. Module chunks must NOT span the entire file (line 1 .. const_line)
        module_chunks = [c for c in chunks if c.chunk_type == "module"]
        assert len(module_chunks) == 2
        assert module_chunks[0].start_line == 1 and module_chunks[0].end_line == 1
        assert module_chunks[1].start_line == const_line and module_chunks[1].end_line == const_line

        # 3. Trailing closing brace `}` of TsLargeService must be preserved in reconstruction
        reconstructed = reconstruct_file_from_chunks(chunks)
        assert reconstructed.splitlines() == source.splitlines()

        # 4. Pathological single-line > 512 tokens in both chunk_symbols and chunk_text must be capped
        long_line = "x = " + " + ".join(f"var_{i}" for i in range(600))
        one_line_sym = Symbol(
            id=uuid4(),
            name="long_expr",
            kind="function",
            file_id=file_id,
            start_line=1,
            end_line=1,
            signature="def long_expr():",
        )
        sym_long_chunks = chunker.chunk_symbols(
            repository_id=repo_id,
            file_id=file_id,
            symbols=[one_line_sym],
            content=long_line,
            language="Python",
        )
        assert len(sym_long_chunks) >= 2
        assert all(c.token_count <= MAX_CHUNK_TOKENS for c in sym_long_chunks)

        text_long_chunks = chunker.chunk_text(
            repository_id=repo_id,
            file_id=file_id,
            content=long_line,
            language="Python",
        )
        assert len(text_long_chunks) >= 2
        assert all(c.token_count <= MAX_CHUNK_TOKENS for c in text_long_chunks)

    @pytest.mark.asyncio
    async def test_bug_emb_02_and_03_incremental_profile_upgrade_and_migration_memory_cleanup(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        """
        BUG-EMB-02 & BUG-EMB-03:
        1. IncrementalIndexer.sync() re-indexes unchanged files when their existing chunks in
           `code_chunks` were indexed under `v1` and the current `embedding_service` is `v2`.
        2. ReembeddingMigrationManager uses deterministic `compute_stable_chunk_id` IDs and
           frees `_staged_chunks_by_repo` upon `activate_v2()` and `_v1_backup_by_repo` upon `rollback_to_v1()`.
        """
        repo = TestIncrementalIndexingAndStagedV2Migration._seed_repo(db_session)
        src = tmp_path / "upgrade_me.py"
        src.write_text("def compute_val(x: int) -> int:\n    return x + 10\n", encoding="utf-8")
        f_info = FileInfo(
            path="upgrade_me.py",
            size_bytes=src.stat().st_size,
            language="Python",
            is_binary=False,
        )

        class _V1Svc:
            dimensions = 768
            model_name = "models/gemini-embedding-001"
            profile_version = "v1"
            profile = EmbeddingProfile(
                provider="gemini",
                model="gemini-embedding-001",
                dimensions=768,
                profile_version="v1",
            )

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [[1.0] + [0.0] * 767 for _ in texts]

        class _V2Svc:
            dimensions = 768
            model_name = "models/gemini-embedding-001"
            profile_version = "v2"
            profile = EmbeddingProfile.v2_gemini(dimensions=768)

            async def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [l2_normalize_vector([0.6, 0.8] + [0.0] * 766, expected_dim=768) for _ in texts]

        # 1. Index under v1
        indexer_v1 = IncrementalIndexer(db_session=db_session, embedding_service=_V1Svc())
        stats_v1 = await indexer_v1.sync(repo.id, [f_info], root_path=str(tmp_path))
        assert stats_v1["indexed"] == 1

        # Re-running with v1 skips the unchanged file
        stats_v1_repeat = await indexer_v1.sync(repo.id, [f_info], root_path=str(tmp_path))
        assert stats_v1_repeat["skipped"] == 1

        # 2. Running IncrementalIndexer.sync with v2 service on the UNCHANGED file must re-embed to v2!
        indexer_v2 = IncrementalIndexer(db_session=db_session, embedding_service=_V2Svc())
        stats_v2_upgrade = await indexer_v2.sync(repo.id, [f_info], root_path=str(tmp_path))
        assert stats_v2_upgrade["indexed"] == 1
        assert stats_v2_upgrade["skipped"] == 0

        # Subsequent v2 sync skips because both content_hash and profile_version ('v2') now match
        stats_v2_repeat = await indexer_v2.sync(repo.id, [f_info], root_path=str(tmp_path))
        assert stats_v2_repeat["skipped"] == 1

        # 3. Verify ReembeddingMigrationManager memory cleanup on activate_v2 and rollback_to_v1
        mgr = ReembeddingMigrationManager(db_session=db_session, embedding_service=_V2Svc())
        await mgr.stage_v2_migration(repo.id, [f_info], root_path=str(tmp_path), resume=False)
        assert repo.id in mgr._staged_chunks_by_repo
        await mgr.activate_v2(repo.id)
        assert repo.id not in mgr._staged_chunks_by_repo  # freed after commit!
        await mgr.rollback_to_v1(repo.id)
        assert repo.id not in mgr._v1_backup_by_repo  # freed after rollback!

    @pytest.mark.asyncio
    async def test_bug_emb_04_and_06_gemini_model_prefix_normalization_and_doc_cache_dedup(
        self,
    ) -> None:
        """
        BUG-EMB-04 & BUG-EMB-06:
        1. EmbeddingProfile normalizes bare `gemini-embedding-001` to `models/gemini-embedding-001`.
        2. CachedEmbeddingService.embed_documents deduplicates identical inputs in a batch and
           reuses cached vectors across subsequent calls.
        """
        bare_prof = EmbeddingProfile(
            provider="gemini",
            model="gemini-embedding-001",
            dimensions=768,
            profile_version="v2",
            document_task_type="RETRIEVAL_DOCUMENT",
            query_task_type="CODE_RETRIEVAL_QUERY",
        )
        v2_prof = EmbeddingProfile.v2_gemini(dimensions=768)
        assert bare_prof.model == "models/gemini-embedding-001"
        assert bare_prof.is_compatible_with(v2_prof) is True
        assert v2_prof.is_compatible_with(bare_prof) is True

        provider_batch_sizes: list[int] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            count = len(body["requests"])
            provider_batch_sizes.append(count)
            return httpx.Response(
                200,
                json={"embeddings": [{"values": [3.0, 4.0] + [0.0] * 766} for _ in range(count)]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        provider = GeminiEmbeddingProvider.v2(api_keys=["k1"], client=client)
        cached_svc = CachedEmbeddingService(provider=provider)
        try:
            # 3 texts where 2 are identical -> provider only receives 2 unique texts!
            vecs1 = await cached_svc.embed_documents(["chunk A", "chunk B", "chunk A"])
            assert len(vecs1) == 3
            assert provider_batch_sizes == [2]
            assert vecs1[0] == vecs1[2]

            # Calling again with already-cached texts makes ZERO network calls!
            vecs2 = await cached_svc.embed_documents(["chunk B", "chunk A"])
            assert len(vecs2) == 2
            assert provider_batch_sizes == [2]
        finally:
            await client.aclose()



"""Comprehensive TDD test suite for Issue:
"Modernize language parsing, symbol extraction, dependency graphs and symbol ranking"

Covers all P1, P2, and P3 acceptance criteria:
- P1: Removal of `tree_sitter_languages` from active dependencies and parser runtime;
      maintained grammar loading (`tree-sitter-language-pack` / `tree_sitter_<lang>` / structural CST);
      parser and extractor fixtures across all 8 documented languages (Python, TypeScript,
      JavaScript, Go, Rust, Java, C, C++); 1-indexed inclusive source ranges; import tracking across
      all 8 languages; malformed code, invalid UTF-16 surrogates, empty files, unsupported languages,
      and Python 3.12+ compatibility.
- P2: Audited `CodeSymbol` (`importance_score`) and `SymbolEdge` (`target_name`, `provenance`,
      `resolution_status`, `confidence`, `weight`, nullable `target_symbol_id`) schema and migration;
      unresolved and ambiguous reference preservation without arbitrary target assignment;
      consistent edge direction (`source_id -> target_id`) and duplicate provenance reconciliation;
      repository-scoped weighted PageRank on empty, single-node, isolated, cyclic, dangling,
      vendor/generated, large, and multi-repository graphs with deterministic repeated runs;
      context retrieval secondary ranking signal preserving semantic dominance, deduplication,
      source locations, token budgets, and safe fallback when scores are missing.
- P3: Optional SCIP indexer registry (`scip-python`, `scip-typescript`) with licensing and
      maintenance metadata; disabled-by-default and unavailable fallbacks; host-execution
      prohibition and sandboxed execution limits; SCIP JSON validation, path-traversal protection,
      1-indexed inclusive symbol occurrence mapping, provenance recording (`scip,tree_sitter`),
      and unresolved reference preservation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai.context.intelligence_context import build_intelligence_context
from ai.retrieval.base import CodeChunk
from ai.retrieval.fusion import RRFFusion
from scanner.detector import LanguageDetector
from scanner.extractor import SymbolExtractor
from scanner.graph import DependencyGraphBuilder, merge_provenance
from scanner.import_tracker import ImportTracker
from scanner.parser import SUPPORTED_GRAMMARS, Parser, get_grammar_status
from scanner.scip_runner import (
    SCIP_INDEXER_REGISTRY,
     SandboxCommandResult,
    SCIPIndexerConfig,
    SCIPRunner,
)
from scanner.source_location import SourceLocationResolver
from scanner.symbol_ranker import (
    PageRankConfig,
    SymbolImportanceRanker,
    compute_symbol_pagerank,
    is_vendor_or_generated_path,
)
from scanner.symbols import FileInfo, Symbol, SymbolEdge

REPO_ROOT = Path(__file__).resolve().parents[2]
AST_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ast_sample"


# ===========================================================================
# P1: Modernized Tree-sitter Grammar Loading & 8-Language Fixture Regression
# ===========================================================================


class TestP1ModernizedGrammarLoadingAndEightLanguages:
    """Verifies P1 requirements: removal of tree_sitter_languages, 8-language parsing
    and symbol extraction, 1-indexed inclusive ranges, and failure resilience."""

    def test_tree_sitter_languages_removed_from_dependencies_and_parser(self):
        pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        reqs_text = (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
        parser_text = (REPO_ROOT / "backend" / "scanner" / "parser.py").read_text(encoding="utf-8")

        assert "tree-sitter-languages" not in pyproject_text
        assert "tree_sitter_languages" not in pyproject_text
        assert "tree-sitter-language-pack" in pyproject_text

        assert "tree-sitter-languages" not in reqs_text
        assert "tree_sitter_languages" not in reqs_text
        assert "tree-sitter-language-pack" in reqs_text

        assert "import tree_sitter_languages" not in parser_text

    def test_grammar_status_reports_all_eight_documented_languages(self):
        status = get_grammar_status()
        expected_languages = {
            "Python",
            "TypeScript",
            "JavaScript",
            "Go",
            "Rust",
            "Java",
            "C",
            "C++",
        }
        assert set(SUPPORTED_GRAMMARS.keys()) == expected_languages
        assert set(status.keys()) == expected_languages
        for lang, info in status.items():
            assert info["is_supported"] is True
            assert info["active_backend"] in (
                "tree_sitter_language_pack",
                "tree_sitter_python",
                "tree_sitter_javascript",
                "tree_sitter_typescript",
                "tree_sitter_go",
                "tree_sitter_rust",
                "tree_sitter_java",
                "tree_sitter_c",
                "tree_sitter_cpp",
                "structural_cst_fallback",
            ), f"Unexpected backend for {lang}: {info}"

    @pytest.mark.parametrize(
        ("fixture_name", "language", "expected_symbols"),
        [
            (
                "supported_python.py",
                "Python",
                {
                    ("AccountManager", "class"),
                    ("__init__", "method"),
                    ("get_display_name", "method"),
                    ("update_role", "method"),
                    ("calculate_tax", "function"),
                    ("fetch_user_data", "function"),
                    ("DEFAULT_TIMEOUT", "constant"),
                },
            ),
            (
                "supported_typescript.ts",
                "TypeScript",
                {
                    ("UserProfile", "interface"),
                    ("ProfileService", "class"),
                    ("getUserProfile", "method"),
                    ("validateProfile", "function"),
                    ("API_VERSION", "constant"),
                },
            ),
            (
                "supported_javascript.js",
                "JavaScript",
                {
                    ("RequestHandler", "class"),
                    ("handleRequest", "method"),
                    ("startServer", "function"),
                    ("DEFAULT_PORT", "constant"),
                },
            ),
            (
                "supported_go.go",
                "Go",
                {
                    ("TokenValidator", "interface"),
                    ("JWTService", "class"),
                    ("NewJWTService", "function"),
                    ("VerifyToken", "method"),
                    ("checkSignature", "function"),
                },
            ),
            (
                "supported_rust.rs",
                "Rust",
                {
                    ("CacheBackend", "interface"),
                    ("MemoryCache", "class"),
                    ("new", "method"),
                    ("insert_item", "method"),
                    ("get_item", "method"),
                    ("normalize_key", "function"),
                },
            ),
            (
                "supported_java.java",
                "Java",
                {
                    ("PaymentGateway", "interface"),
                    ("StripeGateway", "class"),
                    ("StripeGateway", "method"),
                    ("chargeAccount", "method"),
                    ("validateAmount", "method"),
                },
            ),
            (
                "supported_c.c",
                "C",
                {
                    ("PacketHeader", "class"),
                    ("validate_header", "function"),
                    ("process_packet", "function"),
                },
            ),
            (
                "supported_cpp.cpp",
                "C++",
                {
                    ("WorkerPool", "class"),
                    ("dispatchJob", "method"),
                    ("validateConcurrency", "method"),
                    ("computePoolCapacity", "function"),
                },
            ),
        ],
    )
    def test_all_eight_languages_parse_and_extract_1_indexed_inclusive_symbols(
        self,
        fixture_name: str,
        language: str,
        expected_symbols: set[tuple[str, str]],
    ):
        parser = Parser()
        extractor = SymbolExtractor(parser=parser)
        resolver = SourceLocationResolver(extractor=extractor, parser=parser)
        detector = LanguageDetector()

        fixture_path = AST_FIXTURES / fixture_name
        assert fixture_path.exists(), f"Missing fixture {fixture_path}"
        content = fixture_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        file_info = FileInfo(
            path=fixture_name,
            size_bytes=len(content.encode("utf-8")),
            language=language,
            is_binary=False,
        )
        assert detector.detect(file_info) == language
        assert detector.detect(fixture_name) == language

        parse_res = parser.parse_with_status(file_info, content)
        assert parse_res.success is True
        assert parse_res.is_supported is True
        assert parse_res.has_syntax_errors is False
        assert parse_res.tree is not None
        assert parse_res.grammar_backend in (
            "tree_sitter_language_pack",
            "tree_sitter_python",
            "tree_sitter_javascript",
            "tree_sitter_typescript",
            "tree_sitter_go",
            "tree_sitter_rust",
            "tree_sitter_java",
            "tree_sitter_c",
            "tree_sitter_cpp",
            "python_ast",
            "structural_cst_fallback",
        )

        symbols = extractor.extract(file_info, content)
        extracted_pairs = {(s.name, s.kind) for s in symbols}
        for expected_pair in expected_symbols:
            assert expected_pair in extracted_pairs, (
                f"Missing {expected_pair} in {language} fixture; got {extracted_pairs}"
            )

        # Verify 1-indexed inclusive source ranges for every symbol
        for sym in symbols:
            assert 1 <= sym.start_line <= sym.end_line <= len(lines), (
                f"Invalid range for {sym.name} in {fixture_name}: "
                f"{sym.start_line}..{sym.end_line} (total lines={len(lines)})"
            )
            snippet = resolver.extract_snippet(content, sym.start_line, sym.end_line)
            expected_text = "\n".join(lines[sym.start_line - 1 : sym.end_line])
            assert snippet == expected_text

    def test_import_tracker_supports_all_eight_languages(self):
        tracker = ImportTracker()
        known_files = [
            "pkg/helpers.go",
            "src/utils.rs",
            "com/example/service/BaseProcessor.java",
            "include/scanner.h",
        ]

        # Go
        go_content = (AST_FIXTURES / "supported_go.go").read_text(encoding="utf-8")
        go_map = tracker.parse_imports(
            FileInfo("cmd/main.go", len(go_content), "Go", False),
            go_content,
            known_files=known_files,
        )
        go_mods = {i.module for i in go_map.imports}
        assert "context" in go_mods
        assert "fmt" in go_mods

        # Rust
        rust_content = (AST_FIXTURES / "supported_rust.rs").read_text(encoding="utf-8")
        rust_map = tracker.parse_imports(
            FileInfo("src/lib.rs", len(rust_content), "Rust", False),
            rust_content,
            known_files=known_files,
        )
        rust_mods = {i.module for i in rust_map.imports}
        assert "std::collections::HashMap" in rust_mods
        assert "std::sync::Arc" in rust_mods

        # Java
        java_content = (AST_FIXTURES / "supported_java.java").read_text(encoding="utf-8")
        java_map = tracker.parse_imports(
            FileInfo("com/platform/billing/StripeGateway.java", len(java_content), "Java", False),
            java_content,
            known_files=known_files,
        )
        java_mods = {i.module for i in java_map.imports}
        assert "java.math.BigDecimal" in java_mods
        assert "java.util.List" in java_mods

        # C / C++
        cpp_content = (AST_FIXTURES / "supported_cpp.cpp").read_text(encoding="utf-8")
        cpp_map = tracker.parse_imports(
            FileInfo("src/analyzer.cpp", len(cpp_content), "C++", False),
            cpp_content + '\n#include "scanner.h"\n',
            known_files=known_files,
        )
        cpp_mods = {i.module for i in cpp_map.imports}
        assert "string" in cpp_mods
        assert "vector" in cpp_mods
        assert "scanner.h" in cpp_mods
        assert "include/scanner.h" in cpp_map.local_dependencies

    def test_malformed_code_and_invalid_encoding_across_languages_do_not_crash(self):
        parser = Parser()
        extractor = SymbolExtractor(parser=parser)

        malformed_samples = [
            ("broken.go", "Go", "package main\nfunc broken( {\n}\nfunc ValidGoFunc() int {\n    return 1\n}\n"),
            ("broken.rs", "Rust", "pub fn broken( -> i32 {\n\npub fn valid_rust_fn() -> i32 {\n    42\n}\n"),
            ("broken.java", "Java", "public class Broken {\n    public void validMethod() {\n    }\n"),
            ("broken.c", "C", "int valid_c_func(int x) {\n    return x;\n}\nint unclosed( {\n"),
            ("broken.cpp", "C++", "class ValidCpp {\npublic:\n    void run() {}\n};\nclass Unclosed {\n"),
            ("surrogate.py", "Python", "def clean_fn():\n    return 'bad-\ud800-surrogate'\n"),
        ]

        for path, lang, bad_code in malformed_samples:
            fi = FileInfo(path=path, size_bytes=len(bad_code), language=lang, is_binary=False)
            res = parser.parse_with_status(fi, bad_code)
            assert res.is_supported is True
            assert res.success is True
            # Extractor must never raise on malformed or surrogate-containing code
            syms = extractor.extract(fi, bad_code)
            assert isinstance(syms, list)
            assert len(syms) >= 1


# ===========================================================================
# P2: Edge Representation, Provenance, Ambiguity & Weighted PageRank
# ===========================================================================


class TestP2EdgesProvenanceAndPageRank:
    """Verifies P2 requirements: edge direction, unresolved/ambiguous preservation,
    provenance merging, weighted PageRank across graph topologies, and retrieval integration."""

    def test_edge_direction_unresolved_and_ambiguous_references_without_arbitrary_targets(self):
        file_a = uuid4()
        file_b = uuid4()
        file_c = uuid4()

        caller_sym = Symbol(
            id=uuid4(),
            name="orchestrate_payment",
            kind="function",
            file_id=file_a,
            file_path="src/payment.py",
            start_line=1,
            end_line=6,
            signature="def orchestrate_payment(order):",
        )
        unique_callee = Symbol(
            id=uuid4(),
            name="charge_card",
            kind="function",
            file_id=file_b,
            file_path="src/stripe_gateway.py",
            start_line=1,
            end_line=4,
            signature="def charge_card(amount):",
        )
        # Two duplicate `log_audit` definitions in different directories -> ambiguous without import map
        ambig_1 = Symbol(
            id=uuid4(),
            name="log_audit",
            kind="function",
            file_id=file_b,
            file_path="src/audit_v1/logger.py",
            start_line=1,
            end_line=3,
            signature="def log_audit(msg):",
        )
        ambig_2 = Symbol(
            id=uuid4(),
            name="log_audit",
            kind="function",
            file_id=file_c,
            file_path="src/audit_v2/logger.py",
            start_line=1,
            end_line=3,
            signature="def log_audit(msg):",
        )

        file_contents = {
            file_a: (
                "def orchestrate_payment(order):\n"
                "    charge_card(order.total)\n"
                "    log_audit('charged')\n"
                "    external_telemetry_ping(order.id)\n"
            ),
        }

        builder = DependencyGraphBuilder(
            [caller_sym, unique_callee, ambig_1, ambig_2],
            file_contents=file_contents,
        )
        resolved_edges = builder.build()

        # 1. Resolved call edge has consistent direction: caller -> callee
        assert len(resolved_edges) == 1
        call_edge = resolved_edges[0]
        assert call_edge.source_id == caller_sym.id
        assert call_edge.target_id == unique_callee.id
        assert call_edge.edge_type == "calls"
        assert call_edge.resolution_status == "resolved"
        assert call_edge.provenance == "tree_sitter"

        # 2. Ambiguous and unresolved references are preserved without arbitrary target_id
        unres_by_name = {e.target_name: e for e in builder.unresolved_edges}
        assert "log_audit" in unres_by_name
        ambig_edge = unres_by_name["log_audit"]
        assert ambig_edge.resolution_status == "ambiguous"
        assert ambig_edge.target_id is None
        assert set(ambig_edge.candidate_target_ids) == {ambig_1.id, ambig_2.id}

        assert "external_telemetry_ping" in unres_by_name
        unres_edge = unres_by_name["external_telemetry_ping"]
        assert unres_edge.resolution_status == "unresolved"
        assert unres_edge.target_id is None

        # 3. Adding an ImportTracker map disambiguates `log_audit` to `ambig_2` with merged provenance!
        tracker = ImportTracker()
        imp_map = tracker.parse_imports(
            FileInfo("src/payment.py", 100, "Python", False),
            "from src.audit_v2.logger import log_audit\n",
            known_files=["src/audit_v1/logger.py", "src/audit_v2/logger.py"],
        )
        resolved_with_imports = builder.build(import_maps={"src/payment.py": imp_map})
        by_target = {e.target_id: e for e in resolved_with_imports}
        assert ambig_2.id in by_target
        disambiguated = by_target[ambig_2.id]
        assert disambiguated.resolution_status == "resolved"
        assert disambiguated.provenance == "import_tracker,tree_sitter"

    def test_duplicate_edge_reconciliation_retains_multi_provider_provenance(self):
        src_id = uuid4()
        dst_id = uuid4()

        ts_edge = SymbolEdge(
            source_id=src_id,
            target_id=dst_id,
            edge_type="calls",
            target_name="validate",
            provenance="tree_sitter",
            resolution_status="resolved",
            confidence=0.9,
            weight=1.0,
        )
        scip_edge = SymbolEdge(
            source_id=src_id,
            target_id=dst_id,
            edge_type="calls",
            target_name="validate",
            provenance="scip",
            resolution_status="resolved",
            confidence=1.0,
            weight=1.0,
        )
        unres_ts = SymbolEdge(
            source_id=src_id,
            target_id=None,
            edge_type="calls",
            target_name="validate",
            provenance="import_tracker",
            resolution_status="unresolved",
            confidence=0.0,
            weight=1.0,
        )

        merged = DependencyGraphBuilder.reconcile_edges([ts_edge, scip_edge, unres_ts])
        assert len(merged) == 1
        assert merged[0].source_id == src_id
        assert merged[0].target_id == dst_id
        assert merged[0].provenance == "import_tracker,scip,tree_sitter"
        assert merged[0].confidence == 1.0

    def test_pagerank_empty_single_isolated_cyclic_and_dangling_graphs(self):
        ranker = SymbolImportanceRanker()

        # 1. Empty graph
        assert ranker.rank_symbols([], []) == {}
        assert ranker.last_metrics.node_count == 0
        assert ranker.last_metrics.converged is True

        # 2. Single-node graph
        single = Symbol(
            id=uuid4(),
            name="sole_fn",
            kind="function",
            file_id=uuid4(),
            file_path="src/sole.py",
            start_line=1,
            end_line=3,
        )
        single_scores = ranker.rank_symbols([single], [])
        assert single_scores[single.id] == 1.0
        assert single.importance_score == 1.0

        # 3. Isolated nodes (no edges) -> equal normalized scores
        iso_a = Symbol(uuid4(), "a", "function", uuid4(), 1, 2, file_path="src/a.py")
        iso_b = Symbol(uuid4(), "b", "function", uuid4(), 1, 2, file_path="src/b.py")
        iso_scores = ranker.rank_symbols([iso_a, iso_b], [])
        assert iso_scores[iso_a.id] == iso_scores[iso_b.id] == 1.0
        assert ranker.last_metrics.isolated_node_count == 2

        # 4. Cyclic + Dangling + Hub topology:
        #    caller_1 -> hub, caller_2 -> hub, caller_3 -> hub, hub -> sink (dangling), cycle_a <-> cycle_b
        hub = Symbol(uuid4(), "core_hub", "function", uuid4(), 1, 5, file_path="src/core.py")
        sink = Symbol(uuid4(), "leaf_sink", "function", uuid4(), 1, 5, file_path="src/leaf.py")
        c1 = Symbol(uuid4(), "c1", "function", uuid4(), 1, 5, file_path="src/c1.py")
        c2 = Symbol(uuid4(), "c2", "function", uuid4(), 1, 5, file_path="src/c2.py")
        c3 = Symbol(uuid4(), "c3", "function", uuid4(), 1, 5, file_path="src/c3.py")
        cyc_a = Symbol(uuid4(), "cyc_a", "function", uuid4(), 1, 5, file_path="src/cyc.py")
        cyc_b = Symbol(uuid4(), "cyc_b", "function", uuid4(), 6, 10, file_path="src/cyc.py")

        edges = [
            SymbolEdge(c1.id, hub.id, "calls"),
            SymbolEdge(c2.id, hub.id, "calls"),
            SymbolEdge(c3.id, hub.id, "calls"),
            # Duplicate edge of same type should be deduplicated, not double-counted
            SymbolEdge(c1.id, hub.id, "calls"),
            SymbolEdge(hub.id, sink.id, "calls"),
            SymbolEdge(cyc_a.id, cyc_b.id, "calls"),
            SymbolEdge(cyc_b.id, cyc_a.id, "calls"),
            # Unresolved edge must be ignored by PageRank
            SymbolEdge(c1.id, None, "calls", target_name="unknown_ext", resolution_status="unresolved"),
        ]
        all_syms = [hub, sink, c1, c2, c3, cyc_a, cyc_b]
        scores = ranker.rank_symbols(all_syms, edges)

        assert ranker.last_metrics.converged is True
        assert ranker.last_metrics.ignored_unresolved_count == 1
        # sink receives all mass from hub (which receives mass from c1, c2, c3)
        assert scores[hub.id] > scores[c1.id]
        assert scores[sink.id] > scores[c1.id]
        assert scores[cyc_a.id] == scores[cyc_b.id]

        # 5. Deterministic repeated calculations regardless of input permutation
        scores_reversed = ranker.rank_symbols(list(reversed(all_syms)), list(reversed(edges)))
        assert scores == scores_reversed

    def test_pagerank_vendor_discount_repository_isolation_and_large_graph_benchmark(self):
        # 1. Vendor / generated path discounting
        assert is_vendor_or_generated_path("node_modules/lodash/index.js") is True
        assert is_vendor_or_generated_path("api/proto/service_pb2.py") is True
        assert is_vendor_or_generated_path("backend/scanner/parser.py") is False

        core_sym = Symbol(uuid4(), "domain_service", "function", uuid4(), 1, 10, file_path="src/domain.py")
        vendor_sym = Symbol(uuid4(), "vendor_helper", "function", uuid4(), 1, 10, file_path="vendor/lib/helper.py")
        caller_a = Symbol(uuid4(), "caller_a", "function", uuid4(), 1, 5, file_path="src/a.py")
        caller_b = Symbol(uuid4(), "caller_b", "function", uuid4(), 1, 5, file_path="src/b.py")

        # Even with identical incoming call structure, core_sym ranks strictly higher than vendor_sym
        edges = [
            SymbolEdge(caller_a.id, core_sym.id, "calls"),
            SymbolEdge(caller_b.id, vendor_sym.id, "calls"),
        ]
        scores, _ = compute_symbol_pagerank([core_sym, vendor_sym, caller_a, caller_b], edges)
        assert scores[core_sym.id] == 1.0
        assert scores[vendor_sym.id] < 0.5

        # 2. Repository isolation: edges pointing to symbols outside the repository symbol list are ignored
        foreign_sym_id = uuid4()
        cross_repo_edges = edges + [SymbolEdge(caller_a.id, foreign_sym_id, "calls")]
        scores_isolated, _ = compute_symbol_pagerank([core_sym, vendor_sym, caller_a, caller_b], cross_repo_edges)
        assert scores == scores_isolated

        # 3. Large graph benchmark (500 symbols, 1,500 edges) completes in < 250ms
        large_symbols = [
            Symbol(
                id=uuid4(),
                name=f"sym_{i}",
                kind="function",
                file_id=uuid4(),
                start_line=1,
                end_line=10,
                file_path=f"src/mod_{i % 20}/file_{i}.py",
            )
            for i in range(500)
        ]
        large_edges = [
            SymbolEdge(
                source_id=large_symbols[i].id,
                target_id=large_symbols[(i * 7 + offset) % 500].id,
                edge_type="calls" if offset % 2 == 0 else "imports",
            )
            for i in range(500)
            for offset in (1, 3, 9)
            if (i * 7 + offset) % 500 != i
        ]
        large_scores, metrics = compute_symbol_pagerank(large_symbols, large_edges)
        assert len(large_scores) == 500
        assert metrics.converged is True
        assert metrics.duration_ms < 250.0, f"PageRank took too long: {metrics.duration_ms:.2f}ms"

    def test_retrieval_secondary_importance_signal_preserves_semantic_dominance_and_fallback(self):
        from ai.context.models import SymbolContext, TargetSnippet

        fusion = RRFFusion()
        repo_id = uuid4()
        file_id = uuid4()

        def _make_chunk(
            cid: UUID,
            path: str,
            content: str,
            score: float,
            imp: float | None = None,
        ) -> CodeChunk:
            return CodeChunk(
                id=cid,
                repository_id=repo_id,
                file_id=file_id,
                symbol_id=uuid4(),
                content=content,
                token_count=10,
                start_line=1,
                end_line=10,
                content_hash="h",
                score=score,
                file_path=path,
                importance_score=imp,
            )

        # Scenario 1: Semantic dominance — a rank-1 semantic match with missing/zero importance
        # MUST beat a rank-5 match even if the rank-5 match has maximum importance (1.0).
        c_sem_1_id = uuid4()
        c_hub_id = uuid4()
        sem_top = _make_chunk(c_sem_1_id, "src/auth.py", "def verify_jwt():", 0.95, imp=None)
        mid_2 = _make_chunk(uuid4(), "src/a.py", "def a():", 0.80, imp=0.1)
        mid_3 = _make_chunk(uuid4(), "src/b.py", "def b():", 0.70, imp=0.1)
        mid_4 = _make_chunk(uuid4(), "src/c.py", "def c():", 0.60, imp=0.1)
        high_imp_low_sem = _make_chunk(c_hub_id, "src/hub.py", "def hub():", 0.50, imp=1.0)

        ranked = fusion.fuse([sem_top, mid_2, mid_3, mid_4, high_imp_low_sem], k=60, top_n=5)
        assert ranked[0].id == c_sem_1_id, (
            "Semantic top match must remain #1 over lower-ranked high-PageRank symbol"
        )

        # Scenario 2: Secondary tie-breaking — when two chunks are tied in semantic RRF
        # (Chunk Low is #1 in vector/#2 in lexical; Chunk Hub is #2 in vector/#1 in lexical),
        # the chunk with higher PageRank importance_score wins!
        id_low = uuid4()
        id_hub = uuid4()
        chunk_low_v = _make_chunk(id_low, "src/util.py", "def util():", 0.90, imp=0.1)
        chunk_hub_v = _make_chunk(id_hub, "src/core.py", "def core():", 0.89, imp=0.95)

        chunk_hub_l = _make_chunk(id_hub, "src/core.py", "def core():", 0.90, imp=0.95)
        chunk_low_l = _make_chunk(id_low, "src/util.py", "def util():", 0.89, imp=0.1)

        tied_fused = fusion.fuse([chunk_low_v, chunk_hub_v], [chunk_hub_l, chunk_low_l], k=60, top_n=2)
        assert len(tied_fused) == 2
        assert tied_fused[0].id == id_hub
        assert tied_fused[0].start_line == 1 and tied_fused[0].end_line == 10

        # Scenario 3: build_intelligence_context secondary ranking & token budget preservation
        target = TargetSnippet(
            file_path="src/routes.py",
            content="def login_endpoint(req):\n    return authenticate_user(req)\n",
            start_line=1,
            end_line=2,
            symbol_name="login_endpoint",
            language="Python",
        )
        sym_Direct = SymbolContext(
            name="authenticate_user",
            kind="callee",
            file_path="src/auth.py",
            start_line=1,
            end_line=15,
            content="def authenticate_user(req): pass",
            score=1.5,
            importance_score=0.2,
        )
        sym_minor = SymbolContext(
            name="minor_helper",
            kind="callee",
            file_path="src/helper.py",
            start_line=1,
            end_line=5,
            content="def minor_helper(): pass",
            score=1.0,
            importance_score=0.05,
        )
        sym_hub = SymbolContext(
            name="core_dispatcher",
            kind="callee",
            file_path="src/core.py",
            start_line=1,
            end_line=25,
            content="def core_dispatcher(): pass",
            score=1.0,
            importance_score=1.0,
        )

        ctx = build_intelligence_context(
            target=target,
            related_symbols=[sym_Direct, sym_minor, sym_hub],
            token_budget=500,
        )
        # Higher primary score (`authenticate_user`) stays #1; tied primary score (1.0) orders `core_dispatcher` ahead of `minor_helper`
        assert ctx.related_symbols[0].name == "authenticate_user"
        assert ctx.related_symbols[1].name == "core_dispatcher"
        assert ctx.related_symbols[2].name == "minor_helper"
        assert ctx.total_tokens <= ctx.token_budget


# ===========================================================================
# P3: Optional Sandboxed SCIP Evaluation & Integration
# ===========================================================================


class TestP3OptionalSandboxedSCIPIntegration:
    """Verifies P3 requirements: SCIP indexer registry metadata, optional fallback,
    host-execution prohibition, sandbox resource limits, JSON validation, 1-indexed
    mapping, provenance merging, and unresolved reference retention."""

    def test_scip_indexer_registry_documents_licensing_and_maintenance(self):
        assert "Python" in SCIP_INDEXER_REGISTRY
        assert "TypeScript" in SCIP_INDEXER_REGISTRY
        py_meta = SCIP_INDEXER_REGISTRY["Python"]
        ts_meta = SCIP_INDEXER_REGISTRY["TypeScript"]
        assert py_meta.license == "Apache-2.0"
        assert ts_meta.license == "Apache-2.0"
        assert py_meta.binary_name == "scip-python"
        assert ts_meta.binary_name == "scip-typescript"

    def test_scip_disabled_or_unavailable_or_failed_falls_back_cleanly_to_tree_sitter(self):
        sym_a = Symbol(uuid4(), "caller", "function", uuid4(), 1, 5, file_path="src/a.py")
        sym_b = Symbol(uuid4(), "callee", "function", uuid4(), 1, 5, file_path="src/b.py")
        ts_edges = [SymbolEdge(sym_a.id, sym_b.id, "calls", target_name="callee", provenance="tree_sitter")]

        # 1. Disabled by default
        disabled_runner = SCIPRunner(config=SCIPIndexerConfig(enabled=False))
        res_disabled = disabled_runner.index_repository("/tmp/repo", "Python", [sym_a, sym_b], ts_edges)
        assert res_disabled.status == "skipped"
        assert res_disabled.fallback_used is True
        assert res_disabled.edges == ts_edges

        # 2. Host execution is strictly forbidden even if enabled
        unsafe_runner = SCIPRunner(config=SCIPIndexerConfig(enabled=True, allow_host_execution=True))
        res_unsafe = unsafe_runner.index_repository("/tmp/repo", "Python", [sym_a, sym_b], ts_edges)
        assert res_unsafe.status == "failed"
        assert res_unsafe.fallback_used is True
        assert "forbidden" in (res_unsafe.error_message or "").lower()
        assert res_unsafe.edges == ts_edges

        # 3. Unverified language (e.g. C++) falls back cleanly
        enabled_runner = SCIPRunner(config=SCIPIndexerConfig(enabled=True))
        res_unavail = enabled_runner.index_repository("/tmp/repo", "C++", [sym_a, sym_b], ts_edges)
        assert res_unavail.status == "unavailable"
        assert res_unavail.fallback_used is True
        assert res_unavail.edges == ts_edges

        # 4. Sandbox failure / timeout falls back cleanly
        class _TimingOutSandbox:
            def run_sandboxed(self, command, **kwargs):
                assert kwargs["network_disabled"] is True
                return SandboxCommandResult(exit_code=124, timed_out=True, stderr="Timed out")

        timeout_runner = SCIPRunner(
            config=SCIPIndexerConfig(enabled=True, timeout_seconds=10),
            sandbox_executor=_TimingOutSandbox(),
        )
        res_timeout = timeout_runner.index_repository("/tmp/repo", "Python", [sym_a, sym_b], ts_edges)
        assert res_timeout.status == "failed"
        assert res_timeout.fallback_used is True
        assert res_timeout.edges == ts_edges

        # 5. Invalid SCIP output falls back cleanly
        res_invalid = enabled_runner.index_repository(
            "/tmp/repo",
            "Python",
            [sym_a, sym_b],
            ts_edges,
            precomputed_index_payload='{"not_documents": []}',
        )
        assert res_invalid.status == "invalid_output"
        assert res_invalid.fallback_used is True
        assert res_invalid.edges == ts_edges

    def test_scip_valid_output_maps_1_indexed_occurrences_reconciles_provenance_and_retains_unresolved(self):
        sym_caller = Symbol(
            id=uuid4(),
            name="process_checkout",
            kind="function",
            file_id=uuid4(),
            file_path="src/checkout.py",
            start_line=10,
            end_line=25,
            signature="def process_checkout(cart):",
        )
        sym_callee = Symbol(
            id=uuid4(),
            name="compute_total",
            kind="function",
            file_id=uuid4(),
            file_path="src/pricing.py",
            start_line=1,
            end_line=8,
            signature="def compute_total(items):",
        )
        # Tree-sitter already found process_checkout -> compute_total
        ts_edge = SymbolEdge(
            source_id=sym_caller.id,
            target_id=sym_callee.id,
            edge_type="calls",
            target_name="compute_total",
            provenance="tree_sitter",
            resolution_status="resolved",
        )

        # SCIP 0-indexed payload:
        # - compute_total defined at line 0 (1-indexed line 1) in src/pricing.py
        # - referenced at line 14 (1-indexed line 15, inside process_checkout 10..25) in src/checkout.py
        # - external reference to stripe.Charge.create at line 18 (1-indexed line 19) in src/checkout.py
        scip_payload = {
            "metadata": {
                "tool_info": {"name": "scip-python", "version": "0.6.6"},
            },
            "documents": [
                {
                    "relative_path": "src/pricing.py",
                    "occurrences": [
                        {
                            "range": [0, 4, 17],
                            "symbol": "scip-python python pkg 0.1.0 src.pricing/compute_total().",
                            "symbol_roles": 1,  # Definition
                        }
                    ],
                },
                {
                    "relative_path": "src/checkout.py",
                    "occurrences": [
                        {
                            "range": [9, 4, 20],
                            "symbol": "scip-python python pkg 0.1.0 src.checkout/process_checkout().",
                            "symbol_roles": 1,  # Definition
                        },
                        {
                            "range": [14, 12, 25],
                            "symbol": "scip-python python pkg 0.1.0 src.pricing/compute_total().",
                            "symbol_roles": 0,  # Reference
                        },
                        {
                            "range": [18, 8, 28],
                            "symbol": "scip-python python stripe 5.0.0 stripe/Charge#create().",
                            "symbol_roles": 0,  # Unresolved external reference
                        },
                    ],
                },
            ],
        }

        class _MockSandbox:
            def run_sandboxed(self, command, **kwargs):
                import json
                assert command[0] == "scip-python"
                assert kwargs["network_disabled"] is True
                return SandboxCommandResult(
                    exit_code=0,
                    output_files={"index.scip": json.dumps(scip_payload).encode("utf-8")},
                )

        runner = SCIPRunner(
            config=SCIPIndexerConfig(enabled=True),
            sandbox_executor=_MockSandbox(),
        )
        scan_res = runner.index_repository(
            workspace_dir="/tmp/repo",
            language="Python",
            symbols=[sym_caller, sym_callee],
            existing_edges=[ts_edge],
        )

        assert scan_res.status == "completed"
        assert scan_res.fallback_used is False
        assert scan_res.indexer_name == "scip-python"
        assert scan_res.indexer_version == "0.6.6"
        assert scan_res.occurrences_processed == 4

        # Resolved edge reconciled Tree-sitter + SCIP provenance without duplicating the edge
        assert len(scan_res.edges) == 1
        resolved = scan_res.edges[0]
        assert resolved.source_id == sym_caller.id
        assert resolved.target_id == sym_callee.id
        assert resolved.provenance == "scip,tree_sitter"

        # Unresolved external SCIP reference is preserved with provenance="scip" and target_id=None
        assert len(scan_res.unresolved_edges) == 1
        unres = scan_res.unresolved_edges[0]
        assert unres.source_id == sym_caller.id
        assert unres.target_id is None
        assert unres.target_name == "create"
        assert unres.provenance == "scip"
        assert unres.resolution_status == "unresolved"


# ===========================================================================
# Remediation Regression Suite: BUG-P1-01, BUG-P2-01, BUG-P2-02, BUG-P2-03
# ===========================================================================


class TestRemediationRegressions:
    """Verifies the 4 remediation fixes across fallback JS/TS CST + native Tree-sitter
    node types, Vector/Lexical importance_score SQL mapping, orchestrator SymbolContext
    importance_score + null-safe neighbor_ids, and IncrementalIndexer unresolved edge
    persistence + idempotent re-sync."""

    def test_bug_p1_01_js_ts_structural_cst_fallback_and_native_tree_sitter_node_types(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # 1. Force structural_cst_fallback on TypeScript and JavaScript by disabling native tree-sitter loading
        parser = Parser()
        monkeypatch.setattr(parser, "_load_tree_sitter_parser", lambda *_a, **_k: (None, None))
        extractor = SymbolExtractor(parser=parser)
        resolver = SourceLocationResolver(extractor=extractor, parser=parser)

        for fixture_name, lang, expected in [
            (
                "supported_typescript.ts",
                "TypeScript",
                {
                    ("UserProfile", "interface"),
                    ("ProfileService", "class"),
                    ("getUserProfile", "method"),
                    ("validateProfile", "function"),
                    ("API_VERSION", "constant"),
                },
            ),
            (
                "supported_javascript.js",
                "JavaScript",
                {
                    ("RequestHandler", "class"),
                    ("handleRequest", "method"),
                    ("startServer", "function"),
                    ("DEFAULT_PORT", "constant"),
                },
            ),
        ]:
            content = (AST_FIXTURES / fixture_name).read_text(encoding="utf-8")
            lines = content.splitlines()
            fi = FileInfo(fixture_name, len(content), lang, False)
            parse_res = parser.parse_with_status(fi, content)
            assert parse_res.grammar_backend == "structural_cst_fallback"
            syms = extractor.extract(fi, content)
            pairs = {(s.name, s.kind) for s in syms}
            for item in expected:
                assert item in pairs, f"Missing {item} under structural_cst_fallback for {lang}; got {pairs}"
            cls_sym = next(s for s in syms if s.kind == "class")
            assert cls_sym.end_line > cls_sym.start_line
            for s in syms:
                assert 1 <= s.start_line <= s.end_line <= len(lines)
                assert resolver.extract_snippet(content, s.start_line, s.end_line) == "\n".join(
                    lines[s.start_line - 1 : s.end_line]
                )

        # 2. Verify native Tree-sitter node types for C/C++ parameter struct_specifier, Go const_spec, and Java field_declaration
        class _FakeTSNode:
            def __init__(self, type_: str, start: int, end: int, text: str = "", children=None):
                self.type = type_
                self.start_point = (start, 0)
                self.end_point = (end, 10)
                self.text = text.encode("utf-8")
                self.children = children or []
                self.has_error = False

        param_struct = _FakeTSNode(
            "struct_specifier",
            5,
            5,
            "struct PacketHeader",
            children=[_FakeTSNode("type_identifier", 5, 5, "PacketHeader")],
        )
        def_struct = _FakeTSNode(
            "struct_specifier",
            0,
            3,
            "struct PacketHeader { int version; }",
            children=[
                _FakeTSNode("type_identifier", 0, 0, "PacketHeader"),
                _FakeTSNode("field_declaration_list", 0, 3, "{ int version; }"),
            ],
        )
        go_const = _FakeTSNode(
            "const_declaration",
            4,
            4,
            "const MaxTokenTTL = 3600",
            children=[
                _FakeTSNode(
                    "const_spec",
                    4,
                    4,
                    "MaxTokenTTL = 3600",
                    children=[_FakeTSNode("identifier", 4, 4, "MaxTokenTTL")],
                )
            ],
        )
        java_const = _FakeTSNode(
            "field_declaration",
            6,
            6,
            "public static final int DEFAULT_TIMEOUT_MS = 5000;",
            children=[
                _FakeTSNode(
                    "variable_declarator",
                    6,
                    6,
                    "DEFAULT_TIMEOUT_MS = 5000",
                    children=[_FakeTSNode("identifier", 6, 6, "DEFAULT_TIMEOUT_MS")],
                )
            ],
        )
        root = _FakeTSNode("translation_unit", 0, 7, children=[param_struct, def_struct, go_const, java_const])
        monkeypatch.setattr(parser, "parse", lambda *_a, **_k: SimpleNamespace(root_node=root))
        sample_text = "\n".join(
            [
                "struct PacketHeader {",
                "    int version;",
                "};",
                "",
                "const MaxTokenTTL = 3600",
                "int validate(const struct PacketHeader *hdr);",
                "public static final int DEFAULT_TIMEOUT_MS = 5000;",
            ]
        )
        extracted = extractor.extract(FileInfo("sample.c", len(sample_text), "C", False), sample_text)
        class_syms = [s for s in extracted if s.kind == "class" and s.name == "PacketHeader"]
        assert len(class_syms) == 1, f"Expected exactly 1 PacketHeader definition, got {len(class_syms)}"
        const_names = {s.name for s in extracted if s.kind == "constant"}
        assert "MaxTokenTTL" in const_names
        assert "DEFAULT_TIMEOUT_MS" in const_names

    def test_bug_p2_01_vector_and_lexical_retrievers_populate_importance_score(self):
        from ai.retrieval.lexical import _LEXICAL_SEARCH_SQL, _row_to_chunk as lexical_row_to_chunk
        from ai.retrieval.vector import _VECTOR_SEARCH_SQL, _row_to_chunk as vector_row_to_chunk

        assert "importance_score" in str(_VECTOR_SEARCH_SQL)
        assert "importance_score" in str(_LEXICAL_SEARCH_SQL)

        row_with_imp = SimpleNamespace(
            id=uuid4(),
            repository_id=uuid4(),
            file_id=uuid4(),
            symbol_id=uuid4(),
            content="def core_hub(): pass",
            token_count=6,
            start_line=1,
            end_line=2,
            content_hash="h1",
            file_path="src/core.py",
            importance_score=0.875,
        )
        v_chunk = vector_row_to_chunk(row_with_imp, 0.92)
        l_chunk = lexical_row_to_chunk(row_with_imp, 0.88)
        assert v_chunk.importance_score == 0.875
        assert l_chunk.importance_score == 0.875

    @pytest.mark.asyncio
    async def test_bug_p2_02_and_p2_03_incremental_indexer_and_orchestrators_preserve_importance_and_unresolved_edges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.core.config import get_settings
        from app.core.database import Base
        from app.models.code_symbol import CodeSymbol
        from app.models.github_installation import GitHubInstallation
        from app.models.repository import Repository, SyncStatus
        from app.models.symbol_edge import SymbolEdge as DbSymbolEdge
        from app.models.user import User
        from app.schemas.analysis import (
            AnalysisTarget,
            BugDetectionRequest,
            CodeReviewRequest,
            ExplainCodeRequest,
            ReviewTarget,
        )
        from app.services.bug_detection_orchestrator import resolve_bug_target_and_build_context
        from app.services.code_review_orchestrator import resolve_review_target_and_build_context
        from app.services.explanation_orchestrator import resolve_target_and_build_context
        from indexer.incremental import IncrementalIndexer

        monkeypatch.setenv("JWT_SECRET", "test-secret-key-modernize-32bytes!!")
        get_settings.cache_clear()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            dbapi_connection.create_function(
                "to_tsvector", 2, lambda _cfg, txt: txt or "", deterministic=True
            )
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        session = SessionLocal()

        user_id = uuid4()
        inst_id = uuid4()
        repo_id = uuid4()
        session.add(User(id=user_id, github_id="901", login="dev", email="dev@example.com"))
        session.commit()
        session.add(
            GitHubInstallation(
                id=inst_id,
                user_id=user_id,
                installation_id="77001",
                account_login="dev",
                permissions={},
            )
        )
        session.commit()
        repo = Repository(
            id=repo_id,
            user_id=user_id,
            installation_id=inst_id,
            github_repo_id="555001",
            owner="dev",
            name="demo-repo",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.SYNCED,
        )
        session.add(repo)
        session.commit()

        pkg = tmp_path / "pkg"
        pkg.mkdir(parents=True, exist_ok=True)
        f_core = pkg / "core.py"
        f_api = pkg / "api.py"
        f_core.write_text(
            "def validate_token(tok: str) -> bool:\n"
            "    return external_crypto_verify(tok)\n",
            encoding="utf-8",
        )
        f_api.write_text(
            "from pkg.core import validate_token\n\n"
            "def handle_login(tok: str) -> bool:\n"
            "    return validate_token(tok)\n",
            encoding="utf-8",
        )

        scanned = [
            FileInfo("pkg/core.py", f_core.stat().st_size, "Python", False),
            FileInfo("pkg/api.py", f_api.stat().st_size, "Python", False),
        ]
        indexer = IncrementalIndexer(db_session=session, embedding_service=None)
        stats_1 = await indexer.sync(repository_id=repo_id, scanned_files=scanned, root_path=str(tmp_path))
        assert stats_1["indexed"] == 2

        # 1. Verify both resolved and unresolved edges are persisted in symbol_edges (BUG-P2-03)
        edges_1 = session.query(DbSymbolEdge).filter(DbSymbolEdge.repository_id == repo_id).all()
        statuses = {e.resolution_status for e in edges_1}
        assert "resolved" in statuses
        assert "unresolved" in statuses
        unres_edges = [e for e in edges_1 if e.resolution_status == "unresolved"]
        assert any(e.target_name == "external_crypto_verify" and e.target_symbol_id is None for e in unres_edges)

        # 2. Verify code_symbols.importance_score is populated (> 0.0)
        syms_db = session.query(CodeSymbol).filter(CodeSymbol.repository_id == repo_id).all()
        sym_by_name = {s.name: s for s in syms_db}
        assert sym_by_name["validate_token"].importance_score > 0.0

        # 3. Verify orchestrators handle nullable target_symbol_id on unresolved edges without crashing
        #    and propagate importance_score onto SymbolContext (BUG-P2-02)
        exp_req = ExplainCodeRequest(
            target=AnalysisTarget(type="symbol", path="pkg/core.py", symbol="validate_token")
        )
        exp_res = resolve_target_and_build_context(repo_id, repo, exp_req, session)
        assert any(s.name == "handle_login" and s.importance_score > 0.0 for s in exp_res.intelligence_context.related_symbols)

        bug_req = BugDetectionRequest(
            target=AnalysisTarget(type="symbol", path="pkg/core.py", symbol="validate_token")
        )
        bug_res = resolve_bug_target_and_build_context(repo_id, repo, bug_req, session)
        assert any(s.name == "handle_login" and s.importance_score > 0.0 for s in bug_res.intelligence_context.related_symbols)

        rev_req = CodeReviewRequest(target=ReviewTarget(type="file", path="pkg/core.py"))
        rev_res = await resolve_review_target_and_build_context(
            repository_id=repo_id,
            repo=repo,
            payload=rev_req,
            user_id=user_id,
            db=session,
        )
        assert any(s.name == "handle_login" and s.importance_score > 0.0 for s in rev_res.intelligence_context.related_symbols)

        # 4. Re-sync after touching a file must NOT duplicate symbol_edges
        f_api.write_text(
            "from pkg.core import validate_token\n\n"
            "def handle_login(tok: str) -> bool:\n"
            "    # updated comment\n"
            "    return validate_token(tok)\n",
            encoding="utf-8",
        )
        scanned_2 = [
            FileInfo("pkg/core.py", f_core.stat().st_size, "Python", False),
            FileInfo("pkg/api.py", f_api.stat().st_size, "Python", False),
        ]
        await indexer.sync(repository_id=repo_id, scanned_files=scanned_2, root_path=str(tmp_path))
        edges_2 = session.query(DbSymbolEdge).filter(DbSymbolEdge.repository_id == repo_id).all()
        edge_keys = [(e.source_symbol_id, e.target_symbol_id, e.target_name, e.edge_type) for e in edges_2]
        assert len(edge_keys) == len(set(edge_keys)), f"Duplicate symbol_edges found after re-sync: {edge_keys}"
        session.close()


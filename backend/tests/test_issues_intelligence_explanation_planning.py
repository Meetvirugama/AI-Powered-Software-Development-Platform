"""Comprehensive Regression & Adversarial Verification Suite for:
1. Teammate Commits Audit Fixes (BUG-TM-01..BUG-TM-04: PR #236 & PR #233)
2. Issue 1: Repository intelligence snapshot, PageRank importance (F05-C3), and Git co-change coupling
3. Issue 2: Code explanation optional depth mode (1-hop call graph F07-C3), LLM-as-judge rubric (P-28), and redacted source surfacing
4. Issue 3: Task intake & LLM planning with Agentless 3-stage Hierarchical Localisation and strict provider-level JSON schemas
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.intelligence.builder import RepositoryIntelligenceBuilder
from ai.intelligence.co_change import GitCoChangeMiner
from ai.intelligence.impact import DependencyImpactAnalyzer
from ai.intelligence.related_files import RelatedFileDiscoveryService
from ai.llm.gemini_provider import GeminiProvider, build_strict_gemini_response_schema
from ai.llm.groq_provider import GroqProvider, build_strict_groq_json_schema
from ai.llm.schemas import LLMRequest, LLMResponse, Message
from ai.services.ai_quality_evaluator import AIQualityEvaluator, ExplanationQualityRubric
from ai.services.bounded_repair_loop import BoundedRepairLoop
from ai.services.edit_synthesizer import EditSynthesizer
from ai.services.hierarchical_localizer import HierarchicalLocalizer
from ai.services.llm_repair_synthesizer import LLMRepairSynthesizer, _to_repo_relative_path
from ai.services.task_planner import TaskPlanner
from app.core.errors import APIError
from app.schemas.analysis import (
    AnalysisSourceReference,
    AnalysisTarget,
    CodeExplanation,
    ExplainCodeRequest,
    ExplainContextOptions,
    SymbolSummary,
)
from app.schemas.plan import LocalizationTarget, PlannerSchema, PlanStep
from app.schemas.repair import DiagnosedFailure, RepairPatchPayload, TracebackDiagnosisResult
from app.schemas.workspace import WorkspaceCreateRequest, WorkspacePushRequest
from app.services.explanation_orchestrator import (
    detect_redacted_source_metadata,
    ground_explanation_sources,
    is_explain_at_depth_enabled,
    resolve_target_and_build_context,
)
from app.services.repair_service import RepairPatchValidator
from sandbox.exceptions import WorkspacePolicyViolationError
from sandbox.workspace_manager import WorkspaceManager


# ===========================================================================
# 1. Teammate Commits Audit Fixes (BUG-TM-01 .. BUG-TM-04)
# ===========================================================================


class TestTeammateCommitFixes:
    """Verify fixes for BUG-TM-01, BUG-TM-02, BUG-TM-03, and BUG-TM-04."""

    @pytest.mark.asyncio
    async def test_bug_tm_01_multi_file_llm_repair_and_forbidden_files_enforcement(self, tmp_path):
        """BUG-TM-01: Multi-file LLM repair edits must preserve all modified files and block forbidden_files."""
        wm = WorkspaceManager(base_workspaces_dir=tmp_path / "ws")
        task_id = str(uuid4())
        wm.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision="a1b2c3d4",
            )
        )
        wm.write_file(task_id, "src/a.py", "def func_a():\n    return 1\n", create_parents=True)
        wm.write_file(task_id, "src/b.py", "def func_b():\n    return 2\n", create_parents=True)

        mock_resp = MagicMock()
        mock_resp.content = (
            '{\n'
            '  "explanation": "Fix both func_a and func_b",\n'
            '  "edits": [\n'
            '    {"file": "src/a.py", "search": "    return 1\\n", "replace": "    return 10\\n"},\n'
            '    {"file": "src/b.py", "search": "    return 2\\n", "replace": "    return 20\\n"}\n'
            '  ]\n'
            '}'
        )
        gateway = MagicMock()
        gateway.generate = AsyncMock(return_value=mock_resp)

        diag = TracebackDiagnosisResult(
            framework="pytest",
            total_failed=1,
            failures=[
                DiagnosedFailure(
                    failure_id="f1",
                    category="TEST_FAILURE",
                    file_path="src/a.py",
                    line_number=2,
                )
            ],
            can_attempt_repair=True,
        )
        synth = LLMRepairSynthesizer(llm_gateway=gateway, workspace_manager=wm)
        patch = await synth.synthesize_repair_async(
            task_id=task_id,
            attempt_number=1,
            diagnosis=diag,
            allowed_files=["src/a.py", "src/b.py"],
        )
        assert patch.target_files == ["src/a.py", "src/b.py"]
        assert "return 10" in patch.diff
        assert "return 20" in patch.diff

        # Verify BoundedRepairLoop._extract_patched_content slices per file without cross-contaminating
        patched_a = BoundedRepairLoop._extract_patched_content(
            "def func_a():\n    return 1\n",
            patch.diff,
            "src/a.py",
            patch.explanation,
        )
        patched_b = BoundedRepairLoop._extract_patched_content(
            "def func_b():\n    return 2\n",
            patch.diff,
            "src/b.py",
            patch.explanation,
        )
        assert "return 10" in patched_a and "func_b" not in patched_a
        assert "return 20" in patched_b and "func_a" not in patched_b

    def test_bug_tm_01_non_destructive_patch_when_hunk_context_mismatches(self):
        """BUG-TM-01: When existing_content is non-empty and removed lines do not match, do not wipe out the file."""
        existing = (
            "def important_one():\n"
            "    return 'keep_me'\n\n"
            "def important_two():\n"
            "    return 'also_keep_me'\n"
        )
        mismatched_diff = (
            "--- a/src/service.py\n"
            "+++ b/src/service.py\n"
            "@@ -10,1 +10,1 @@\n"
            "-    return 'non_existent_line'\n"
            "+    return 'new_single_line'\n"
        )
        result = BoundedRepairLoop._extract_patched_content(
            existing,
            mismatched_diff,
            "src/service.py",
            "Attempt fix",
        )
        assert "important_one" in result
        assert "important_two" in result

    def test_bug_tm_02_normalize_absolute_traceback_paths(self, tmp_path):
        """BUG-TM-02: Absolute traceback paths must be normalized to repo-relative paths."""
        rel = _to_repo_relative_path("/tmp/sandbox/ws-123/backend/app/main.py")
        assert rel == "backend/app/main.py"
        rel_generic = _to_repo_relative_path("/var/folders/xyz/custom_module.py")
        assert not rel_generic.startswith("/")
        assert rel_generic == "var/folders/xyz/custom_module.py"

    def test_bug_tm_03_repair_patch_validator_checks_target_files_against_allowed_files(self):
        """BUG-TM-03: Gate 5 must reject patches whose explicit target_files escape allowed_files scope."""
        validator = RepairPatchValidator()
        payload = RepairPatchPayload(
            task_id="task-1",
            attempt_number=1,
            diff="--- a/src/allowed.py\n+++ b/src/allowed.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
            explanation="Update allowed",
            target_files=["src/allowed.py", "src/unapproved_secret_target.py"],
        )
        res = validator.validate_patch(
            payload,
            allowed_files=["src/allowed.py"],
        )
        assert not res.is_valid
        assert any("unapproved_secret_target.py" in v for v in res.violations)

    def test_bug_tm_04_push_task_branch_blocks_malicious_remote_url(self, tmp_path):
        """BUG-TM-04: push_task_branch must reject remote_url starting with '-' or 'ext::'."""
        wm = WorkspaceManager(base_workspaces_dir=tmp_path / "ws")
        task_id = str(uuid4())
        wm.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision="a1b2c3d4",
            )
        )
        with pytest.raises(WorkspacePolicyViolationError):
            wm.push_task_branch(
                WorkspacePushRequest(
                    task_id=task_id,
                    branch_name="agent/task-123",
                    remote_name="origin",
                    remote_url="--upload-pack=evil",
                    publication_authorized=True,
                )
            )
        with pytest.raises(WorkspacePolicyViolationError):
            wm.push_task_branch(
                WorkspacePushRequest(
                    task_id=task_id,
                    branch_name="agent/task-123",
                    remote_name="origin",
                    remote_url="ext::sh -c evil",
                    publication_authorized=True,
                )
            )


# ===========================================================================
# 2. Issue 1: Repository Intelligence Snapshot, PageRank & Co-Change Coupling
# ===========================================================================


class TestIssue1RepositoryIntelligenceCoChangeAndPageRank:
    """Verify PageRank importance (F05-C3) and Git history co-change coupling in snapshot, related_files, and impact."""

    def test_git_co_change_miner_and_snapshot_integration(self):
        miner = GitCoChangeMiner(min_co_changes=2, min_jaccard=0.2)
        commit_history = [
            ("c1", ["backend/app/api.py", "backend/app/service.py", "backend/app/schemas.py"]),
            ("c2", ["backend/app/api.py", "backend/app/service.py"]),
            ("c3", ["backend/app/api.py", "backend/app/service.py"]),
            ("c4", ["backend/app/models.py"]),
        ]
        co_edges = miner.mine_co_changes(commit_history=commit_history)
        assert len(co_edges) >= 1
        top_edge = co_edges[0]
        assert {top_edge.file_a, top_edge.file_b} == {"backend/app/api.py", "backend/app/service.py"}
        assert top_edge.co_change_count == 3
        assert top_edge.jaccard_similarity == 1.0
        assert top_edge.last_co_changed_commit == "c1"

        # Build snapshot with symbols, call edges, and commit_history
        files = [
            SimpleNamespace(id="f1", path="backend/app/api.py", language="python", content_hash="h1", line_count=50, size_bytes=1000),
            SimpleNamespace(id="f2", path="backend/app/service.py", language="python", content_hash="h2", line_count=80, size_bytes=1600),
            SimpleNamespace(id="f3", path="backend/app/models.py", language="python", content_hash="h3", line_count=40, size_bytes=800),
        ]
        symbols = [
            SimpleNamespace(id="s1", name="endpoint_handler", kind="function", file_id="f1", file_path="backend/app/api.py", start_line=1, end_line=20, signature="def endpoint_handler()", importance_score=0.0),
            SimpleNamespace(id="s2", name="run_business_logic", kind="function", file_id="f2", file_path="backend/app/service.py", start_line=1, end_line=40, signature="def run_business_logic()", importance_score=0.0),
            SimpleNamespace(id="s3", name="UserRecord", kind="class", file_id="f3", file_path="backend/app/models.py", start_line=1, end_line=30, signature="class UserRecord", importance_score=0.0),
        ]
        edges = [
            SimpleNamespace(source_symbol_id="s1", target_symbol_id="s2", edge_type="calls", confidence=1.0),
            SimpleNamespace(source_symbol_id="s2", target_symbol_id="s3", edge_type="calls", confidence=1.0),
            SimpleNamespace(source_symbol_id="s1", target_symbol_id="s3", edge_type="uses", confidence=1.0),
        ]

        builder = RepositoryIntelligenceBuilder(repository_id=uuid4(), commit_sha="abc1234")
        snapshot = builder.build_snapshot(
            files=files,
            symbols=symbols,
            edges=edges,
            commit_history=commit_history,
        )

        # Verify PageRank computed on nodes, files, and modules
        node_map = {n.name: n for n in snapshot.nodes}
        assert node_map["UserRecord"].importance_score >= node_map["endpoint_handler"].importance_score
        assert node_map["UserRecord"].importance_score > 0.0
        assert len(snapshot.top_important_files) == 3
        assert len(snapshot.co_change_edges) >= 1

        # Verify RelatedFileDiscoveryService includes co_change_coupled and PageRank importance
        rel_service = RelatedFileDiscoveryService(snapshot=snapshot)
        related = rel_service.discover_related_files("backend/app/api.py")
        rel_paths = {r.path: r for r in related}
        assert "backend/app/service.py" in rel_paths
        assert rel_paths["backend/app/service.py"].importance_score > 0.0
        assert rel_paths["backend/app/service.py"].co_change_score == 1.0

        # Also test pure co-change relation when no AST edge exists between two files
        commit_history_extra = commit_history + [
            ("c5", ["backend/app/api.py", "backend/app/models.py"]),
            ("c6", ["backend/app/api.py", "backend/app/models.py"]),
        ]
        snapshot2 = builder.build_snapshot(
            files=files,
            symbols=symbols,
            edges=[],
            commit_history=commit_history_extra,
        )
        rel_only_cc = RelatedFileDiscoveryService(snapshot=snapshot2).discover_related_files("backend/app/api.py")
        assert any(r.relation == "co_change_coupled" for r in rel_only_cc)

        # Verify DependencyImpactAnalyzer reports co_change_coupled_files, high_importance_affected_files, and impact_risk_score
        analyzer = DependencyImpactAnalyzer(snapshot=snapshot)
        impact = analyzer.analyze_impact(["backend/app/service.py"])
        assert "backend/app/api.py" in impact.co_change_coupled_files
        assert "backend/app/api.py" in impact.affected_files
        assert len(impact.high_importance_affected_files) >= 2
        assert 0.0 < impact.impact_risk_score <= 1.0


# ===========================================================================
# 3. Issue 2: Code Explanation Depth Mode, Quality Rubric & Redacted Source
# ===========================================================================


class TestIssue2ExplanationDepthRubricAndRedaction:
    """Verify 1-hop 'Explain at depth', P-28 LLM-as-judge quality rubric, and [REDACTED] surfacing."""

    def test_detect_redacted_source_and_grounding_propagation(self):
        code_with_redactions = (
            'API_SECRET = "[REDACTED]"\n'
            'DB_PASSWORD = "[REDACTED_AWS_KEY]"\n'
            "def connect():\n"
            "    return True\n"
        )
        has_red, count, notice = detect_redacted_source_metadata(code_with_redactions)
        assert has_red is True
        assert count == 2
        assert notice is not None and "2 redacted" in notice

        req = ExplainCodeRequest(
            target=AnalysisTarget(type="symbol", path="src/config.py", symbol="connect"),
            depth_mode="deep",
            explain_at_depth=True,
            context=ExplainContextOptions(explain_at_depth=True),
        )
        assert is_explain_at_depth_enabled(req) is True

        # Verify ground_explanation_sources propagates redaction and depth fields
        resolved = resolve_target_and_build_context(
            uuid4(),
            SimpleNamespace(default_branch="main"),
            req,
            SimpleNamespace(_is_mock_db=True),
        )
        resolved.has_redacted_content = has_red
        resolved.redacted_occurrences = count
        resolved.redaction_notice = notice
        resolved.call_graph_depth_expanded = True
        resolved.expanded_callers = ["main_handler"]
        resolved.expanded_callees = ["open_socket"]

        raw_exp = CodeExplanation(
            purpose="Connects to database using configured credentials.",
            logic_flow=["Reads configuration (L1-L2)", "Returns connection status (L3-L4)"],
            key_symbols=[SymbolSummary(name="connect", kind="function", role="Initiates connection", start_line=3, end_line=4)],
            inputs_and_outputs="Inputs: none | Outputs: bool",
            dependencies=["open_socket"],
            sources=[AnalysisSourceReference(file_path="src/config.py", start_line=1, end_line=4)],
        )
        grounded = ground_explanation_sources(raw_exp, repository_id=uuid4(), resolved=resolved)
        assert grounded.has_redacted_content is True
        assert grounded.redacted_occurrences == 2
        assert grounded.redaction_notice == notice
        assert grounded.call_graph_depth_expanded is True
        assert grounded.expanded_callers == ["main_handler"]
        assert grounded.expanded_callees == ["open_socket"]

    @pytest.mark.asyncio
    async def test_explanation_quality_evaluator_deterministic_and_llm_judge(self):
        evaluator = AIQualityEvaluator()
        source = (
            'SECRET_TOKEN = "[REDACTED]"\n'
            "def verify_token(token: str) -> bool:\n"
            "    return check_signature(token, SECRET_TOKEN)\n"
        )
        explanation = CodeExplanation(
            purpose="Verifies an authentication token against the configured secret token using check_signature.",
            logic_flow=[
                "Loads the redacted SECRET_TOKEN constant (L1).",
                "Delegates signature verification to check_signature (L2-L3).",
            ],
            key_symbols=[
                SymbolSummary(name="verify_token", kind="function", role="Token verifier", start_line=2, end_line=3)
            ],
            inputs_and_outputs="Inputs: token (str) | Outputs: bool indicating signature validity.",
            dependencies=["check_signature", "auth_middleware"],
            execution_flow=["Called by auth_middleware -> verify_token -> invokes check_signature"],
            sources=[AnalysisSourceReference(file_path="src/auth.py", start_line=1, end_line=3)],
            has_redacted_content=True,
            redacted_occurrences=1,
            redaction_notice="Source code contains 1 redacted secret/configuration value (`[REDACTED]`).",
        )

        # 1. Deterministic rubric evaluation
        det_rubric = evaluator.evaluate_explanation_quality(
            explanation,
            source,
            expected_symbols=["verify_token"],
            callers=["auth_middleware"],
            callees=["check_signature"],
        )
        assert isinstance(det_rubric, ExplanationQualityRubric)
        assert det_rubric.judge_mode == "deterministic_rubric"
        assert det_rubric.passed is True
        assert det_rubric.redaction_transparency == 5.0
        assert det_rubric.overall_score >= 0.80

        # 2. LLM-as-judge (P-28) evaluation with permitted provider (Gemini)
        mock_judge_resp = MagicMock()
        mock_judge_resp.content = (
            '{\n'
            '  "factual_accuracy": 4.8,\n'
            '  "completeness": 4.7,\n'
            '  "call_graph_context_clarity": 4.6,\n'
            '  "citation_grounding": 5.0,\n'
            '  "redaction_transparency": 5.0,\n'
            '  "rationale": "Accurate, grounded explanation with clear 1-hop caller/callee context.",\n'
            '  "improvement_suggestions": []\n'
            '}'
        )
        mock_gateway = MagicMock()
        mock_gateway.provider = SimpleNamespace(provider_name="gemini", default_model="gemini-2.5-flash")
        mock_gateway.generate = AsyncMock(return_value=mock_judge_resp)

        llm_rubric = await evaluator.evaluate_explanation_quality_async(
            explanation,
            source,
            llm_gateway=mock_gateway,
            callers=["auth_middleware"],
            callees=["check_signature"],
        )
        assert llm_rubric.judge_mode == "llm_judge"
        assert llm_rubric.passed is True
        assert llm_rubric.factual_accuracy == 4.8
        assert llm_rubric.overall_score > 0.90

        # 3. ADR-008 provider policy enforcement rejects unapproved provider
        bad_gateway = MagicMock()
        bad_gateway.provider = SimpleNamespace(provider_name="openai", default_model="gpt-4o")
        with pytest.raises(APIError) as exc_info:
            evaluator.evaluate_explanation_quality(explanation, source, llm_gateway=bad_gateway)
        assert exc_info.value.status_code == 400


# ===========================================================================
# 4. Issue 3: Agentless Hierarchical Localisation & Strict Provider JSON Schemas
# ===========================================================================


class TestIssue3HierarchicalLocalizationAndStrictProviderSchemas:
    """Verify 3-stage Agentless localization, PlanStep/PlannerSchema persistence, EditSynthesizer integration, and strict Groq/Gemini JSON schemas."""

    @pytest.mark.asyncio
    async def test_hierarchical_localizer_three_stages_and_task_planner_integration(self):
        localizer = HierarchicalLocalizer()
        task = SimpleNamespace(
            id=uuid4(),
            repository_id=uuid4(),
            title="Fix token expiration check in validate_session_token",
            description="In backend/app/auth_session.py, `validate_session_token` fails when token expiry is None.",
            source_type="GITHUB_ISSUE",
            base_revision="a1b2c3d4",
            requirements=[
                {
                    "id": "req-1",
                    "description": "Update validate_session_token in backend/app/auth_session.py to guard None expiry.",
                    "target_files": ["backend/app/auth_session.py"],
                }
            ],
            assumptions=[],
            constraints=[{"forbidden_files": [".env", "backend/app/secret_keys.py"]}],
            origin_finding_id=None,
            repair_attempts_max=3,
        )

        # Build a mock snapshot with symbols, PageRank scores, and co-change edges
        files = [
            SimpleNamespace(id="f1", path="backend/app/auth_session.py", language="python", content_hash="h1", line_count=120, size_bytes=3000),
            SimpleNamespace(id="f2", path="backend/app/middleware.py", language="python", content_hash="h2", line_count=90, size_bytes=2000),
            SimpleNamespace(id="f3", path="backend/app/secret_keys.py", language="python", content_hash="h3", line_count=30, size_bytes=500),
        ]
        symbols = [
            SimpleNamespace(
                id="sym1",
                name="validate_session_token",
                kind="function",
                file_id="f1",
                file_path="backend/app/auth_session.py",
                start_line=42,
                end_line=78,
                signature="def validate_session_token(token: str, expiry: int | None) -> bool",
                importance_score=0.92,
            ),
            SimpleNamespace(
                id="sym2",
                name="SessionMiddleware",
                kind="class",
                file_id="f2",
                file_path="backend/app/middleware.py",
                start_line=10,
                end_line=65,
                signature="class SessionMiddleware",
                importance_score=0.65,
            ),
        ]
        snapshot = RepositoryIntelligenceBuilder(repository_id=task.repository_id).build_snapshot(
            files=files,
            symbols=symbols,
            edges=[],
            commit_history=[
                ("c1", ["backend/app/auth_session.py", "backend/app/middleware.py"]),
                ("c2", ["backend/app/auth_session.py", "backend/app/middleware.py"]),
            ],
        )

        targets = localizer.localize(
            task,
            repo_files=["backend/app/auth_session.py", "backend/app/middleware.py", "backend/app/secret_keys.py"],
            snapshot=snapshot,
        )
        assert len(targets) >= 1
        primary = targets[0]
        assert primary.file_path == "backend/app/auth_session.py"
        assert primary.symbol_name == "validate_session_token"
        assert primary.start_line == 42
        assert primary.end_line == 78
        assert primary.localization_stage == "line_range"
        assert all(t.file_path != "backend/app/secret_keys.py" for t in targets)

        # Verify TaskPlanner persists localization_targets on StructuredPlan and PlanStep
        planner = TaskPlanner(llm_gateway=None, localizer=localizer)
        plan = await planner.generate_plan(task, db=None)
        assert len(plan.localization_targets) >= 1
        assert plan.localization_targets[0].file_path == "backend/app/auth_session.py"
        assert len(plan.steps[0].localization_targets) >= 1

        # Verify EditSynthesizer includes localization_targets in LLM prompt
        captured_reqs: list[LLMRequest] = []

        async def _capture_generate(req: LLMRequest) -> LLMResponse:
            captured_reqs.append(req)
            return LLMResponse(
                content='{"explanation": "Guard None expiry", "edits": [{"file": "backend/app/auth_session.py", "search": "return False", "replace": "return True"}]}',
                model="gemini-2.5-flash",
            )

        mock_gw = MagicMock()
        mock_gw.generate = AsyncMock(side_effect=_capture_generate)
        synthesizer = EditSynthesizer(llm_gateway=mock_gw)
        await synthesizer._generate_llm_edits(
            step=plan.steps[1],
            file_contents={"backend/app/auth_session.py": "def validate_session_token():\n    return False\n"},
            allowed_files=["backend/app/auth_session.py"],
            task_context=None,
            previous_error=None,
            previous_edits=[],
            attempt=1,
        )
        assert len(captured_reqs) == 1
        assert "HIERARCHICAL LOCALIZATION TARGETS" in captured_reqs[0].messages[1].content
        assert "backend/app/auth_session.py" in captured_reqs[0].messages[1].content

    def test_strict_provider_level_json_schemas_for_groq_and_gemini(self):
        # 1. Groq strict json_schema builder
        groq_format = build_strict_groq_json_schema(PlannerSchema)
        assert groq_format["type"] == "json_schema"
        assert groq_format["json_schema"]["name"] == "StructuredPlan"
        assert groq_format["json_schema"]["strict"] is True
        root_schema = groq_format["json_schema"]["schema"]
        assert root_schema["additionalProperties"] is False
        assert "summary" in root_schema["required"]
        assert "steps" in root_schema["required"]

        groq_provider = GroqProvider(api_keys=["gsk_test_key_123456"])
        req = LLMRequest(
            model="openai/gpt-oss-120b",
            messages=[Message(role="user", content="Generate plan")],
            response_schema=PlannerSchema,
        )
        groq_payload = groq_provider._build_payload(req, "openai/gpt-oss-120b")
        assert groq_payload["response_format"]["type"] == "json_schema"
        assert groq_payload["response_format"]["json_schema"]["strict"] is True

        # 2. Gemini strict responseSchema builder
        gemini_schema = build_strict_gemini_response_schema(PlannerSchema)
        assert gemini_schema["type"] == "OBJECT"
        assert "properties" in gemini_schema
        assert "summary" in gemini_schema["properties"]
        assert "steps" in gemini_schema["properties"]
        assert "$defs" not in gemini_schema

        gemini_provider = GeminiProvider(api_keys=["AIzaSyTestKey123456"])
        gem_payload, _ = gemini_provider._build_payload(req)
        assert gem_payload["generationConfig"]["responseMimeType"] == "application/json"
        assert gem_payload["generationConfig"]["responseSchema"]["type"] == "OBJECT"

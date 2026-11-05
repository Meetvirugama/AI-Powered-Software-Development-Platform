"""Task Context Builder — Repository Intelligence–backed Context for Task Planning.

Owner: Meet & Dev (task.md §5 A, Phase 1).
Integrates shared Repository Intelligence (symbols, edges, chunks, files, tests) into
task planning so the planner understands callers, dependencies, constraints, and architecture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ai.context.token_budget import count_tokens
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.models.analysis_finding import AnalysisFinding
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.models.task import AgentTask

logger = logging.getLogger(__name__)


@dataclass
class TaskContextManifest:
    """Rich manifest summarizing repository context assembled for task planning."""

    snapshot_id: str
    commit_sha: str | None
    retrieved_files: list[str] = field(default_factory=list)
    retrieved_symbols: list[str] = field(default_factory=list)
    callers: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    truncated_context: bool = False
    confidence: float = 1.0
    architecture_rules: list[str] = field(default_factory=list)
    existing_tests: list[str] = field(default_factory=list)
    language: str = "Python"
    test_command: str = "pytest -q"
    target_files: list[str] = field(default_factory=list)
    prompt_context_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "commit_sha": self.commit_sha,
            "retrieved_files": self.retrieved_files,
            "retrieved_symbols": self.retrieved_symbols,
            "callers": self.callers,
            "dependencies": self.dependencies,
            "excluded_files": self.excluded_files,
            "missing_dependencies": self.missing_dependencies,
            "truncated_context": self.truncated_context,
            "confidence": self.confidence,
            "architecture_rules": self.architecture_rules,
            "existing_tests": self.existing_tests,
            "language": self.language,
            "test_command": self.test_command,
            "target_files": self.target_files,
        }


class TaskContextBuilder:
    """Assembles Repository Intelligence into an evidence-backed task context."""

    def __init__(self, token_budget: int = 12_000) -> None:
        self.token_budget = token_budget

    def build_task_context(
        self,
        task: AgentTask,
        db: Session | None = None,
        *,
        file_contents: dict[str, str] | None = None,
    ) -> TaskContextManifest:
        """Query repository intelligence tables to build a contextual planning manifest."""
        repository_id = getattr(task, "repository_id", None)
        base_revision = getattr(task, "base_revision", None)
        snapshot_id = f"snap_{str(base_revision or repository_id or 'default')[:12]}"

        language = "Python"
        test_command = "pytest -q"
        repo_files: list[str] = []
        target_files: list[str] = []
        retrieved_symbols: list[str] = []
        callers: list[str] = []
        dependencies: list[str] = []
        excluded_files: list[str] = []
        missing_dependencies: list[str] = []
        existing_tests: list[str] = []
        architecture_rules: list[str] = []
        finding_summaries: list[str] = []

        # 1. Collect forbidden files from task constraints
        forbidden_lower: set[str] = set()
        for cst in getattr(task, "constraints", []) or []:
            if isinstance(cst, dict):
                for fp in cst.get("forbidden_files", []) or []:
                    forbidden_lower.add(str(fp).lower().strip())
            elif hasattr(cst, "forbidden_files"):
                for fp in getattr(cst, "forbidden_files", []) or []:
                    forbidden_lower.add(str(fp).lower().strip())

        # 2. Extract initial target files from task requirements or finding
        for req in getattr(task, "requirements", []) or []:
            t_files = req.get("target_files", []) if isinstance(req, dict) else getattr(req, "target_files", [])
            for tf in t_files or []:
                try:
                    norm = validate_repo_relative_path(str(tf))
                    if norm.lower() in forbidden_lower:
                        excluded_files.append(norm)
                    elif norm not in target_files:
                        target_files.append(norm)
                except UnsafePathError:
                    excluded_files.append(str(tf))

        # 3. Query Repository and Symbols if DB is provided
        if db is not None and hasattr(db, "query") and getattr(db, "_is_mock_db", None) is not True:
            try:
                if repository_id:
                    repo = db.get(Repository, repository_id)
                    if repo and repo.language:
                        language = repo.language
                        if language.lower() in ("typescript", "javascript"):
                            test_command = "npm test -- --run"

                    # Fetch Repository Files
                    db_files = (
                        db.query(RepositoryFile)
                        .filter(RepositoryFile.repository_id == repository_id)
                        .limit(200)
                        .all()
                    )
                    for f in db_files:
                        try:
                            norm = validate_repo_relative_path(f.path)
                            if norm.lower() in forbidden_lower:
                                excluded_files.append(norm)
                            else:
                                repo_files.append(norm)
                                if "test" in norm.lower():
                                    existing_tests.append(norm)
                        except UnsafePathError:
                            excluded_files.append(f.path)

                    # Fetch Code Symbols
                    db_symbols = (
                        db.query(CodeSymbol)
                        .filter(CodeSymbol.repository_id == repository_id)
                        .limit(100)
                        .all()
                    )
                    sym_map = {s.id: s for s in db_symbols}
                    for s in db_symbols:
                        if s.name and s.name not in retrieved_symbols:
                            retrieved_symbols.append(s.name)

                    # Fetch Symbol Edges (callers & callees)
                    if db_symbols:
                        sym_ids = list(sym_map.keys())
                        db_edges = (
                            db.query(SymbolEdge)
                            .filter((SymbolEdge.source_id.in_(sym_ids)) | (SymbolEdge.target_id.in_(sym_ids)))
                            .limit(150)
                            .all()
                        )
                        for edge in db_edges:
                            src_name = getattr(sym_map.get(edge.source_id), "name", None)
                            tgt_name = getattr(sym_map.get(edge.target_id), "name", None)
                            if edge.edge_type in ("calls", "invokes"):
                                if src_name and src_name not in callers:
                                    callers.append(src_name)
                                if tgt_name and tgt_name not in dependencies:
                                    dependencies.append(tgt_name)
                            elif edge.edge_type in ("imports", "depends_on"):
                                if tgt_name and tgt_name not in dependencies:
                                    dependencies.append(tgt_name)

                # Link Origin Finding
                origin_finding_id = getattr(task, "origin_finding_id", None)
                if origin_finding_id:
                    finding = db.get(AnalysisFinding, origin_finding_id)
                    if finding:
                        finding_summaries.append(
                            f"[{finding.severity}] {finding.title} in {finding.file_path} "
                            f"(L{finding.start_line or 1}): {finding.description}"
                        )
                        try:
                            norm_fp = validate_repo_relative_path(finding.file_path)
                            if norm_fp.lower() not in forbidden_lower and norm_fp not in target_files:
                                target_files.insert(0, norm_fp)
                        except UnsafePathError:
                            pass
            except Exception as exc:
                logger.warning("task_context_query_warning", extra={"error": str(exc)})

        # 4. Ingest explicit file contents if passed directly
        if file_contents:
            for fpath in file_contents.keys():
                try:
                    norm = validate_repo_relative_path(fpath)
                    if norm.lower() not in forbidden_lower:
                        if norm not in repo_files:
                            repo_files.append(norm)
                        if "test" in norm.lower() and norm not in existing_tests:
                            existing_tests.append(norm)
                except UnsafePathError:
                    pass

        # 5. Autonomous Candidate Target Resolution if target_files still empty
        if not target_files and repo_files:
            corpus_parts = [getattr(task, "title", "") or "", getattr(task, "description", "") or ""]
            for req in getattr(task, "requirements", []) or []:
                desc = req.get("description", "") if isinstance(req, dict) else getattr(req, "description", "")
                if desc:
                    corpus_parts.append(desc)
            text_corpus = " ".join(corpus_parts).lower()

            for rf in repo_files:
                rf_lower = rf.lower()
                rf_base = rf.split("/")[-1].lower()
                if (rf_lower in text_corpus or (len(rf_base) > 4 and rf_base in text_corpus)) and rf not in target_files:
                    target_files.append(rf)
                    if len(target_files) >= 3:
                        break

            if not target_files:
                non_test = [f for f in repo_files if "test" not in f.lower() and not f.endswith(".md")]
                target_files = (non_test or repo_files)[:2]

        if not target_files:
            fallback = "src/main.py" if language.lower() == "python" else "src/index.ts"
            if fallback.lower() in forbidden_lower:
                fallback = "src/implementation.py"
            target_files = [fallback]

        # 6. Format Grounded Markdown Prompt Text
        prompt_lines = [
            f"### Repository Intelligence Snapshot: `{snapshot_id}` (Commit: `{base_revision or 'HEAD'}`)",
            f"- **Primary Language**: {language}",
            f"- **Detected Test Command**: `{test_command}`",
            f"- **Target Files**: {', '.join(f'`{f}`' for f in target_files)}",
            f"- **Relevant Symbols**: {', '.join(f'`{s}`' for s in retrieved_symbols[:15]) or '*(none discovered)*'}",
            f"- **Key Callers**: {', '.join(f'`{c}`' for c in callers[:10]) or '*(none)*'}",
            f"- **Dependencies**: {', '.join(f'`{d}`' for d in dependencies[:10]) or '*(none)*'}",
            f"- **Existing Test Files**: {', '.join(f'`{t}`' for t in existing_tests[:10]) or '*(none)*'}",
        ]
        if finding_summaries:
            prompt_lines.append("- **Origin Finding Context**:")
            for fs in finding_summaries:
                prompt_lines.append(f"  * {fs}")
        if excluded_files:
            prompt_lines.append(f"- **Protected / Excluded Files**: {', '.join(f'`{f}`' for f in excluded_files[:5])}")

        prompt_context_text = "\n".join(prompt_lines)

        # 7. Check Token Budget
        token_count = count_tokens(prompt_context_text)
        truncated = False
        if token_count > self.token_budget:
            prompt_context_text = prompt_context_text[: self.token_budget * 4]
            truncated = True

        return TaskContextManifest(
            snapshot_id=snapshot_id,
            commit_sha=base_revision,
            retrieved_files=repo_files[:50],
            retrieved_symbols=retrieved_symbols[:20],
            callers=callers[:10],
            dependencies=dependencies[:10],
            excluded_files=excluded_files,
            missing_dependencies=missing_dependencies,
            truncated_context=truncated,
            confidence=0.95 if not truncated else 0.80,
            architecture_rules=architecture_rules,
            existing_tests=existing_tests[:15],
            language=language,
            test_command=test_command,
            target_files=target_files,
            prompt_context_text=prompt_context_text,
        )


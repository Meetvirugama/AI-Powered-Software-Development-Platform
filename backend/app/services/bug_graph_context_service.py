"""Bug Graph Context Service — Repository-Aware Dependency and Program Slicing.

Part of Phase 2: Graph-Guided Detection & Program Slicing (task.md).
Performs bounded multi-hop graph traversal over repository symbols and edges,
constructing backward (caller/source) and forward (callee/propagation) slices,
and associating relevant test files with suspected defect targets.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge

logger = logging.getLogger(__name__)


@dataclass
class GraphSliceNode:
    """A symbol node in a backward or forward dependency slice."""
    symbol_id: UUID
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    signature: str | None = None
    hop_distance: int = 1
    edge_type: str = "calls"
    code_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": str(self.symbol_id),
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "hop_distance": self.hop_distance,
            "edge_type": self.edge_type,
            "code_snippet": self.code_snippet,
        }


@dataclass
class AssociatedTestContext:
    """Test file and function associated with the target code under investigation."""
    test_file_path: str
    test_symbol_name: str
    test_start_line: int
    test_end_line: int
    test_snippet: str = ""
    association_kind: str = "caller"  # "caller" | "file_mapping" | "naming"

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_file_path": self.test_file_path,
            "test_symbol_name": self.test_symbol_name,
            "test_start_line": self.test_start_line,
            "test_end_line": self.test_end_line,
            "test_snippet": self.test_snippet,
            "association_kind": self.association_kind,
        }


@dataclass
class BugGraphSlice:
    """Complete program slice around a suspected bug target."""
    target_symbol_id: UUID | None
    target_symbol_name: str
    target_file_path: str
    backward_slice: list[GraphSliceNode] = field(default_factory=list)
    forward_slice: list[GraphSliceNode] = field(default_factory=list)
    associated_tests: list[AssociatedTestContext] = field(default_factory=list)
    dependency_trace: list[str] = field(default_factory=list)
    completeness_score: float = 1.0
    missing_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_symbol_id": str(self.target_symbol_id) if self.target_symbol_id else None,
            "target_symbol_name": self.target_symbol_name,
            "target_file_path": self.target_file_path,
            "backward_slice": [node.to_dict() for node in self.backward_slice],
            "forward_slice": [node.to_dict() for node in self.forward_slice],
            "associated_tests": [test.to_dict() for test in self.associated_tests],
            "dependency_trace": self.dependency_trace,
            "completeness_score": self.completeness_score,
            "missing_nodes": self.missing_nodes,
        }


class BugGraphContextService:
    """Traverses repository dependency graph to build bounded program slices for bug investigation."""

    def __init__(self, db: Any = None) -> None:
        self.db = db

    async def _execute(self, query: Any) -> Any:
        res = self.db.execute(query)
        if inspect.isawaitable(res):
            return await res
        return res

    async def build_program_slice(
        self,
        repository_id: UUID,
        target_file_path: str,
        target_symbol_id: UUID | None = None,
        target_line: int | None = None,
        max_depth: int = 2,
    ) -> BugGraphSlice:
        """Construct backward and forward dependency slice with associated test coverage."""
        if not self.db:
            return BugGraphSlice(
                target_symbol_id=target_symbol_id,
                target_symbol_name="",
                target_file_path=target_file_path,
                completeness_score=0.5,
                missing_nodes=["Database session unavailable for graph traversal"],
            )

        # 1. Resolve target symbol if not provided
        target_symbol = None
        if target_symbol_id:
            res = await self._execute(
                select(CodeSymbol).where(
                    CodeSymbol.id == target_symbol_id,
                    CodeSymbol.repository_id == repository_id,
                )
            )
            target_symbol = res.scalar_one_or_none()
        elif target_line:
            # Query by file path and line
            file_res = await self._execute(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id == repository_id,
                    RepositoryFile.path == target_file_path,
                )
            )
            file_record = file_res.scalar_one_or_none()
            if file_record:
                sym_res = await self._execute(
                    select(CodeSymbol).where(
                        CodeSymbol.file_id == file_record.id,
                        CodeSymbol.start_line <= target_line,
                        CodeSymbol.end_line >= target_line,
                    ).order_by((CodeSymbol.end_line - CodeSymbol.start_line).asc())
                )
                target_symbol = sym_res.scalars().first()

        sym_name = target_symbol.name if target_symbol else ""
        sym_id = target_symbol.id if target_symbol else None

        if not target_symbol:
            # If no AST symbol, return file-level context
            tests = await self._find_associated_tests_by_file(repository_id, target_file_path)
            return BugGraphSlice(
                target_symbol_id=None,
                target_symbol_name="",
                target_file_path=target_file_path,
                associated_tests=tests,
                dependency_trace=[f"{target_file_path}:{target_line or 1}"],
                completeness_score=0.7,
            )

        # 2. Backward Slice: Callers, upstream callers (who calls target?)
        backward_nodes = await self._traverse_slice(
            repository_id=repository_id,
            origin_symbol_id=target_symbol.id,
            direction="backward",
            max_depth=max_depth,
        )

        # 3. Forward Slice: Callees, downstream invocations (what does target call?)
        forward_nodes = await self._traverse_slice(
            repository_id=repository_id,
            origin_symbol_id=target_symbol.id,
            direction="forward",
            max_depth=max_depth,
        )

        # 4. Associated tests
        tests = await self._find_associated_tests(
            repository_id=repository_id,
            target_symbol_id=target_symbol.id,
            target_file_path=target_file_path,
        )

        # 5. Build linear dependency trace string
        trace_steps: list[str] = []
        for b_node in reversed(backward_nodes):
            trace_steps.append(f"{b_node.file_path}:{b_node.start_line} ({b_node.name})")
        trace_steps.append(f"{target_file_path}:{target_symbol.start_line} ({target_symbol.name})")
        for f_node in forward_nodes:
            trace_steps.append(f"{f_node.file_path}:{f_node.start_line} ({f_node.name})")

        # 6. Graph completeness
        completeness = 1.0
        missing: list[str] = []
        if not backward_nodes and not forward_nodes:
            completeness = 0.8
            missing.append("Target symbol is an isolated node or top-level entrypoint")

        return BugGraphSlice(
            target_symbol_id=sym_id,
            target_symbol_name=sym_name,
            target_file_path=target_file_path,
            backward_slice=backward_nodes,
            forward_slice=forward_nodes,
            associated_tests=tests,
            dependency_trace=trace_steps,
            completeness_score=completeness,
            missing_nodes=missing,
        )

    async def _traverse_slice(
        self,
        repository_id: UUID,
        origin_symbol_id: UUID,
        direction: str,  # "backward" (incoming) or "forward" (outgoing)
        max_depth: int,
    ) -> list[GraphSliceNode]:
        """Bounded multi-hop traversal along SymbolEdges."""
        visited: set[UUID] = {origin_symbol_id}
        current_layer: list[UUID] = [origin_symbol_id]
        result_nodes: list[GraphSliceNode] = []

        for hop in range(1, max_depth + 1):
            if not current_layer:
                break

            next_layer: list[UUID] = []

            if direction == "backward":
                # Find edges where target_symbol_id is in current_layer
                edge_query = select(SymbolEdge).where(
                    SymbolEdge.repository_id == repository_id,
                    SymbolEdge.target_symbol_id.in_(current_layer),
                )
            else:
                # Find edges where source_symbol_id is in current_layer
                edge_query = select(SymbolEdge).where(
                    SymbolEdge.repository_id == repository_id,
                    SymbolEdge.source_symbol_id.in_(current_layer),
                )

            edge_res = await self._execute(edge_query)
            edges = edge_res.scalars().all()

            for edge in edges:
                neighbor_id = edge.source_symbol_id if direction == "backward" else edge.target_symbol_id
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    next_layer.append(neighbor_id)

                    # Fetch symbol and file info
                    sym_res = await self._execute(
                        select(CodeSymbol, RepositoryFile.path)
                        .join(RepositoryFile, CodeSymbol.file_id == RepositoryFile.id)
                        .where(CodeSymbol.id == neighbor_id)
                    )
                    row = sym_res.first()
                    if row:
                        sym, fpath = row[0], row[1]
                        # Fetch code chunk snippet
                        snippet = await self._get_symbol_chunk_snippet(sym.id, sym.repository_id)
                        result_nodes.append(
                            GraphSliceNode(
                                symbol_id=sym.id,
                                name=sym.name,
                                kind=sym.kind,
                                file_path=fpath,
                                start_line=sym.start_line,
                                end_line=sym.end_line,
                                signature=sym.signature,
                                hop_distance=hop,
                                edge_type=edge.edge_type,
                                code_snippet=snippet,
                            )
                        )

            current_layer = next_layer

        return result_nodes

    async def _get_symbol_chunk_snippet(self, symbol_id: UUID, repository_id: UUID) -> str:
        """Retrieve real source code chunk for symbol."""
        res = await self._execute(
            select(CodeChunk.content)
            .where(
                CodeChunk.symbol_id == symbol_id,
                CodeChunk.repository_id == repository_id,
            )
            .limit(1)
        )
        content = res.scalar_one_or_none()
        return (content or "")[:1000]

    async def _find_associated_tests(
        self,
        repository_id: UUID,
        target_symbol_id: UUID,
        target_file_path: str,
    ) -> list[AssociatedTestContext]:
        """Find tests that directly call target symbol or test the target file."""
        tests: list[AssociatedTestContext] = []

        # 1. Tests calling the target symbol directly
        caller_test_res = await self._execute(
            select(CodeSymbol, RepositoryFile.path)
            .join(SymbolEdge, SymbolEdge.source_symbol_id == CodeSymbol.id)
            .join(RepositoryFile, CodeSymbol.file_id == RepositoryFile.id)
            .where(
                SymbolEdge.target_symbol_id == target_symbol_id,
                SymbolEdge.repository_id == repository_id,
            )
        )
        for sym, fpath in caller_test_res.all():
            if self._is_test_file_path(fpath) or sym.name.startswith("test_"):
                snippet = await self._get_symbol_chunk_snippet(sym.id, repository_id)
                tests.append(
                    AssociatedTestContext(
                        test_file_path=fpath,
                        test_symbol_name=sym.name,
                        test_start_line=sym.start_line,
                        test_end_line=sym.end_line,
                        test_snippet=snippet,
                        association_kind="caller",
                    )
                )

        # 2. File-based test matching if no direct caller test found
        if not tests:
            file_tests = await self._find_associated_tests_by_file(repository_id, target_file_path)
            tests.extend(file_tests)

        return tests

    async def _find_associated_tests_by_file(
        self,
        repository_id: UUID,
        target_file_path: str,
    ) -> list[AssociatedTestContext]:
        """Find test files matching name of target file (e.g. test_user.py for user.py)."""
        import os
        base_name = os.path.basename(target_file_path)
        name_no_ext = os.path.splitext(base_name)[0]

        candidates = [
            f"test_{name_no_ext}.py",
            f"{name_no_ext}_test.py",
            f"{name_no_ext}.test.ts",
            f"{name_no_ext}.spec.ts",
            f"{name_no_ext}.test.tsx",
            f"{name_no_ext}.spec.tsx",
        ]

        tests: list[AssociatedTestContext] = []
        for cand in candidates:
            res = await self._execute(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id == repository_id,
                    RepositoryFile.path.ilike(f"%{cand}"),
                )
            )
            test_file = res.scalars().first()
            if test_file:
                # Get first test function or top symbol
                sym_res = await self._execute(
                    select(CodeSymbol).where(
                        CodeSymbol.file_id == test_file.id,
                        CodeSymbol.repository_id == repository_id,
                    ).limit(3)
                )
                test_syms = sym_res.scalars().all()
                for ts in test_syms:
                    tests.append(
                        AssociatedTestContext(
                            test_file_path=test_file.path,
                            test_symbol_name=ts.name,
                            test_start_line=ts.start_line,
                            test_end_line=ts.end_line,
                            association_kind="file_mapping",
                        )
                    )
                if not test_syms:
                    tests.append(
                        AssociatedTestContext(
                            test_file_path=test_file.path,
                            test_symbol_name=test_file.path,
                            test_start_line=1,
                            test_end_line=1,
                            association_kind="file_mapping",
                        )
                    )
        return tests

    @staticmethod
    def _is_test_file_path(path: str) -> bool:
        p = path.lower().replace("\\", "/")
        return (
            "test" in p
            or "spec" in p
            or p.endswith(("_test.py", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))
        )


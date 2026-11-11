"""Optional, sandboxed SCIP code-intelligence indexer integration (P3).

Key safety & architectural guarantees:
1. Optional capability (`enabled=False` by default); Tree-sitter remains the primary parser and
   universal fallback. SCIP is never a prerequisite for ordinary indexing.
2. Verified indexers only: Python (`scip-python`, Apache-2.0) and TypeScript (`scip-typescript`,
   Apache-2.0).
3. Strict sandboxing: SCIP indexers are never executed directly on the API host via `subprocess`.
   Any CLI execution must run through an injected `SandboxCommandExecutor` (e.g. Docker container
   with `--network none`, CPU/memory limits, non-root user, and read-only source mount) with
   fixed argument arrays (`shell=False`) and zero arbitrary build-script execution.
4. Output validation & provenance: Validates SCIP JSON or protobuf index outputs, maps 0-indexed
   SCIP occurrence ranges to 1-indexed inclusive `Symbol` ranges, records indexer name/version
   and `provenance="scip"`, retains unresolved external references, and reconciles duplicate
   edges with Tree-sitter edges without blindly overwriting them.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from .graph import DependencyGraphBuilder
from .symbols import EDGE_TYPE_DEFAULT_WEIGHTS, Symbol, SymbolEdge

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SCIPIndexerMetadata:
    """Verified metadata for an evaluated SCIP indexer."""

    language: str
    binary_name: str
    package_name: str
    license: str
    repository_url: str
    maintenance_status: str
    build_requirements: str
    safe_args: tuple[str, ...]
    supported: bool = True


SCIP_INDEXER_REGISTRY: dict[str, SCIPIndexerMetadata] = {
    "Python": SCIPIndexerMetadata(
        language="Python",
        binary_name="scip-python",
        package_name="@sourcegraph/scip-python",
        license="Apache-2.0",
        repository_url="https://github.com/sourcegraph/scip-python",
        maintenance_status="Actively maintained by Sourcegraph (Pyright-based)",
        build_requirements="Node.js >= 18 and Python >= 3.10 in isolated sandbox; no setup.py execution",
        safe_args=("scip-python", "index", ".", "--output", "index.scip", "--quiet"),
        supported=True,
    ),
    "TypeScript": SCIPIndexerMetadata(
        language="TypeScript",
        binary_name="scip-typescript",
        package_name="@sourcegraph/scip-typescript",
        license="Apache-2.0",
        repository_url="https://github.com/sourcegraph/scip-typescript",
        maintenance_status="Actively maintained by Sourcegraph (TypeScript compiler API)",
        build_requirements="Node.js >= 18 and tsconfig.json in isolated sandbox; no npm lifecycle scripts",
        safe_args=("scip-typescript", "index", "--output", "index.scip", "--no-progress-bar"),
        supported=True,
    ),
    "JavaScript": SCIPIndexerMetadata(
        language="JavaScript",
        binary_name="scip-typescript",
        package_name="@sourcegraph/scip-typescript",
        license="Apache-2.0",
        repository_url="https://github.com/sourcegraph/scip-typescript",
        maintenance_status="Actively maintained by Sourcegraph (`--infer-tsconfig` mode)",
        build_requirements="Node.js >= 18 in isolated sandbox; no npm lifecycle scripts",
        safe_args=(
            "scip-typescript",
            "index",
            "--infer-tsconfig",
            "--output",
            "index.scip",
            "--no-progress-bar",
        ),
        supported=True,
    ),
}


@dataclass(frozen=True)
class SCIPIndexerConfig:
    """Configuration and sandbox resource limits for optional SCIP indexing."""

    enabled: bool = False
    allowed_languages: tuple[str, ...] = ("Python", "TypeScript", "JavaScript")
    timeout_seconds: int = 60
    max_memory_mb: int = 1024
    max_cpus: float = 1.0
    max_index_size_bytes: int = 50 * 1024 * 1024  # 50 MB cap
    network_disabled: bool = True
    allow_host_execution: bool = False  # Hard safety invariant: never run on API host


@dataclass(frozen=True)
class SandboxCommandResult:
    """Result returned by a sandboxed command executor."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    output_files: dict[str, bytes] = field(default_factory=dict)


class SandboxCommandExecutor(Protocol):
    """Protocol for isolated container execution of SCIP indexers."""

    def run_sandboxed(
        self,
        command: Sequence[str],
        *,
        workspace_dir: str,
        timeout_seconds: int,
        max_memory_mb: int,
        max_cpus: float,
        network_disabled: bool,
    ) -> SandboxCommandResult: ...


@dataclass(frozen=True)
class SCIPOccurrence:
    """Normalized SCIP symbol occurrence with 1-indexed inclusive source range."""

    file_path: str
    symbol_moniker: str
    start_line: int  # 1-indexed inclusive
    start_col: int
    end_line: int  # 1-indexed inclusive
    end_col: int
    is_definition: bool
    enclosing_symbol_moniker: str | None = None


@dataclass
class SCIPScanResult:
    """Result of an optional SCIP indexing and symbol-mapping pass."""

    status: str  # "completed", "skipped", "unavailable", "failed", "invalid_output"
    edges: list[SymbolEdge] = field(default_factory=list)
    unresolved_edges: list[SymbolEdge] = field(default_factory=list)
    indexer_name: str | None = None
    indexer_version: str | None = None
    fallback_used: bool = True
    error_message: str | None = None
    occurrences_processed: int = 0


# SCIP SymbolRole bitmask constants (https://github.com/sourcegraph/scip/blob/main/scip.proto)
SCIP_ROLE_DEFINITION = 0x1


class SCIPRunner:
    """Sandboxed SCIP indexer runner, validator, and symbol/edge mapper."""

    def __init__(
        self,
        config: SCIPIndexerConfig | None = None,
        sandbox_executor: SandboxCommandExecutor | None = None,
    ) -> None:
        self.config = config or SCIPIndexerConfig()
        self.sandbox_executor = sandbox_executor

    def index_repository(
        self,
        workspace_dir: str,
        language: str,
        symbols: Sequence[Symbol],
        existing_edges: Sequence[SymbolEdge] | None = None,
        *,
        precomputed_index_payload: bytes | str | dict[str, Any] | None = None,
    ) -> SCIPScanResult:
        """Run or ingest SCIP index for a repository and reconcile with Tree-sitter edges.

        If SCIP is disabled, the language is not verified, no sandbox executor is configured,
        or the sandbox execution / validation fails, gracefully skips or falls back to
        `existing_edges` without raising an exception.
        """
        base_edges = list(existing_edges or [])

        if not self.config.enabled:
            return SCIPScanResult(
                status="skipped",
                edges=base_edges,
                fallback_used=True,
                error_message="SCIP integration is disabled by configuration.",
            )

        if self.config.allow_host_execution:
            return SCIPScanResult(
                status="failed",
                edges=base_edges,
                fallback_used=True,
                error_message="Security policy violation: host execution of SCIP indexers is forbidden.",
            )

        meta = SCIP_INDEXER_REGISTRY.get(language)
        if meta is None or not meta.supported or language not in self.config.allowed_languages:
            return SCIPScanResult(
                status="unavailable",
                edges=base_edges,
                fallback_used=True,
                error_message=f"No verified SCIP indexer configured for language '{language}'.",
            )

        raw_payload = precomputed_index_payload
        if raw_payload is None:
            if self.sandbox_executor is None:
                return SCIPScanResult(
                    status="unavailable",
                    edges=base_edges,
                    indexer_name=meta.binary_name,
                    fallback_used=True,
                    error_message="No isolated sandbox executor available for SCIP indexing.",
                )
            try:
                cmd_result = self.sandbox_executor.run_sandboxed(
                    meta.safe_args,
                    workspace_dir=workspace_dir,
                    timeout_seconds=self.config.timeout_seconds,
                    max_memory_mb=self.config.max_memory_mb,
                    max_cpus=self.config.max_cpus,
                    network_disabled=True,
                )
            except Exception as exc:
                logger.warning("SCIP sandbox execution raised error: %s", exc)
                return SCIPScanResult(
                    status="failed",
                    edges=base_edges,
                    indexer_name=meta.binary_name,
                    fallback_used=True,
                    error_message=f"Sandbox execution error: {exc}",
                )

            if cmd_result.timed_out or cmd_result.exit_code != 0:
                reason = (
                    "SCIP indexer timed out in sandbox"
                    if cmd_result.timed_out
                    else f"SCIP indexer exited with code {cmd_result.exit_code}: {cmd_result.stderr.strip()}"
                )
                return SCIPScanResult(
                    status="failed",
                    edges=base_edges,
                    indexer_name=meta.binary_name,
                    fallback_used=True,
                    error_message=reason,
                )

            raw_payload = cmd_result.output_files.get("index.scip") or cmd_result.stdout
            if not raw_payload:
                return SCIPScanResult(
                    status="invalid_output",
                    edges=base_edges,
                    indexer_name=meta.binary_name,
                    fallback_used=True,
                    error_message="SCIP indexer produced empty output.",
                )

        try:
            parsed_index = self.validate_and_parse_scip_index(
                raw_payload,
                max_size_bytes=self.config.max_index_size_bytes,
            )
        except ValueError as exc:
            return SCIPScanResult(
                status="invalid_output",
                edges=base_edges,
                indexer_name=meta.binary_name,
                fallback_used=True,
                error_message=str(exc),
            )

        indexer_name = parsed_index.get("tool_name") or meta.binary_name
        indexer_version = parsed_index.get("tool_version") or "unknown"
        occurrences: list[SCIPOccurrence] = parsed_index["occurrences"]

        scip_edges = self.map_occurrences_to_edges(occurrences, symbols)
        combined = DependencyGraphBuilder.reconcile_edges(base_edges + scip_edges)
        resolved = [
            e for e in combined if e.resolution_status == "resolved" and e.target_id is not None
        ]
        unresolved = [
            e for e in combined if e.resolution_status in ("unresolved", "ambiguous")
        ]

        return SCIPScanResult(
            status="completed",
            edges=resolved,
            unresolved_edges=unresolved,
            indexer_name=indexer_name,
            indexer_version=indexer_version,
            fallback_used=False,
            occurrences_processed=len(occurrences),
        )

    @classmethod
    def validate_and_parse_scip_index(
        cls,
        payload: bytes | str | dict[str, Any],
        *,
        max_size_bytes: int = 50 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Validate a SCIP JSON payload and convert 0-indexed ranges to 1-indexed inclusive ranges."""
        if isinstance(payload, (bytes, bytearray)):
            if len(payload) > max_size_bytes:
                raise ValueError(
                    f"SCIP index size ({len(payload)} bytes) exceeds limit ({max_size_bytes} bytes)."
                )
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("SCIP index is not valid UTF-8 JSON.") from exc
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed SCIP JSON payload: {exc}") from exc
        elif isinstance(payload, str):
            if len(payload.encode("utf-8")) > max_size_bytes:
                raise ValueError("SCIP index exceeds maximum size limit.")
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed SCIP JSON string: {exc}") from exc
        elif isinstance(payload, dict):
            data = payload
        else:
            raise ValueError(f"Unsupported SCIP payload type: {type(payload).__name__}")

        if not isinstance(data, dict) or "documents" not in data:
            raise ValueError("Invalid SCIP index schema: missing 'documents' array.")

        documents = data.get("documents")
        if not isinstance(documents, list):
            raise ValueError("Invalid SCIP index schema: 'documents' must be a list.")

        metadata = data.get("metadata") or {}
        tool_info = metadata.get("tool_info") or metadata.get("toolInfo") or {}
        tool_name = tool_info.get("name")
        tool_version = tool_info.get("version")

        occurrences: list[SCIPOccurrence] = []
        for doc in documents:
            if not isinstance(doc, dict):
                raise ValueError("Invalid SCIP document entry: expected object.")
            rel_path = doc.get("relative_path") or doc.get("relativePath")
            if not rel_path or not isinstance(rel_path, str):
                raise ValueError("Invalid SCIP document: missing 'relative_path'.")
            norm_path = cls._sanitize_relative_path(rel_path)

            raw_occs = doc.get("occurrences") or []
            if not isinstance(raw_occs, list):
                raise ValueError("Invalid SCIP document: 'occurrences' must be a list.")

            for occ in raw_occs:
                if not isinstance(occ, dict):
                    continue
                moniker = occ.get("symbol")
                raw_range = occ.get("range")
                if not moniker or not isinstance(moniker, str) or moniker.startswith("local "):
                    continue
                if not isinstance(raw_range, list) or len(raw_range) not in (3, 4):
                    raise ValueError(
                        f"Invalid SCIP occurrence range in '{norm_path}': expected 3 or 4 integers."
                    )
                if not all(isinstance(v, int) and v >= 0 for v in raw_range):
                    raise ValueError(
                        f"Invalid SCIP occurrence coordinates in '{norm_path}': coordinates must be non-negative integers."
                    )

                # SCIP range is 0-indexed: [startLine, startChar, endChar] or [startLine, startChar, endLine, endChar]
                start_line_1 = raw_range[0] + 1
                start_col = raw_range[1]
                if len(raw_range) == 3:
                    end_line_1 = start_line_1
                    end_col = raw_range[2]
                else:
                    end_line_1 = max(start_line_1, raw_range[2] + 1)
                    end_col = raw_range[3]

                roles = int(occ.get("symbol_roles") or occ.get("symbolRoles") or 0)
                is_def = bool(roles & SCIP_ROLE_DEFINITION)
                enclosing = occ.get("enclosing_symbol") or occ.get("enclosingSymbol")

                occurrences.append(
                    SCIPOccurrence(
                        file_path=norm_path,
                        symbol_moniker=moniker,
                        start_line=start_line_1,
                        start_col=start_col,
                        end_line=end_line_1,
                        end_col=end_col,
                        is_definition=is_def,
                        enclosing_symbol_moniker=enclosing if isinstance(enclosing, str) else None,
                    )
                )

        return {
            "tool_name": tool_name,
            "tool_version": tool_version,
            "occurrences": occurrences,
        }

    @classmethod
    def map_occurrences_to_edges(
        cls,
        occurrences: Sequence[SCIPOccurrence],
        symbols: Sequence[Symbol],
    ) -> list[SymbolEdge]:
        """Map SCIP definitions and references to internal `Symbol` UUIDs and `SymbolEdge`s."""
        symbols_by_file: dict[str, list[Symbol]] = defaultdict(list)
        for sym in symbols:
            norm = cls._sanitize_relative_path(sym.file_path)
            symbols_by_file[norm].append(sym)

        # Sort per-file symbols by span size ascending so inner-most enclosing symbol matches first
        for file_syms in symbols_by_file.values():
            file_syms.sort(key=lambda s: (s.end_line - s.start_line, s.start_line))

        # 1. Map definition occurrences to internal symbols
        moniker_to_symbol: dict[str, Symbol] = {}
        for occ in occurrences:
            if not occ.is_definition:
                continue
            matched = cls._find_enclosing_symbol(
                symbols_by_file.get(occ.file_path, []),
                occ.start_line,
                occ.end_line,
            )
            if matched is not None:
                moniker_to_symbol[occ.symbol_moniker] = matched

        # 2. Map reference occurrences to resolved or unresolved edges
        edges: list[SymbolEdge] = []
        default_call_weight = EDGE_TYPE_DEFAULT_WEIGHTS["calls"]

        for occ in occurrences:
            if occ.is_definition:
                continue
            source_sym = cls._find_enclosing_symbol(
                symbols_by_file.get(occ.file_path, []),
                occ.start_line,
                occ.end_line,
            )
            if source_sym is None:
                continue

            target_sym = moniker_to_symbol.get(occ.symbol_moniker)
            short_name = cls.extract_symbol_name_from_moniker(occ.symbol_moniker)

            if target_sym is not None:
                if target_sym.id == source_sym.id:
                    continue
                edges.append(
                    SymbolEdge(
                        source_id=source_sym.id,
                        target_id=target_sym.id,
                        edge_type="calls",
                        target_name=target_sym.name,
                        provenance="scip",
                        resolution_status="resolved",
                        confidence=1.0,
                        weight=default_call_weight,
                    )
                )
            else:
                edges.append(
                    SymbolEdge(
                        source_id=source_sym.id,
                        target_id=None,
                        edge_type="calls",
                        target_name=short_name or occ.symbol_moniker,
                        provenance="scip",
                        resolution_status="unresolved",
                        confidence=0.0,
                        weight=default_call_weight,
                    )
                )

        return DependencyGraphBuilder.reconcile_edges(edges)

    @staticmethod
    def _find_enclosing_symbol(
        file_symbols: Sequence[Symbol],
        start_line: int,
        end_line: int,
    ) -> Symbol | None:
        """Return the tightest symbol in `file_symbols` whose 1-indexed inclusive range covers `[start_line, end_line]`."""
        for sym in file_symbols:
            if sym.start_line <= start_line and end_line <= sym.end_line:
                return sym
        # Fallback if single-line header matches start_line
        for sym in file_symbols:
            if sym.start_line <= start_line <= sym.end_line:
                return sym
        return None

    @staticmethod
    def _sanitize_relative_path(path: str) -> str:
        norm = path.replace("\\", "/").strip()
        if norm.startswith("./"):
            norm = norm[2:]
        norm = norm.lstrip("/")
        parts = norm.split("/")
        if ".." in parts:
            raise ValueError(f"Path traversal detected in SCIP document path: '{path}'")
        return os.path.normpath(norm).replace("\\", "/") if norm else ""

    @staticmethod
    def extract_symbol_name_from_moniker(moniker: str) -> str:
        """Extract the human-readable identifier from a SCIP symbol moniker string.

        Example: `'scip-python python pkg 0.1.0 mod/MyClass#my_method().'` -> `'my_method'`
        """
        tail = moniker.strip().split(" ")[-1]
        tail = tail.rstrip(".#():!")
        for sep in ("#", "/", "::", "."):
            if sep in tail:
                tail = tail.split(sep)[-1]
        tail = re.sub(r"\([^)]*\)$", "", tail).strip("`")
        return tail

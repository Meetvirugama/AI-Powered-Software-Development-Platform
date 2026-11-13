"""Repository-scoped weighted PageRank symbol importance ranker (P2).

Computes deterministic, repository-scoped PageRank importance scores over resolved
dependency graph edges:
- Edge direction: `source_id -> target_id` means `source` depends on / calls / inherits /
  imports `target`, so authority flows from `source` to `target`.
- Supports per-edge-type weights (`calls`: 1.0, `inherits`: 1.2, `implements`: 1.1, `imports`: 0.6).
- Deduplicates parallel edges between the same `(source_id, target_id)` by summing weights
   across distinct relationship types and taking max weight for identical relationship types.
- Handles empty graphs, single-node graphs, isolated symbols, cyclic graphs, and dangling
  nodes (sinks with no outgoing edges redistribute their mass via personalization/damping).
- Discounts symbols located in generated, vendor, third-party, or build directories via
  configurable personalization & post-ranking multipliers so core repository symbols rank first.
- Normalizes final scores to `[0.0, 1.0]` (max-normalized with deterministic tie stability).
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from .symbols import EDGE_TYPE_DEFAULT_WEIGHTS, Symbol, SymbolEdge

DEFAULT_VENDOR_GENERATED_PATTERNS: tuple[str, ...] = (
    "vendor/",
    "node_modules/",
    "third_party/",
    "dist/",
    "build/",
    ".next/",
    "__pycache__/",
    ".pb.go",
    "_pb2.py",
    ".generated.",
    ".min.js",
)


@dataclass(frozen=True)
class PageRankConfig:
    """Configuration parameters for weighted symbol PageRank."""

    damping_factor: float = 0.85
    max_iterations: int = 100
    tolerance: float = 1e-6
    edge_type_weights: dict[str, float] = field(
        default_factory=lambda: dict(EDGE_TYPE_DEFAULT_WEIGHTS)
    )
    vendor_discount_factor: float = 0.25
    vendor_patterns: tuple[str, ...] = DEFAULT_VENDOR_GENERATED_PATTERNS
    normalize_to_unit_interval: bool = True


@dataclass
class PageRankMetrics:
    """Diagnostic and benchmark metrics from a PageRank run."""

    node_count: int = 0
    resolved_edge_count: int = 0
    deduplicated_edge_count: int = 0
    ignored_unresolved_count: int = 0
    dangling_node_count: int = 0
    isolated_node_count: int = 0
    iterations: int = 0
    converged: bool = True
    residual: float = 0.0
    duration_ms: float = 0.0


def is_vendor_or_generated_path(
    file_path: str,
    patterns: Sequence[str] = DEFAULT_VENDOR_GENERATED_PATTERNS,
) -> bool:
    """Return True if `file_path` matches a known vendor, build, or generated file pattern."""
    norm = file_path.replace("\\", "/").lower()
    for pat in patterns:
        p = pat.lower()
        if p.startswith("."):
            if norm.endswith(p) or f"/{p}" in norm or p in norm:
                return True
        elif p.endswith("/"):
            if norm.startswith(p) or f"/{p}" in norm:
                return True
        elif p in norm:
            return True
    return False


class SymbolImportanceRanker:
    """Computes deterministic weighted PageRank over repository symbols."""

    def __init__(self, config: PageRankConfig | None = None) -> None:
        self.config = config or PageRankConfig()
        self._last_metrics = PageRankMetrics()

    @property
    def last_metrics(self) -> PageRankMetrics:
        return self._last_metrics

    def rank_symbols(
        self,
        symbols: Sequence[Symbol],
        edges: Sequence[SymbolEdge],
    ) -> dict[UUID, float]:
        """Compute importance scores for `symbols` and mutate `sym.importance_score` in-place.

        Returns a mapping `{symbol_id: importance_score}` for all symbols in `symbols`.
        Only edges whose `source_id` and `target_id` belong to `symbols` and whose
        `resolution_status == "resolved"` participate in authority transfer, guaranteeing
        strict repository isolation even if edges from multiple repositories are passed.
        """
        t0 = time.perf_counter()
        n = len(symbols)
        if n == 0:
            self._last_metrics = PageRankMetrics(
                node_count=0,
                converged=True,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return {}

        # Sort symbols deterministically by UUID string so floating-point accumulation order is 100% stable
        ordered_symbols = sorted(symbols, key=lambda s: str(s.id))
        node_ids = [s.id for s in ordered_symbols]
        id_to_idx = {sid: idx for idx, sid in enumerate(node_ids)}

        if n == 1:
            only_sym = ordered_symbols[0]
            score = (
                round(self.config.vendor_discount_factor, 6)
                if is_vendor_or_generated_path(only_sym.file_path, self.config.vendor_patterns)
                else 1.0
            )
            only_sym.importance_score = score
            self._last_metrics = PageRankMetrics(
                node_count=1,
                isolated_node_count=1,
                dangling_node_count=1,
                iterations=1,
                converged=True,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return {only_sym.id: score}

        # 1. Filter to repository-scoped resolved edges and deduplicate
        # Key: (src_idx, dst_idx, edge_type) -> max weight
        pair_type_weight: dict[tuple[int, int, str], float] = {}
        resolved_edge_count = 0
        ignored_unresolved = 0

        for edge in edges:
            if edge.resolution_status != "resolved" or edge.target_id is None:
                ignored_unresolved += 1
                continue
            src_idx = id_to_idx.get(edge.source_id)
            dst_idx = id_to_idx.get(edge.target_id)
            if src_idx is None or dst_idx is None or src_idx == dst_idx:
                continue

            resolved_edge_count += 1
            base_w = self.config.edge_type_weights.get(
                edge.edge_type,
                EDGE_TYPE_DEFAULT_WEIGHTS.get(edge.edge_type, 1.0),
            )
            effective_w = max(0.0, base_w * max(0.0, float(edge.confidence)))
            if effective_w <= 0.0:
                continue
            key = (src_idx, dst_idx, edge.edge_type)
            if key not in pair_type_weight or effective_w > pair_type_weight[key]:
                pair_type_weight[key] = effective_w

        # Collapse across edge_types per (src_idx, dst_idx)
        pair_weights: dict[tuple[int, int], float] = defaultdict(float)
        for (src_idx, dst_idx, _etype), w in pair_type_weight.items():
            pair_weights[(src_idx, dst_idx)] += w

        outgoing: list[list[tuple[int, float]]] = [[] for _ in range(n)]
        out_weight_sum: list[float] = [0.0] * n
        in_degree: list[int] = [0] * n

        for (src_idx, dst_idx), w in sorted(pair_weights.items()):
            outgoing[src_idx].append((dst_idx, w))
            out_weight_sum[src_idx] += w
            in_degree[dst_idx] += 1

        dangling_indices = [i for i in range(n) if out_weight_sum[i] == 0.0]
        isolated_count = sum(
            1 for i in range(n) if out_weight_sum[i] == 0.0 and in_degree[i] == 0
        )

        # 2. Personalization vector (discounts vendor/generated files)
        personalization = [
            self.config.vendor_discount_factor
            if is_vendor_or_generated_path(sym.file_path, self.config.vendor_patterns)
            else 1.0
            for sym in ordered_symbols
        ]
        p_sum = sum(personalization)
        if p_sum > 0.0:
            personalization = [p / p_sum for p in personalization]
        else:
            personalization = [1.0 / n] * n

        # 3. Power iteration
        d = self.config.damping_factor
        scores = list(personalization)
        converged = False
        residual = 0.0
        iterations = 0

        for it in range(1, self.config.max_iterations + 1):
            iterations = it
            dangling_mass = sum(scores[i] for i in dangling_indices)
            base_contrib = (1.0 - d) + d * dangling_mass
            next_scores = [base_contrib * personalization[i] for i in range(n)]

            for src_idx in range(n):
                total_w = out_weight_sum[src_idx]
                if total_w <= 0.0:
                    continue
                src_factor = d * (scores[src_idx] / total_w)
                for dst_idx, w in outgoing[src_idx]:
                    next_scores[dst_idx] += src_factor * w

            # L1 residual check
            residual = sum(abs(next_scores[i] - scores[i]) for i in range(n))
            scores = next_scores
            if residual <= self.config.tolerance:
                converged = True
                break

        # Apply post-iteration discount to vendor/generated symbols so a heavily-connected vendor
        # helper does not eclipse core domain symbols
        for i, sym in enumerate(ordered_symbols):
            if is_vendor_or_generated_path(sym.file_path, self.config.vendor_patterns):
                scores[i] *= self.config.vendor_discount_factor

        # 4. Normalize to [0.0, 1.0]
        if self.config.normalize_to_unit_interval:
            max_score = max(scores) if scores else 0.0
            if max_score > 0.0 and not math.isclose(max_score, 0.0):
                scores = [round(min(1.0, max(0.0, s / max_score)), 6) for s in scores]
            else:
                scores = [0.0] * n
        else:
            total = sum(scores)
            if total > 0.0:
                scores = [round(s / total, 6) for s in scores]

        result: dict[UUID, float] = {}
        for i, sym in enumerate(ordered_symbols):
            sym.importance_score = scores[i]
            result[sym.id] = scores[i]

        self._last_metrics = PageRankMetrics(
            node_count=n,
            resolved_edge_count=resolved_edge_count,
            deduplicated_edge_count=len(pair_weights),
            ignored_unresolved_count=ignored_unresolved,
            dangling_node_count=len(dangling_indices),
            isolated_node_count=isolated_count,
            iterations=iterations,
            converged=converged,
            residual=residual,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )
        return result


def compute_symbol_pagerank(
    symbols: Sequence[Symbol],
    edges: Sequence[SymbolEdge],
    config: PageRankConfig | None = None,
) -> tuple[dict[UUID, float], PageRankMetrics]:
    """Convenience function returning `(scores_by_symbol_id, metrics)`."""
    ranker = SymbolImportanceRanker(config=config)
    scores = ranker.rank_symbols(symbols, edges)
    return scores, ranker.last_metrics

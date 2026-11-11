import hashlib
from typing import Any, Iterable
import uuid
from uuid import UUID

try:
    from scanner.symbols import Symbol
except ImportError:
    from backend.scanner.symbols import Symbol

from app.core.secret_redaction import redact

from .models import Chunk


MAX_CHUNK_TOKENS = 512
SMALL_SIBLING_TOKEN_THRESHOLD = 128
CHUNKER_VERSION = "v2_cast"
_CHUNK_ID_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
_CONTAINER_SYMBOL_KINDS: frozenset[str] = frozenset({"class", "interface", "struct"})
_CALLABLE_SYMBOL_KINDS: frozenset[str] = frozenset({"function", "method"})


def compute_stable_chunk_id(
    *,
    repository_id: UUID,
    file_id: UUID,
    chunk_type: str,
    start_line: int,
    end_line: int,
    content_hash: str,
    symbol_id: UUID | None = None,
    symbol_ids: list[str] | None = None,
) -> UUID:
    """
    Compute a deterministic UUIDv5 chunk identity from immutable source/symbol boundaries
    and content hash so unchanged chunks keep a stable ID across re-indexing passes.
    """
    sym_part = ",".join(symbol_ids) if symbol_ids else (str(symbol_id) if symbol_id else "none")
    seed = f"{repository_id}|{file_id}|{chunk_type}|{start_line}:{end_line}|{sym_part}|{content_hash}"
    return uuid.uuid5(_CHUNK_ID_NAMESPACE, seed)


def build_contextual_header(
    *,
    file_path: str | None = None,
    language: str | None = None,
    class_name: str | None = None,
    signature: str | None = None,
) -> str:
    """
    Build a concise, deterministic contextual header from trusted file/symbol metadata.

    Example output:
        `# path: app/x.py | class Foo | def bar(a, b)`

    Guarantees:
    - Uses only available, non-empty metadata fields.
    - Redacts any secrets present in symbol signatures before inclusion.
    - Never alters displayed source `content` or line numbers.
    """
    parts: list[str] = []
    clean_path = (file_path or "").strip().replace("\\", "/")
    if clean_path:
        parts.append(f"path: {clean_path}")
    elif language and language.strip() and language.strip().lower() != "unknown":
        parts.append(f"lang: {language.strip()}")

    clean_class = (class_name or "").strip()
    if clean_class:
        if not clean_class.startswith("class "):
            parts.append(f"class {redact(clean_class)}")
        else:
            parts.append(redact(clean_class))

    clean_sig = (signature or "").strip()
    if clean_sig:
        first_line_sig = " ".join(clean_sig.splitlines()[0].split())
        redacted_sig = redact(first_line_sig)
        if len(redacted_sig) > 180:
            redacted_sig = redacted_sig[:177] + "..."
        if not (clean_class and (redacted_sig == f"class {clean_class}" or redacted_sig == f"class {clean_class}:")):
            parts.append(redacted_sig)

    if not parts:
        return ""
    return "# " + " | ".join(parts)


def build_contextual_embedding_input(
    content: str,
    header: str | None,
    *,
    max_tokens: int = MAX_CHUNK_TOKENS,
) -> str:
    """
    Prepend `header` to `content` for embedding generation while respecting `max_tokens`.

    Keeps synthetic context out of displayed `content` and trims body tokens only if
    adding the header would exceed `max_tokens`.
    """
    redacted_content = redact(content)
    clean_header = redact(header.strip()) if header and header.strip() else ""
    if not clean_header:
        tokens = redacted_content.split()
        if len(tokens) > max_tokens:
            return " ".join(tokens[:max_tokens])
        return redacted_content

    header_tokens = clean_header.split()
    if len(header_tokens) >= max_tokens:
        return " ".join(header_tokens[:max_tokens])

    combined = f"{clean_header}\n{redacted_content}"
    combined_tokens = combined.split()
    if len(combined_tokens) <= max_tokens:
        return combined

    allowed_body_tokens = max(1, max_tokens - len(header_tokens))
    body_words = redacted_content.split()[:allowed_body_tokens]
    return f"{clean_header}\n{' '.join(body_words)}"


def reconstruct_file_from_chunks(
    chunks: Iterable[object],
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Reconstruct source text from indexed CodeChunk records without duplicating overlapping lines.

    SymbolChunker produces overlapping chunks (e.g. a `class` chunk spanning lines 10..60
    plus `method` chunks spanning lines 15..30, or `block` chunks with 10-line overlaps,
    or a `module` chunk spanning imports/constants at lines 1..120).
    Naive `"\n".join(c.content for c in chunks)` duplicates methods and overlapped lines.

    This helper reconstructs a 1-indexed line buffer (`dict[int, str]`) when valid line
    metadata is present, prioritizing fuller outer chunks (`class`, `function`, `block`)
    before filling gaps from `module` chunks, and slices to `[start_line..end_line]`.
    """
    chunk_list = [c for c in chunks if getattr(c, "content", None)]
    if not chunk_list:
        return ""

    # Sort so specific structural chunks (block, class, function) populate lines first,
    # and sparse/spanning 'module' chunks only fill remaining gaps.
    def _chunk_priority(c: object) -> tuple[int, int, int]:
        meta = getattr(c, "metadata", None) or getattr(c, "chunk_metadata", None) or {}
        ctype = meta.get("chunk_type", "") if isinstance(meta, dict) else getattr(c, "chunk_type", "")
        is_module = 1 if ctype == "module" else 0
        s_ln = int(getattr(c, "start_line", 0) or 0)
        e_ln = int(getattr(c, "end_line", 0) or 0)
        return (is_module, s_ln, -(e_ln - s_ln))

    line_map: dict[int, str] = {}
    can_use_line_map = True

    for c in sorted(chunk_list, key=_chunk_priority):
        content = str(getattr(c, "content", ""))
        s_ln = getattr(c, "start_line", None)
        e_ln = getattr(c, "end_line", None)
        lines = content.splitlines()
        if not isinstance(s_ln, int) or not isinstance(e_ln, int) or s_ln < 1:
            can_use_line_map = False
            break
        expected_span = e_ln - s_ln + 1
        # If a single-chunk mock in a unit test has start_line=1, end_line=10 but 2 lines of text,
        # only use line-by-line placement when the line count matches the span or there are multiple overlapping chunks.
        if len(chunk_list) == 1 and len(lines) != expected_span:
            can_use_line_map = False
            break

        meta = getattr(c, "metadata", None) or getattr(c, "chunk_metadata", None) or {}
        is_split = isinstance(meta, dict) and bool(meta.get("split_from_large_symbol"))
        context_hdr_count = int(meta.get("context_header_lines", 4)) if isinstance(meta, dict) else 4
        if is_split and context_hdr_count > 0 and s_ln > 1 and len(lines) > context_hdr_count:
            # Sub-chunks from _split_large_symbol prepend context header lines before the slice at s_ln
            body_lines = lines[context_hdr_count:]
            for idx, ln_text in enumerate(body_lines):
                line_no = s_ln + idx
                if line_no not in line_map:
                    line_map[line_no] = ln_text
        else:
            for idx, ln_text in enumerate(lines):
                line_no = s_ln + idx
                if line_no > e_ln:
                    break
                if line_no not in line_map:
                    line_map[line_no] = ln_text

    if not can_use_line_map or not line_map:
        # Fallback for mock chunks without line metadata
        filtered = [
            c
            for c in chunk_list
            if (start_line is None or (getattr(c, "end_line", 1) or 1) >= start_line)
            and (end_line is None or (getattr(c, "start_line", 1) or 1) <= end_line)
        ] or chunk_list
        return "\n".join(str(getattr(c, "content", "")) for c in filtered if getattr(c, "content", None))

    min_ln = max(1, start_line) if start_line is not None else min(line_map.keys())
    max_ln = end_line if end_line is not None else max(line_map.keys())
    selected_numbers = [ln for ln in sorted(line_map.keys()) if min_ln <= ln <= max_ln]
    if not selected_numbers:
        selected_numbers = sorted(line_map.keys())

    # Preserve blank lines between contiguous ranges within the reconstructed span
    output_lines: list[str] = []
    prev_ln: int | None = None
    for ln in selected_numbers:
        if prev_ln is not None and ln > prev_ln + 1 and (ln - prev_ln) <= 20:
            output_lines.extend([""] * (ln - prev_ln - 1))
        output_lines.append(line_map[ln])
        prev_ln = ln

    return "\n".join(output_lines)


class SymbolChunker:
    """
    Creates cAST-style syntax-aware chunks from parsed symbols with automatic secret redaction
    and contextual embedding headers kept strictly separate from displayed source content.
    """

    def __init__(
        self,
        *,
        max_chunk_tokens: int = MAX_CHUNK_TOKENS,
        small_sibling_threshold: int = SMALL_SIBLING_TOKEN_THRESHOLD,
        merge_small_siblings: bool = True,
    ) -> None:
        self.max_chunk_tokens = max_chunk_tokens
        self.small_sibling_threshold = small_sibling_threshold
        self.merge_small_siblings = merge_small_siblings

    def _token_count(self, content: str) -> int:
        """Return the project's lightweight token-count estimate."""
        return len(content.split())

    def _content_hash(self, content: str) -> str:
        """Return the SHA-256 hash of chunk content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _enforce_token_ceiling(
        self,
        raw_chunks: list[tuple[str, int, int]],
    ) -> list[tuple[str, int, int]]:
        """
        Guarantee every `(chunk_content, chunk_start, chunk_end)` tuple has
        `token_count <= self.max_chunk_tokens`, splitting oversized single-line or
        short-line segments along word boundaries if necessary.
        """
        bounded: list[tuple[str, int, int]] = []
        for text_seg, c_start, c_end in raw_chunks:
            words = text_seg.split()
            if len(words) <= self.max_chunk_tokens:
                bounded.append((text_seg, c_start, c_end))
                continue
            for offset in range(0, len(words), self.max_chunk_tokens):
                sub_words = words[offset : offset + self.max_chunk_tokens]
                bounded.append((" ".join(sub_words), c_start, c_end))
        return bounded

    def _split_large_symbol(
        self,
        symbol_content: str,
        start_line: int,
    ) -> list[tuple[str, int, int]]:
        """
        Split a large leaf symbol at logical line boundaries.

        Every sub-chunk keeps the symbol signature and first three
        lines as overlapping context (when they fit comfortably in the token budget),
        and records the accurate `(chunk_start, chunk_end)` line offset within the symbol.
        """
        lines = symbol_content.splitlines()
        if not lines:
            return []

        if self._token_count(symbol_content) <= self.max_chunk_tokens:
            return [
                (
                    symbol_content,
                    start_line,
                    start_line + len(lines) - 1,
                )
            ]

        context_lines = lines[:4]
        body_lines = lines[4:]

        # If <= 4 lines total or context_lines alone consumes >= half the token budget,
        # split line-by-line (and word-by-word via _enforce_token_ceiling if a single line > budget).
        context_tokens = self._token_count("\n".join(context_lines))
        if not body_lines or context_tokens >= (self.max_chunk_tokens // 2):
            line_chunks: list[tuple[str, int, int]] = []
            cur_lines: list[str] = []
            cur_start = start_line
            for idx, ln in enumerate(lines):
                cand = "\n".join(cur_lines + [ln])
                if cur_lines and self._token_count(cand) > self.max_chunk_tokens:
                    line_chunks.append(
                        ("\n".join(cur_lines), cur_start, cur_start + len(cur_lines) - 1)
                    )
                    cur_lines = [ln]
                    cur_start = start_line + idx
                else:
                    cur_lines.append(ln)
            if cur_lines:
                line_chunks.append(
                    ("\n".join(cur_lines), cur_start, cur_start + len(cur_lines) - 1)
                )
            return self._enforce_token_ceiling(line_chunks)

        chunks: list[tuple[str, int, int]] = []
        current_body: list[str] = []
        body_offset = 0

        for idx, line in enumerate(body_lines):
            candidate_body = current_body + [line]
            candidate = "\n".join(context_lines + candidate_body)

            if current_body and self._token_count(candidate) > self.max_chunk_tokens:
                chunk_content = "\n".join(context_lines + current_body)
                chunk_start = start_line if body_offset == 0 else (start_line + 4 + body_offset)
                chunk_end = start_line + 4 + body_offset + len(current_body) - 1

                chunks.append((chunk_content, chunk_start, chunk_end))

                current_body = [line]
                body_offset = idx
            else:
                current_body = candidate_body

        if current_body:
            chunk_content = "\n".join(context_lines + current_body)
            chunk_start = start_line if body_offset == 0 else (start_line + 4 + body_offset)
            chunk_end = start_line + 4 + body_offset + len(current_body) - 1

            chunks.append((chunk_content, chunk_start, chunk_end))

        return self._enforce_token_ceiling(chunks)

    def chunk_text(
        self,
        repository_id: UUID,
        file_id: UUID,
        content: str,
        language: str = "unknown",
        file_path: str | None = None,
    ) -> list[Chunk]:
        """Chunk arbitrary file content by line blocks with overlap when no symbols exist."""
        lines = content.splitlines()
        if not lines:
            return []

        chunks: list[Chunk] = []
        start_idx = 0
        total_lines = len(lines)
        header = build_contextual_header(file_path=file_path, language=language)

        while start_idx < total_lines:
            end_idx = min(start_idx + 60, total_lines)
            # Dynamically shrink end_idx if the 60-line window exceeds max_chunk_tokens
            while end_idx > start_idx + 1:
                candidate_raw = "\n".join(lines[start_idx:end_idx])
                if self._token_count(candidate_raw) <= self.max_chunk_tokens:
                    break
                end_idx -= 1

            raw_block = "\n".join(lines[start_idx:end_idx])
            block = redact(raw_block)
            start_line = start_idx + 1
            end_line = end_idx

            # Handle pathological single line exceeding max_chunk_tokens
            for sub_block, sub_s, sub_e in self._enforce_token_ceiling([(block, start_line, end_line)]):
                meta: dict[str, Any] = {"chunker_version": CHUNKER_VERSION}
                if header:
                    meta["contextual_header"] = header
                chunks.append(
                    Chunk(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol_id=None,
                        content=sub_block,
                        start_line=sub_s,
                        end_line=sub_e,
                        language=language,
                        chunk_type="block",
                        token_count=self._token_count(sub_block),
                        content_hash=self._content_hash(sub_block),
                        metadata=meta,
                        embedding_text=build_contextual_embedding_input(
                            sub_block,
                            header,
                            max_tokens=self.max_chunk_tokens,
                        ),
                    )
                )
            if end_idx >= total_lines:
                break
            # Overlap by up to 10 lines while always advancing at least 1 line
            overlap = min(10, max(0, (end_idx - start_idx) // 3))
            start_idx = max(start_idx + 1, end_idx - overlap)

        return chunks

    def _emit_single_or_split_symbol(
        self,
        *,
        repository_id: UUID,
        file_id: UUID,
        symbol: Symbol,
        lines: list[str],
        language: str,
        file_path: str | None,
        class_name: str | None = None,
        override_chunk_type: str | None = None,
    ) -> list[Chunk]:
        """Emit a single symbol chunk or recursively split it along line boundaries if > budget."""
        start = max(0, symbol.start_line - 1)
        end = symbol.end_line
        symbol_content = "\n".join(lines[start:end])
        if override_chunk_type:
            chunk_type = override_chunk_type
        elif symbol.kind in _CONTAINER_SYMBOL_KINDS:
            chunk_type = "class"
        elif symbol.kind in _CALLABLE_SYMBOL_KINDS:
            chunk_type = "function"
        else:
            chunk_type = "module"

        header = build_contextual_header(
            file_path=file_path,
            language=language,
            class_name=class_name or (symbol.name if symbol.kind in _CONTAINER_SYMBOL_KINDS else None),
            signature=symbol.signature or symbol.name,
        )

        split_chunks = self._split_large_symbol(symbol_content, symbol.start_line)
        emitted: list[Chunk] = []
        dom_sym_id = None if chunk_type == "module" else symbol.id

        if len(split_chunks) == 1:
            chunk_content = redact(split_chunks[0][0])
            meta: dict[str, Any] = {
                "symbol_ids": [str(symbol.id)],
                "symbol_names": [symbol.name],
                "chunker_version": CHUNKER_VERSION,
            }
            if header:
                meta["contextual_header"] = header
            if class_name:
                meta["parent_class"] = class_name
            emitted.append(
                Chunk(
                    repository_id=repository_id,
                    file_id=file_id,
                    symbol_id=dom_sym_id,
                    content=chunk_content,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    language=language,
                    chunk_type=chunk_type,
                    token_count=self._token_count(chunk_content),
                    content_hash=self._content_hash(chunk_content),
                    metadata=meta,
                    embedding_text=build_contextual_embedding_input(
                        chunk_content,
                        header,
                        max_tokens=self.max_chunk_tokens,
                    ),
                )
            )
        else:
            for raw_chunk_content, chunk_start, chunk_end in split_chunks:
                chunk_content = redact(raw_chunk_content)
                meta = {
                    "split_from_large_symbol": True,
                    "symbol_ids": [str(symbol.id)],
                    "symbol_names": [symbol.name],
                    "chunker_version": CHUNKER_VERSION,
                }
                if header:
                    meta["contextual_header"] = header
                if class_name:
                    meta["parent_class"] = class_name
                emitted.append(
                    Chunk(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol_id=dom_sym_id,
                        content=chunk_content,
                        start_line=chunk_start,
                        end_line=chunk_end,
                        language=language,
                        chunk_type=chunk_type,
                        token_count=self._token_count(chunk_content),
                        content_hash=self._content_hash(chunk_content),
                        metadata=meta,
                        embedding_text=build_contextual_embedding_input(
                            chunk_content,
                            header,
                            max_tokens=self.max_chunk_tokens,
                        ),
                    )
                )
        return emitted

    def _chunk_sibling_sequence(
        self,
        *,
        repository_id: UUID,
        file_id: UUID,
        siblings: list[Symbol],
        lines: list[str],
        language: str,
        file_path: str | None,
        class_name: str | None = None,
        allow_merge: bool = True,
        default_chunk_type: str = "function",
    ) -> list[Chunk]:
        """
        Greedily merge adjacent small sibling symbols within the same scope up to `max_chunk_tokens`,
        preserving a deterministic dominant `symbol_id` (`group[0].id`, or `None` for module chunks)
        and recording all merged symbol IDs in `metadata["symbol_ids"]`.
        """
        if not siblings:
            return []

        ordered = sorted(siblings, key=lambda s: (s.start_line, s.end_line, str(s.name)))
        if not allow_merge or not self.merge_small_siblings or len(ordered) == 1:
            out: list[Chunk] = []
            for sym in ordered:
                out.extend(
                    self._emit_single_or_split_symbol(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol=sym,
                        lines=lines,
                        language=language,
                        file_path=file_path,
                        class_name=class_name,
                        override_chunk_type=default_chunk_type,
                    )
                )
            return out

        emitted: list[Chunk] = []
        current_group: list[Symbol] = []

        def _flush_group(group: list[Symbol]) -> None:
            if not group:
                return
            if len(group) == 1:
                emitted.extend(
                    self._emit_single_or_split_symbol(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol=group[0],
                        lines=lines,
                        language=language,
                        file_path=file_path,
                        class_name=class_name,
                        override_chunk_type=default_chunk_type,
                    )
                )
                return

            g_start = group[0].start_line
            g_end = max(s.end_line for s in group)
            merged_raw = "\n".join(lines[max(0, g_start - 1) : g_end])
            merged_content = redact(merged_raw)
            dominant = group[0]
            dom_id = None if default_chunk_type == "module" else dominant.id
            combined_sig = " ; ".join(
                (s.signature or s.name).splitlines()[0].strip() for s in group if (s.signature or s.name)
            )
            header = build_contextual_header(
                file_path=file_path,
                language=language,
                class_name=class_name,
                signature=combined_sig,
            )
            meta: dict[str, Any] = {
                "symbol_ids": [str(s.id) for s in group],
                "symbol_names": [s.name for s in group],
                "merged_sibling_count": len(group),
                "chunker_version": CHUNKER_VERSION,
            }
            if header:
                meta["contextual_header"] = header
            if class_name:
                meta["parent_class"] = class_name

            emitted.append(
                Chunk(
                    repository_id=repository_id,
                    file_id=file_id,
                    symbol_id=dom_id,
                    content=merged_content,
                    start_line=g_start,
                    end_line=g_end,
                    language=language,
                    chunk_type=default_chunk_type,
                    token_count=self._token_count(merged_content),
                    content_hash=self._content_hash(merged_content),
                    metadata=meta,
                    embedding_text=build_contextual_embedding_input(
                        merged_content,
                        header,
                        max_tokens=self.max_chunk_tokens,
                    ),
                )
            )

        for sym in ordered:
            sym_text = "\n".join(lines[max(0, sym.start_line - 1) : sym.end_line])
            sym_tokens = self._token_count(sym_text)

            # Only small sibling nodes (<= small_sibling_threshold) are candidates for greedy merging
            if sym_tokens > self.small_sibling_threshold:
                _flush_group(current_group)
                current_group = []
                emitted.extend(
                    self._emit_single_or_split_symbol(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol=sym,
                        lines=lines,
                        language=language,
                        file_path=file_path,
                        class_name=class_name,
                        override_chunk_type=default_chunk_type,
                    )
                )
                continue

            if not current_group:
                current_group = [sym]
                continue

            prev_end = max(s.end_line for s in current_group)
            gap_lines = lines[prev_end : max(0, sym.start_line - 1)]
            non_empty_gap = sum(1 for ln in gap_lines if ln.strip())
            candidate_span_text = "\n".join(
                lines[max(0, current_group[0].start_line - 1) : max(prev_end, sym.end_line)]
            )
            candidate_tokens = self._token_count(candidate_span_text)

            if non_empty_gap <= 2 and candidate_tokens <= self.max_chunk_tokens:
                current_group.append(sym)
            else:
                _flush_group(current_group)
                current_group = [sym]

        _flush_group(current_group)
        return emitted

    def _emit_class_span_segment(
        self,
        *,
        repository_id: UUID,
        file_id: UUID,
        cls: Symbol,
        seg_start: int,
        seg_end: int,
        lines: list[str],
        language: str,
        file_path: str | None,
        segment_tag: str,
    ) -> list[Chunk]:
        """Emit bounded class sub-chunk(s) for preamble, inter-method, or trailing class lines."""
        if seg_start > seg_end:
            return []
        seg_raw = "\n".join(lines[max(0, seg_start - 1) : seg_end])
        if not seg_raw.strip():
            return []

        seg_content = redact(seg_raw)
        header = build_contextual_header(
            file_path=file_path,
            language=language,
            class_name=cls.name,
            signature=cls.signature or f"class {cls.name}",
        )
        out: list[Chunk] = []
        for sub_raw, sub_s, sub_e in self._split_large_symbol(seg_content, seg_start):
            sub_redacted = redact(sub_raw)
            meta: dict[str, Any] = {
                "symbol_ids": [str(cls.id)],
                "symbol_names": [cls.name],
                segment_tag: True,
                "chunker_version": CHUNKER_VERSION,
            }
            if header:
                meta["contextual_header"] = header
            out.append(
                Chunk(
                    repository_id=repository_id,
                    file_id=file_id,
                    symbol_id=cls.id,
                    content=sub_redacted,
                    start_line=sub_s,
                    end_line=sub_e,
                    language=language,
                    chunk_type="class",
                    token_count=self._token_count(sub_redacted),
                    content_hash=self._content_hash(sub_redacted),
                    metadata=meta,
                    embedding_text=build_contextual_embedding_input(
                        sub_redacted,
                        header,
                        max_tokens=self.max_chunk_tokens,
                    ),
                )
            )
        return out

    def chunk_symbols(
        self,
        repository_id: UUID,
        file_id: UUID,
        symbols: list[Symbol],
        content: str,
        language: str,
        file_path: str | None = None,
    ) -> list[Chunk]:
        """
        cAST-style AST/symbol chunker:
        1. Recursively splits container symbols (`class`, `interface`, `struct`) exceeding
           `MAX_CHUNK_TOKENS` along child method boundaries before falling back to line-based
           splitting, while preserving preamble, inter-method, and trailing lines (such as `}`).
        2. Greedily merges adjacent small top-level sibling symbols and adjacent module symbols
           up to `MAX_CHUNK_TOKENS` without spanning across intermediate classes/functions.
        3. Populates `chunk.embedding_text` with deterministic contextual headers while keeping
           `chunk.content` strictly as raw/redacted source lines.
        """
        if not symbols:
            return self.chunk_text(
                repository_id,
                file_id,
                content,
                language,
                file_path=file_path,
            )

        lines = content.splitlines()
        chunks: list[Chunk] = []
        module_symbols: list[Symbol] = []
        classes: list[Symbol] = []
        functions_and_methods: list[Symbol] = []

        for symbol in symbols:
            if symbol.kind in _CONTAINER_SYMBOL_KINDS:
                classes.append(symbol)
            elif symbol.kind in _CALLABLE_SYMBOL_KINDS:
                functions_and_methods.append(symbol)
            else:
                module_symbols.append(symbol)

        classes.sort(key=lambda c: (c.start_line, c.end_line))

        # Map child methods to their enclosing class (by parent_id or line span containment)
        children_by_class_id: dict[UUID, list[Symbol]] = {c.id: [] for c in classes}
        top_level_functions: list[Symbol] = []

        for fn in functions_and_methods:
            assigned_class: Symbol | None = None
            if fn.parent_id and fn.parent_id in children_by_class_id:
                assigned_class = next((c for c in classes if c.id == fn.parent_id), None)
            if assigned_class is None:
                for cls in classes:
                    if cls.start_line <= fn.start_line and fn.end_line <= cls.end_line:
                        assigned_class = cls
                        break
            if assigned_class is not None:
                children_by_class_id[assigned_class.id].append(fn)
            else:
                top_level_functions.append(fn)

        # Process classes/interfaces/structs with cAST recursive splitting
        for cls in classes:
            cls_start = max(0, cls.start_line - 1)
            cls_end = cls.end_line
            cls_raw = "\n".join(lines[cls_start:cls_end])
            cls_tokens = self._token_count(cls_raw)
            child_methods = sorted(
                children_by_class_id.get(cls.id, []),
                key=lambda m: (m.start_line, m.end_line),
            )

            if cls_tokens <= self.max_chunk_tokens or not child_methods:
                # Class fits within budget (or has no child symbols): emit class chunk
                chunks.extend(
                    self._emit_single_or_split_symbol(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol=cls,
                        lines=lines,
                        language=language,
                        file_path=file_path,
                        class_name=cls.name,
                        override_chunk_type="class",
                    )
                )
                # Also emit individual child method chunks for fine-grained method retrieval
                for m in child_methods:
                    chunks.extend(
                        self._emit_single_or_split_symbol(
                            repository_id=repository_id,
                            file_id=file_id,
                            symbol=m,
                            lines=lines,
                            language=language,
                            file_path=file_path,
                            class_name=cls.name,
                            override_chunk_type="function",
                        )
                    )
            else:
                # Large class (> MAX_CHUNK_TOKENS) with child methods:
                # 1. Emit class preamble before the first child method
                first_method_start = child_methods[0].start_line
                if first_method_start > cls.start_line:
                    chunks.extend(
                        self._emit_class_span_segment(
                            repository_id=repository_id,
                            file_id=file_id,
                            cls=cls,
                            seg_start=cls.start_line,
                            seg_end=first_method_start - 1,
                            lines=lines,
                            language=language,
                            file_path=file_path,
                            segment_tag="class_preamble",
                        )
                    )

                # 2. Emit any non-empty inter-method class attribute/comment blocks
                for prev_m, next_m in zip(child_methods, child_methods[1:]):
                    if next_m.start_line > prev_m.end_line + 1:
                        chunks.extend(
                            self._emit_class_span_segment(
                                repository_id=repository_id,
                                file_id=file_id,
                                cls=cls,
                                seg_start=prev_m.end_line + 1,
                                seg_end=next_m.start_line - 1,
                                lines=lines,
                                language=language,
                                file_path=file_path,
                                segment_tag="class_inter_method",
                            )
                        )

                # 3. Greedily merge tiny sibling methods inside the large class or emit/split each method
                chunks.extend(
                    self._chunk_sibling_sequence(
                        repository_id=repository_id,
                        file_id=file_id,
                        siblings=child_methods,
                        lines=lines,
                        language=language,
                        file_path=file_path,
                        class_name=cls.name,
                        allow_merge=True,
                        default_chunk_type="function",
                    )
                )

                # 4. Preserve trailing class lines after the last child method (e.g. closing `}` or trailing fields)
                last_method_end = max(m.end_line for m in child_methods)
                if last_method_end < cls.end_line:
                    chunks.extend(
                        self._emit_class_span_segment(
                            repository_id=repository_id,
                            file_id=file_id,
                            cls=cls,
                            seg_start=last_method_end + 1,
                            seg_end=cls.end_line,
                            lines=lines,
                            language=language,
                            file_path=file_path,
                            segment_tag="class_epilogue",
                        )
                    )

        # Process top-level sibling functions (greedily merging adjacent small siblings up to budget)
        chunks.extend(
            self._chunk_sibling_sequence(
                repository_id=repository_id,
                file_id=file_id,
                siblings=top_level_functions,
                lines=lines,
                language=language,
                file_path=file_path,
                class_name=None,
                allow_merge=True,
                default_chunk_type="function",
            )
        )

        # Process module symbols (imports, constants, etc.) using _chunk_sibling_sequence so
        # top-of-file imports and bottom-of-file constants never merge across functions/classes
        # and every module chunk strictly obeys `max_chunk_tokens`.
        if module_symbols:
            chunks.extend(
                self._chunk_sibling_sequence(
                    repository_id=repository_id,
                    file_id=file_id,
                    siblings=module_symbols,
                    lines=lines,
                    language=language,
                    file_path=file_path,
                    class_name=None,
                    allow_merge=True,
                    default_chunk_type="module",
                )
            )

        return chunks

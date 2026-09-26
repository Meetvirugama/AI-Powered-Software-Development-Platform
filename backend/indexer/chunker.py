import hashlib
from uuid import UUID

from backend.scanner.symbols import Symbol

from .models import Chunk


MAX_CHUNK_TOKENS = 512


class SymbolChunker:
    """Creates symbol-aware chunks from parsed symbols."""

    def _token_count(self, content: str) -> int:
        """Return the project's lightweight token-count estimate."""
        return len(content.split())

    def _content_hash(self, content: str) -> str:
        """Return the SHA-256 hash of chunk content."""
        return hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()

    def _split_large_symbol(
        self,
        symbol_content: str,
        start_line: int,
    ) -> list[tuple[str, int, int]]:
        """
        Split a large symbol at logical line boundaries.

        Every sub-chunk keeps the symbol signature and first three
        lines as overlapping context.
        """
        lines = symbol_content.splitlines()

        if self._token_count(symbol_content) <= MAX_CHUNK_TOKENS:
            return [
                (
                    symbol_content,
                    start_line,
                    start_line + len(lines) - 1,
                )
            ]

        context_lines = lines[:4]
        body_lines = lines[4:]

        if not body_lines:
            return [
                (
                    symbol_content,
                    start_line,
                    start_line + len(lines) - 1,
                )
            ]

        chunks: list[tuple[str, int, int]] = []
        current_body: list[str] = []

        for line in body_lines:
            candidate_body = current_body + [line]
            candidate = "\n".join(
                context_lines + candidate_body
            )

            if (
                current_body
                and self._token_count(candidate) > MAX_CHUNK_TOKENS
            ):
                chunk_content = "\n".join(
                    context_lines + current_body
                )
                chunk_start = start_line
                chunk_end = (
                    start_line
                    + 3
                    + len(current_body)
                    - 1
                )

                chunks.append(
                    (
                        chunk_content,
                        chunk_start,
                        chunk_end,
                    )
                )

                current_body = [line]
            else:
                current_body = candidate_body

        if current_body:
            chunk_content = "\n".join(
                context_lines + current_body
            )
            chunk_start = start_line
            chunk_end = (
                start_line
                + 3
                + len(current_body)
                - 1
            )

            chunks.append(
                (
                    chunk_content,
                    chunk_start,
                    chunk_end,
                )
            )

        return chunks

    def chunk_symbols(
        self,
        repository_id: UUID,
        file_id: UUID,
        symbols: list[Symbol],
        content: str,
        language: str,
    ) -> list[Chunk]:
        lines = content.splitlines()
        chunks: list[Chunk] = []
        module_symbols: list[Symbol] = []

        for symbol in symbols:
            if symbol.kind in {"function", "method", "class"}:
                start = symbol.start_line - 1
                end = symbol.end_line
                symbol_content = "\n".join(
                    lines[start:end]
                )

                chunk_type = (
                    "class"
                    if symbol.kind == "class"
                    else "function"
                )

                split_chunks = self._split_large_symbol(
                    symbol_content,
                    symbol.start_line,
                )

                if len(split_chunks) == 1:
                    chunk_content = split_chunks[0][0]

                    chunks.append(
                        Chunk(
                            repository_id=repository_id,
                            file_id=file_id,
                            symbol_id=symbol.id,
                            content=chunk_content,
                            start_line=symbol.start_line,
                            end_line=symbol.end_line,
                            language=language,
                            chunk_type=chunk_type,
                            token_count=self._token_count(
                                chunk_content
                            ),
                            content_hash=self._content_hash(
                                chunk_content
                            ),
                            metadata={},
                        )
                    )
                else:
                    for (
                        chunk_content,
                        chunk_start,
                        chunk_end,
                    ) in split_chunks:
                        chunks.append(
                            Chunk(
                                repository_id=repository_id,
                                file_id=file_id,
                                symbol_id=symbol.id,
                                content=chunk_content,
                                start_line=chunk_start,
                                end_line=chunk_end,
                                language=language,
                                chunk_type=chunk_type,
                                token_count=self._token_count(
                                    chunk_content
                                ),
                                content_hash=self._content_hash(
                                    chunk_content
                                ),
                                metadata={
                                    "split_from_large_symbol": True,
                                },
                            )
                        )
            else:
                module_symbols.append(symbol)

        if module_symbols:
            start_line = min(
                symbol.start_line
                for symbol in module_symbols
            )
            end_line = max(
                symbol.end_line
                for symbol in module_symbols
            )

            module_content = "\n".join(
                lines[start_line - 1:end_line]
            )

            chunks.append(
                Chunk(
                    repository_id=repository_id,
                    file_id=file_id,
                    symbol_id=None,
                    content=module_content,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    chunk_type="module",
                    token_count=self._token_count(
                        module_content
                    ),
                    content_hash=self._content_hash(
                        module_content
                    ),
                    metadata={},
                )
            )

        return chunks
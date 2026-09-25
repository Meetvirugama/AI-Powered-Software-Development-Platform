from typing import Any

from .models import Chunk


class SymbolChunker:
    """Creates chunks from parsed symbols."""

    def chunk_symbols(
        self,
        repository_id,
        file_id,
        symbols: list[Any],
        content: str,
        language: str,
    ) -> list[Chunk]:
        lines = content.splitlines()
        chunks: list[Chunk] = []
        module_symbols = []

        for symbol in symbols:
            if symbol.kind in {"function", "method", "class"}:
                start = symbol.start_line - 1
                end = symbol.end_line
                symbol_content = "\n".join(lines[start:end])

                chunk_type = (
                    "class"
                    if symbol.kind == "class"
                    else "function"
                )

                chunks.append(
                    Chunk(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbol_id=symbol.id,
                        content=symbol_content,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        language=language,
                        chunk_type=chunk_type,
                        token_count=len(symbol_content.split()),
                        content_hash="",
                        metadata={},
                    )
                )
            else:
                module_symbols.append(symbol)

        if module_symbols:
            start_line = min(symbol.start_line for symbol in module_symbols)
            end_line = max(symbol.end_line for symbol in module_symbols)

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
                    token_count=len(module_content.split()),
                    content_hash="",
                    metadata={},
                )
            )

        return chunks
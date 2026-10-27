import ast
import logging
import re
from typing import Any, Optional

try:
    import tree_sitter
    HAS_TREE_SITTER = True
except ImportError:
    tree_sitter = None
    HAS_TREE_SITTER = False

try:
    import tree_sitter_languages
except ImportError:
    tree_sitter_languages = None

from .symbols import FileInfo, ParseResult

logger = logging.getLogger(__name__)


def _sanitize_source_text(content: str) -> str:
    """Replace lone UTF-16 surrogates so UTF-8 encoding and AST parsing never crash."""
    if not content:
        return ""
    return content.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


class Parser:
    def __init__(self):
        self.language_map = {
            'Python': 'python',
            'TypeScript': 'typescript',
            'JavaScript': 'javascript',
            'Java': 'java',
            'Go': 'go',
            'Rust': 'rust',
            'C': 'c',
            'C++': 'cpp',
        }

    def is_language_supported(self, language: str) -> bool:
        """Return True if language is in the recognized grammar mapping."""
        return language in self.language_map

    def get_supported_languages(self) -> list[str]:
        """Return the list of all supported language names."""
        return list(self.language_map.keys())

    def parse_with_status(self, file_info: FileInfo, content: str) -> ParseResult:
        """Parse source content and return a structured ParseResult with explicit status."""
        safe_content = _sanitize_source_text(content or "")
        ts_lang_name = self.language_map.get(file_info.language)
        if not ts_lang_name:
            logger.warning(f"Unsupported language: {file_info.language}")
            return ParseResult(
                success=False,
                language=file_info.language,
                is_supported=False,
                error_message=f"Unsupported language: {file_info.language}",
            )

        if HAS_TREE_SITTER:
            try:
                language = None
                if tree_sitter_languages is not None:
                    try:
                        language = tree_sitter_languages.get_language(ts_lang_name)
                    except Exception:
                        pass

                if language is None:
                    if ts_lang_name == "python":
                        import tree_sitter_python
                        language = tree_sitter.Language(tree_sitter_python.language())
                    elif ts_lang_name == "javascript":
                        import tree_sitter_javascript
                        language = tree_sitter.Language(tree_sitter_javascript.language())
                    elif ts_lang_name == "typescript":
                        import tree_sitter_typescript
                        language = tree_sitter.Language(tree_sitter_typescript.language_typescript())

                if language is not None:
                    try:
                        parser = tree_sitter.Parser(language)
                    except TypeError:
                        parser = tree_sitter.Parser()
                        parser.set_language(language)

                    tree = parser.parse(safe_content.encode("utf-8", errors="replace"))
                    has_syntax_errors = bool(tree.root_node.has_error)
                    return ParseResult(
                        success=True,
                        tree=tree,
                        language=file_info.language,
                        is_supported=True,
                        has_syntax_errors=has_syntax_errors,
                        error_message="Syntax errors detected in source code" if has_syntax_errors else None,
                    )
            except Exception as e:
                logger.debug(f"Tree-sitter parse fallback for {file_info.path}: {e}")

        # Fallback AST / structural parser when tree-sitter grammar wheel is not installed
        if ts_lang_name == "python":
            try:
                ast_tree = ast.parse(safe_content)
                return ParseResult(
                    success=True,
                    tree=ast_tree,
                    language=file_info.language,
                    is_supported=True,
                    has_syntax_errors=False,
                    error_message=None,
                )
            except SyntaxError as syn_err:
                return ParseResult(
                    success=True,
                    tree=None,
                    language=file_info.language,
                    is_supported=True,
                    has_syntax_errors=True,
                    error_message=f"Syntax errors detected in source code: {syn_err.msg}",
                )

        if ts_lang_name in ("javascript", "typescript"):
            stripped = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", '""', safe_content)
            has_err = (
                stripped.count("{") != stripped.count("}")
                or stripped.count("(") != stripped.count(")")
            )
            return ParseResult(
                success=True,
                tree=None,
                language=file_info.language,
                is_supported=True,
                has_syntax_errors=has_err,
                error_message="Syntax errors detected in source code" if has_err else None,
            )

        return ParseResult(
            success=False,
            language=file_info.language,
            is_supported=True,
            error_message=f"Could not load parser grammar for {ts_lang_name}",
        )

    def parse(self, file_info: FileInfo, content: str) -> Optional[Any]:
        """Parse source content into a concrete syntax tree, returning None on failure."""
        result = self.parse_with_status(file_info, content)
        if not result.success:
            return None
        if hasattr(result.tree, "root_node"):
            return result.tree
        return None

import logging
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
        if not HAS_TREE_SITTER:
            return ParseResult(
                success=False,
                language=file_info.language,
                is_supported=self.is_language_supported(file_info.language),
                error_message="tree-sitter is not installed or available",
            )

        ts_lang_name = self.language_map.get(file_info.language)
        if not ts_lang_name:
            logger.warning(f"Unsupported language: {file_info.language}")
            return ParseResult(
                success=False,
                language=file_info.language,
                is_supported=False,
                error_message=f"Unsupported language: {file_info.language}",
            )

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

            if not language:
                logger.warning(f"Could not load parser grammar for {ts_lang_name}")
                return ParseResult(
                    success=False,
                    language=file_info.language,
                    is_supported=True,
                    error_message=f"Could not load parser grammar for {ts_lang_name}",
                )

            try:
                parser = tree_sitter.Parser(language)
            except TypeError:
                parser = tree_sitter.Parser()
                parser.set_language(language)

            tree = parser.parse(bytes(content, "utf8"))
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
            logger.error(f"Error parsing {file_info.path}: {e}")
            return ParseResult(
                success=False,
                language=file_info.language,
                is_supported=True,
                error_message=str(e),
            )

    def parse(self, file_info: FileInfo, content: str) -> Optional[Any]:
        """Parse source content into a concrete syntax tree, returning None on failure."""
        result = self.parse_with_status(file_info, content)
        return result.tree if result.success else None



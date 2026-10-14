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

from .symbols import FileInfo

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
            'C++': 'cpp'
        }

    def parse(self, file_info: FileInfo, content: str) -> Optional[Any]:
        if not HAS_TREE_SITTER:
            return None
        try:
            ts_lang_name = self.language_map.get(file_info.language)
            if not ts_lang_name:
                logger.warning(f"Unsupported language: {file_info.language}")
                return None
            
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
                return None

            try:
                parser = tree_sitter.Parser(language)
            except TypeError:
                parser = tree_sitter.Parser()
                parser.set_language(language)

            tree = parser.parse(bytes(content, "utf8"))
            return tree
        except Exception as e:
            logger.error(f"Error parsing {file_info.path}: {e}")
            return None


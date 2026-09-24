import logging
from typing import Any, Optional
import tree_sitter
import tree_sitter_languages
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

    def parse(self, file_info: FileInfo, content: str) -> Optional[tree_sitter.Tree]:
        try:
            ts_lang_name = self.language_map.get(file_info.language)
            if not ts_lang_name:
                logger.warning(f"Unsupported language: {file_info.language}")
                return None
            
            language = tree_sitter_languages.get_language(ts_lang_name)
            parser = tree_sitter.Parser()
            parser.set_language(language)
            
            tree = parser.parse(bytes(content, "utf8"))
            return tree
        except Exception as e:
            logger.error(f"Error parsing {file_info.path}: {e}")
            return None

import logging
import tree_sitter_languages
from tree_sitter import Parser as TSParser, Tree
from typing import Optional
from .symbols import FileInfo

logger = logging.getLogger(__name__)

class Parser:
    def __init__(self):
        pass

    def parse(self, file_info: FileInfo, content: str) -> Optional[Tree]:
        lang_key = file_info.language.lower()
        if lang_key not in ["python", "typescript"]:
            return None
            
        try:
            # Initialize tree_sitter_languages.get_language(file_info.language)
            lang = tree_sitter_languages.get_language(lang_key)
            parser = TSParser()
            parser.set_language(lang)
            
            # Parse content, return tree
            tree = parser.parse(content.encode('utf-8'))
            return tree
        except Exception as e:
            # Handle parse errors gracefully: log the error, return a partial tree (don't raise)
            logger.error(f"Error parsing {file_info.path}: {e}")
            return None

import os
from .symbols import FileInfo

class LanguageDetector:
    def __init__(self):
        self.extension_map = {
            '.py': 'Python',
            '.ts': 'TypeScript',
            '.js': 'JavaScript',
            '.java': 'Java',
            '.go': 'Go',
            '.rs': 'Rust',
            '.c': 'C',
            '.cpp': 'C++'
        }

    def detect(self, file_info: FileInfo) -> str:
        ext = os.path.splitext(file_info.path)[1].lower()
        if ext in self.extension_map:
            return self.extension_map[ext]
        
        # Shebang detection
        try:
            with open(file_info.path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if first_line.startswith('#!'):
                    if 'python' in first_line:
                        return 'Python'
                    elif 'node' in first_line:
                        return 'JavaScript'
        except Exception:
            pass
            
        return 'unknown'

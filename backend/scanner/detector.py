import os
from pathlib import Path
from .symbols import FileInfo


class LanguageDetector:
    def __init__(self, root_path: str | Path | None = None):
        self.root_path = Path(root_path).resolve() if root_path is not None else None
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

    def detect(self, file_info: FileInfo, root_path: str | Path | None = None) -> str:
        raw_path = (file_info.path or "").strip()
        if not raw_path or "\x00" in raw_path:
            return 'unknown'

        ext = os.path.splitext(raw_path)[1].lower()
        if ext in self.extension_map:
            return self.extension_map[ext]

        # Security (W1-F4): Reject path traversal segments ('..') before opening a file
        normalized_parts = raw_path.replace("\\", "/").split("/")
        if ".." in normalized_parts:
            return 'unknown'

        effective_root = Path(root_path).resolve() if root_path is not None else self.root_path
        try:
            target = Path(raw_path)
            if effective_root is not None:
                candidate = (effective_root / target).resolve() if not target.is_absolute() else target.resolve()
                candidate.relative_to(effective_root)
            else:
                candidate = target.resolve()

            if not candidate.is_file():
                return 'unknown'

            # Shebang detection
            with open(candidate, 'r', encoding='utf-8', errors='replace') as f:
                first_line = f.readline(256).strip()
                if first_line.startswith('#!'):
                    if 'python' in first_line:
                        return 'Python'
                    elif 'node' in first_line:
                        return 'JavaScript'
        except Exception:
            pass

        return 'unknown'

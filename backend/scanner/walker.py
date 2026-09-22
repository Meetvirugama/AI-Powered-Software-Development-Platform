import os
import pathspec
from typing import List
from .symbols import FileInfo

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1MB
SKIP_DIRS = {'.git', 'node_modules', 'venv', '__pycache__', 'dist', 'build', '.next', '.cache'}

class FileWalker:
    def __init__(self):
        pass

    def _is_binary(self, filepath: str) -> bool:
        try:
            with open(filepath, 'rb') as f:
                chunk = f.read(8192)
                if b'\x00' in chunk:
                    return True
        except Exception:
            return True
        return False

    def walk(self, root_path: str) -> List[FileInfo]:
        gitignore_path = os.path.join(root_path, '.gitignore')
        spec = None
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                spec = pathspec.PathSpec.from_lines('gitignore', f)

        file_infos = []

        for dirpath, dirnames, filenames in os.walk(root_path):
            # Modify dirnames in-place to skip directories
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            
            # Remove hidden directories as well (starting with '.') except maybe some valid ones?
            # Instructions only specified specific SKIP_DIRS, so we stick to that.
            
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                # Ensure we use forward slashes for cross-platform rel_path consistency if needed,
                # but os.path.relpath works natively.
                rel_path = os.path.relpath(filepath, root_path)
                # pathspec match_file expects POSIX path format
                posix_rel_path = rel_path.replace(os.sep, '/')
                
                # Check .gitignore
                if spec and spec.match_file(posix_rel_path):
                    continue
                
                # Skip large files
                try:
                    size_bytes = os.path.getsize(filepath)
                except OSError:
                    continue
                if size_bytes > MAX_FILE_SIZE_BYTES:
                    continue
                
                # Skip binary files
                is_binary = self._is_binary(filepath)
                if is_binary:
                    continue
                    
                file_infos.append(FileInfo(
                    path=rel_path,
                    size_bytes=size_bytes,
                    language="unknown",
                    is_binary=False
                ))
        
        file_infos.sort(key=lambda x: x.path)
        return file_infos

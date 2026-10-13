import logging
import os
from pathlib import Path
from typing import List

import pathspec

from app.core.input_security import UnsafePathError, is_within, validate_repo_relative_path

from .symbols import FileInfo

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1MB — larger files (e.g. a 50MB dump) are skipped
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
        real_root = Path(root_path).resolve()

        # followlinks=False (the default): symlinked directories are never entered.
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
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

                # Security (Day 5): never follow symlinks. A repository can ship
                # `authorized_keys -> /root/.ssh/authorized_keys`; reading it would
                # pull a host file into the index and the LLM context.
                if os.path.islink(filepath):
                    logger.warning("walker_skipped_symlink", extra={"path": posix_rel_path})
                    continue

                # Security (Day 5): reject malicious file names (control characters,
                # backslashes, `..` segments) and anything resolving outside the root.
                try:
                    validate_repo_relative_path(posix_rel_path)
                except UnsafePathError:
                    logger.warning("walker_skipped_unsafe_path", extra={"path": repr(posix_rel_path)})
                    continue
                if not is_within(real_root, Path(filepath).resolve()):
                    logger.warning("walker_skipped_outside_root", extra={"path": posix_rel_path})
                    continue

                # Check .gitignore
                if spec and spec.match_file(posix_rel_path):
                    continue

                # Skip large files
                try:
                    size_bytes = os.path.getsize(filepath)
                except OSError:
                    continue
                if size_bytes > MAX_FILE_SIZE_BYTES:
                    logger.info("walker_skipped_large_file", extra={"path": posix_rel_path, "size_bytes": size_bytes})
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

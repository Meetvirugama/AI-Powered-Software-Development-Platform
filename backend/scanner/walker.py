import logging
import os
from pathlib import Path
from typing import List

import pathspec

from app.core.input_security import UnsafePathError, is_within, validate_repo_relative_path

from .symbols import FileInfo

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1MB — larger files (e.g. a 50MB dump) are skipped
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", "dist", "build", ".next", ".cache",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".tox", "coverage", ".nyc_output"
}

SKIP_EXTENSIONS = {
    # Data & Datasets
    ".csv", ".tsv", ".parquet", ".feather", ".arrow", ".sqlite", ".sqlite3", ".db", ".sqlitedb",
    # ML / Model files
    ".h5", ".hdf5", ".pt", ".pth", ".onnx", ".safetensors", ".weights", ".pkl", ".pickle", ".npy", ".npz",
    # Notebooks & Documents
    ".ipynb", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Media & Fonts
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Archives
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar",
    # Logs & Locks & Minified
    ".log", ".lock", ".min.js", ".min.css", ".map",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pipfile.lock",
    "cargo.lock",
    "composer.lock",
}


class FileWalker:
    def __init__(self):
        pass

    def _is_binary(self, filepath: str) -> bool:
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(8192)
                if b"\x00" in chunk:
                    return True
        except Exception:
            return True
        return False

    def walk(self, root_path: str) -> List[FileInfo]:
        gitignore_path = os.path.join(root_path, ".gitignore")
        spec = None
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                spec = pathspec.PathSpec.from_lines("gitignore", f)

        file_infos = []
        real_root = Path(root_path).resolve()

        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            for filename in filenames:
                lower_filename = filename.lower()
                if lower_filename in SKIP_FILENAMES:
                    continue
                if any(lower_filename.endswith(ext) for ext in SKIP_EXTENSIONS):
                    continue

                filepath = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(filepath, root_path)
                posix_rel_path = rel_path.replace(os.sep, "/").replace("\\", "/")

                if os.path.islink(filepath):
                    logger.warning("walker_skipped_symlink", extra={"path": posix_rel_path})
                    continue

                try:
                    validate_repo_relative_path(posix_rel_path)
                except UnsafePathError:
                    logger.warning("walker_skipped_unsafe_path", extra={"path": repr(posix_rel_path)})
                    continue
                if not is_within(real_root, Path(filepath).resolve()):
                    logger.warning("walker_skipped_outside_root", extra={"path": posix_rel_path})
                    continue

                if spec and spec.match_file(posix_rel_path):
                    continue

                try:
                    size_bytes = os.path.getsize(filepath)
                except OSError:
                    continue
                if size_bytes > MAX_FILE_SIZE_BYTES:
                    logger.info("walker_skipped_large_file", extra={"path": posix_rel_path, "size_bytes": size_bytes})
                    continue

                if self._is_binary(filepath):
                    continue

                file_infos.append(FileInfo(
                    path=posix_rel_path,
                    size_bytes=size_bytes,
                    language="unknown",
                    is_binary=False
                ))

        file_infos.sort(key=lambda x: x.path)
        return file_infos

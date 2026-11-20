import fnmatch
import logging
import os
from pathlib import Path

import pathspec
from app.core.input_security import UnsafePathError, is_within, validate_repo_relative_path

from .detector import LanguageDetector
from .symbols import FileInfo

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1MB — larger files (e.g. a 50MB dump) are skipped
MAX_FILES_PER_REPOSITORY = 50_000  # hard ceiling so a pathological repo cannot exhaust the worker

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", "dist", "build", ".next", ".cache",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".tox", "coverage", ".nyc_output",
    ".ruff_cache", ".gradle", ".terraform", "target", "vendor", "bower_components", ".svn", ".hg",
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

# Files that typically hold credentials. They are never indexed: indexing would store their
# contents in code_chunks and send them to the embedding provider. (Output redaction runs later,
# but only catches patterns it recognises.)
SECRET_FILE_PATTERNS = (
    ".env", ".env.*", "*.env",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.crt", "*.cer", "*.der",
    "id_rsa", "id_rsa.*", "id_dsa", "id_ecdsa", "id_ed25519", "*.ppk",
    ".npmrc", ".pypirc", ".netrc", ".htpasswd", ".git-credentials",
    "credentials.json", "service-account*.json", "*secret*.json", "*.tfstate", "*.tfstate.*",
)
# Templates that are meant to be committed and contain no real secrets.
SECRET_FILE_ALLOWLIST = (".env.example", ".env.sample", ".env.template", "*.env.example")

# --- File classification -----------------------------------------------------------------
CATEGORY_SOURCE = "source"
CATEGORY_TEST = "test"
CATEGORY_CONFIG = "config"
CATEGORY_DOCS = "docs"
CATEGORY_BUILD = "build"
CATEGORY_OTHER = "other"

_DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
_CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".properties", ".env"}
_BUILD_FILENAMES = {
    "dockerfile", "makefile", "cmakelists.txt", "build.gradle", "build.gradle.kts", "pom.xml",
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "go.mod",
    "cargo.toml", "gemfile", "procfile", "docker-compose.yml", "docker-compose.yaml",
}
_TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec", "specs", "testing"}


def is_secret_file(filename: str) -> bool:
    name = filename.lower()
    if any(fnmatch.fnmatch(name, pat) for pat in SECRET_FILE_ALLOWLIST):
        return False
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_FILE_PATTERNS)


def classify_file(rel_path: str, language: str) -> str:
    """Categorise a repository-relative path as source, test, config, docs, build or other."""
    posix = rel_path.replace("\\", "/")
    parts = [p.lower() for p in posix.split("/")]
    name = parts[-1]
    stem, ext = os.path.splitext(name)

    if name in _BUILD_FILENAMES or name.startswith("dockerfile") or posix.lower().startswith(".github/workflows/"):
        return CATEGORY_BUILD
    if language and language != "unknown":
        is_test = (
            any(p in _TEST_DIR_NAMES for p in parts[:-1])
            or stem.startswith("test_")
            or stem.endswith(("_test", ".test", ".spec", "_spec"))
            or stem.startswith("test") and stem[4:5].isupper()
        )
        return CATEGORY_TEST if is_test else CATEGORY_SOURCE
    if ext in _DOC_EXTENSIONS or stem in {"readme", "license", "changelog", "contributing"}:
        return CATEGORY_DOCS
    if ext in _CONFIG_EXTENSIONS or name.startswith(".") or name.endswith("rc"):
        return CATEGORY_CONFIG
    return CATEGORY_OTHER


class FileWalker:
    def __init__(self, max_file_size_bytes: int = MAX_FILE_SIZE_BYTES, max_files: int = MAX_FILES_PER_REPOSITORY):
        self.max_file_size_bytes = max_file_size_bytes
        self.max_files = max_files
        self.detector = LanguageDetector()

    def _is_binary(self, filepath: str) -> bool:
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(8192)
                if b"\x00" in chunk:
                    return True
        except Exception:
            return True
        return False

    @staticmethod
    def _load_gitignore(directory: str) -> pathspec.PathSpec | None:
        gitignore_path = os.path.join(directory, ".gitignore")
        if not os.path.isfile(gitignore_path) or os.path.islink(gitignore_path):
            return None
        try:
            with open(gitignore_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            return None
        try:
            # "gitignore" (pathspec >= 0.12) implements git's negation/directory semantics exactly.
            return pathspec.PathSpec.from_lines("gitignore", lines)
        except Exception:
            return pathspec.PathSpec.from_lines("gitwildmatch", lines)

    @staticmethod
    def _is_ignored(specs: list[tuple[str, pathspec.PathSpec]], rel_path: str, is_dir: bool = False) -> bool:
        """Apply every .gitignore from the root down; each matches paths relative to its own folder."""
        for base, spec in specs:
            if base:
                if not rel_path.startswith(base + "/"):
                    continue
                local = rel_path[len(base) + 1:]
            else:
                local = rel_path
            if spec.match_file(local + "/" if is_dir else local):
                return True
        return False

    def walk(self, root_path: str) -> list[FileInfo]:
        file_infos: list[FileInfo] = []
        real_root = Path(root_path).resolve()
        # (repo-relative directory, spec) for every .gitignore seen on the way down
        specs: list[tuple[str, pathspec.PathSpec]] = []
        limit_hit = False

        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
            rel_dir = os.path.relpath(dirpath, root_path).replace(os.sep, "/")
            rel_dir = "" if rel_dir == "." else rel_dir

            # Nested .gitignore files apply to their own subtree (previously only the root one was read).
            local_spec = self._load_gitignore(dirpath)
            if local_spec is not None:
                specs.append((rel_dir, local_spec))
            active_specs = [(b, s) for b, s in specs if not b or rel_dir == b or rel_dir.startswith(b + "/")]

            # Prune skipped and git-ignored directories so we never descend into them.
            kept_dirs = []
            for d in dirnames:
                if d in SKIP_DIRS:
                    continue
                child_rel = f"{rel_dir}/{d}" if rel_dir else d
                if self._is_ignored(active_specs, child_rel, is_dir=True):
                    continue
                kept_dirs.append(d)
            dirnames[:] = sorted(kept_dirs)

            for filename in sorted(filenames):
                if len(file_infos) >= self.max_files:
                    limit_hit = True
                    break
                lower_filename = filename.lower()
                if lower_filename in SKIP_FILENAMES:
                    continue
                if any(lower_filename.endswith(ext) for ext in SKIP_EXTENSIONS):
                    continue

                filepath = os.path.join(dirpath, filename)
                posix_rel_path = f"{rel_dir}/{filename}" if rel_dir else filename

                if is_secret_file(filename):
                    logger.info("walker_skipped_secret_file", extra={"path": posix_rel_path})
                    continue

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

                if self._is_ignored(active_specs, posix_rel_path):
                    continue

                try:
                    size_bytes = os.path.getsize(filepath)
                except OSError:
                    continue
                if size_bytes > self.max_file_size_bytes:
                    logger.info("walker_skipped_large_file", extra={"path": posix_rel_path, "size_bytes": size_bytes})
                    continue

                if self._is_binary(filepath):
                    continue

                language = self.detector.detect(posix_rel_path, root_path=real_root)
                file_infos.append(
                    FileInfo(
                        path=posix_rel_path,
                        size_bytes=size_bytes,
                        language=language,
                        is_binary=False,
                        category=classify_file(posix_rel_path, language),
                    )
                )
            if limit_hit:
                break

        if limit_hit:
            logger.warning(
                "walker_file_limit_reached",
                extra={"root": str(real_root), "max_files": self.max_files},
            )

        file_infos.sort(key=lambda x: x.path)
        return file_infos

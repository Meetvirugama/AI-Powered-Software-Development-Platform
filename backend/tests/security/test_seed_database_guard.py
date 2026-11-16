"""Database seed guard test (TST-08, ISS-029).

Validates:
- seed_database.py refuses to wipe/drop a non-local or production database without --force and --i-understand.
- System exits with status code 1 when attempting unauthorized execution against remote database.
"""

from unittest.mock import patch
import pytest

from app.core.config import get_settings
from scripts.seed_database import seed


def test_seed_database_refuses_remote_database_without_confirmation() -> None:
    """TST-08: Attempting to seed a remote database without --force and --i-understand exits with code 1."""
    settings = get_settings()
    original_url = settings.database_url
    try:
        settings.database_url = "postgresql://produser:secret@prod-db.internal.postgres.database.azure.com:5432/platform"

        with pytest.raises(SystemExit) as exc_info:
            seed(force=False, i_understand=False)

        assert exc_info.value.code == 1
    finally:
        settings.database_url = original_url


def test_seed_database_refuses_production_env_without_confirmation() -> None:
    """TST-08: Attempting to seed in production environment exits with code 1."""
    settings = get_settings()
    original_env = settings.app_env
    try:
        settings.app_env = "production"

        with pytest.raises(SystemExit) as exc_info:
            seed(force=False, i_understand=False)

        assert exc_info.value.code == 1
    finally:
        settings.app_env = original_env


def test_seed_database_allows_remote_with_explicit_confirmation() -> None:
    """TST-08: When both force=True and i_understand=True are provided, guard does not exit with code 1."""
    settings = get_settings()
    original_url = settings.database_url
    try:
        settings.database_url = "postgresql://produser:secret@prod-db.internal.postgres.database.azure.com:5432/platform"

        # Mock create_engine and Base.metadata so no actual DDL is run against remote
        with patch("scripts.seed_database.create_engine") as mock_engine, \
             patch("scripts.seed_database.Base.metadata.drop_all"), \
             patch("scripts.seed_database.Base.metadata.create_all"), \
             patch("sqlalchemy.orm.sessionmaker"):
            mock_engine.return_value = None
            # Should proceed past guard without sys.exit
            try:
                seed(force=True, i_understand=True)
            except Exception as exc:
                # We only care that the guard did not sys.exit(1)
                _ = exc
    finally:
        settings.database_url = original_url

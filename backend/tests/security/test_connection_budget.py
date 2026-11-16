"""Test connection budget per service role (ISS-032)."""

import os
from unittest.mock import patch
from app.core.database import _get_role_pool_size


def test_api_role_connection_budget():
    with patch.dict(os.environ, {"SERVICE_ROLE": "api"}):
        pool_sz, overflow = _get_role_pool_size()
        assert pool_sz >= 10
        assert overflow >= 5


def test_worker_role_connection_budget():
    with patch.dict(os.environ, {"SERVICE_ROLE": "sync_worker"}):
        pool_sz, overflow = _get_role_pool_size()
        assert pool_sz <= 5
        assert overflow <= 2


def test_migrate_role_connection_budget():
    with patch.dict(os.environ, {"SERVICE_ROLE": "migrate"}):
        pool_sz, overflow = _get_role_pool_size()
        assert pool_sz == 1
        assert overflow == 0

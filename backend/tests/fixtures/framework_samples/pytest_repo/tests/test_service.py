import pytest


def test_service_execution(db_session):
    assert db_session["connected"] is True

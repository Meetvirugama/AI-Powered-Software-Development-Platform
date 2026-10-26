import pytest


@pytest.fixture
def db_session():
    """Mock database session fixture."""
    return {"connected": True}


@pytest.fixture(scope="session", autouse=True)
def configure_environment():
    """Global environment setup fixture."""
    return {"env": "test"}

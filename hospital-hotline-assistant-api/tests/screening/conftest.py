import pytest

from app.services.screening.rules.criteria_store import load_seed_criteria


@pytest.fixture(scope="session")
def criteria():
    return load_seed_criteria()

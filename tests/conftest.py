import pytest


@pytest.fixture(autouse=True)
def _offline_narrator(monkeypatch):
    """Tests must never call the real API, even if the developer has credentials set."""
    monkeypatch.setenv("REROLL_NARRATOR", "mock")

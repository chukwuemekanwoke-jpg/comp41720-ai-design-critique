"""Keep the default runtime budget isolated per test, not in the user's ledger."""
from pathlib import Path
import pytest
from answer_service.budget import DEFAULT_BUDGET_DB, DailyTokenBudget


@pytest.fixture(autouse=True)
def isolated_default_answer_budget(tmp_path, monkeypatch):
    # Production and explicit-path tests use the real SQLite implementation.
    # Redirect only the default filename for tests that do not choose a store.
    def create(path, limit, *args, **kwargs):
        if Path(path) == Path(DEFAULT_BUDGET_DB):
            path = tmp_path / 'default-answer-budget.sqlite3'
        return DailyTokenBudget(path, limit, *args, **kwargs)
    monkeypatch.setattr('answer_service.app.DailyTokenBudget', create)
    monkeypatch.setattr('answer_service.ollama.DailyTokenBudget', create)

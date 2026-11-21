"""Persistent UTC-day admission quota, charged before each model attempt.

Charges are conservative context-plus-output allowances, not measured usage.
Never refund: unknown usage, cancellation and a crash cannot restore allowance.
"""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Callable

DEFAULT_BUDGET_DB = 'state/answer-budget.sqlite3'


class BudgetExhausted(Exception):
    pass


class BudgetUnavailable(Exception):
    pass


class DailyTokenBudget:
    def __init__(self, path: str | Path, limit: int,
                 clock: Callable[[], datetime] | None = None):
        if type(limit) is not int or limit <= 0:
            raise ValueError('Daily token allowance must be a positive integer')
        self.path = Path(path).expanduser().resolve()
        self.limit = limit
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def charge(self, allowance: int) -> int:
        """Atomically charge the full attempt allowance; return remaining quota.

        Separate instances/processes sharing this file serialize via SQLite.
        Limit reductions keep prior usage; no row is reset on a restart.
        """
        if type(allowance) is not int or allowance <= 0:
            raise ValueError('Attempt allowance must be a positive integer')
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError('Budget clock must include a timezone')
        day = now.astimezone(timezone.utc).date().isoformat()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.2)) as connection:
                connection.execute('''CREATE TABLE IF NOT EXISTS daily_usage (
                    day TEXT PRIMARY KEY, charged INTEGER NOT NULL CHECK(charged >= 0)
                )''')
                connection.execute('BEGIN IMMEDIATE')
                row = connection.execute('SELECT charged FROM daily_usage WHERE day=?', (day,)).fetchone()
                charged = row[0] if row else 0
                if type(charged) is not int or charged < 0:
                    raise BudgetUnavailable('Invalid budget ledger')
                # Subtract rather than add before checking the limit.
                if allowance > self.limit - charged:
                    raise BudgetExhausted('Daily model allowance exhausted')
                total = charged + allowance
                connection.execute('''INSERT INTO daily_usage(day,charged) VALUES (?,?)
                    ON CONFLICT(day) DO UPDATE SET charged=excluded.charged''', (day, total))
                connection.commit()
                # Commit and close before the HTTP attempt can be admitted.
            return self.limit - total
        except (sqlite3.Error, OSError) as error:
            raise BudgetUnavailable('Daily budget ledger unavailable') from error

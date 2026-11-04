"""Read the published storage contract without importing Indexer internals."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import re
import sqlite3

from .repository import IndexSnapshot, IndexUnavailable, IndexVersionNotFound, Passage


class SQLitePassageRepository:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path).resolve()

    def _connect(self):
        return sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)

    def pin(self, index_version: str | None = None) -> IndexSnapshot:
        explicit = index_version is not None
        if explicit:
            if not re.fullmatch(r'idx-[1-9][0-9]{0,18}', index_version):
                raise IndexVersionNotFound(index_version)
            version = int(index_version[4:])
            if version > 9223372036854775807:
                raise IndexVersionNotFound(index_version)
        try:
            with closing(self._connect()) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute('PRAGMA query_only = ON')
                connection.execute('BEGIN')
                if not explicit:
                    current = connection.execute(
                        'SELECT index_version FROM current_index WHERE singleton = 1'
                    ).fetchone()
                    if current is None:
                        raise IndexUnavailable()
                    version = current['index_version']
                published = connection.execute(
                    'SELECT index_version FROM published_index_versions WHERE index_version = ?',
                    (version,),
                ).fetchone()
                if published is None:
                    if explicit:
                        raise IndexVersionNotFound(index_version)
                    raise IndexUnavailable()
                rows = connection.execute(
                    '''SELECT passage_id, source_id, snapshot_id, source_version,
                              source_url, text, checked_at
                       FROM published_passages WHERE index_version = ?
                       ORDER BY source_id, position''', (version,),
                ).fetchall()
                if not rows:
                    raise IndexUnavailable()
                timestamps = [datetime.fromisoformat(r['checked_at'].replace('Z', '+00:00')) for r in rows]
                if any(t.utcoffset() is None for t in timestamps):
                    raise ValueError('Indexed check timestamps must have a timezone')
                # Conservative collection freshness: the oldest indexed source check.
                # This does not claim knowledge of later unchanged Collector checks.
                snapshot = IndexSnapshot(
                    f'idx-{version}', min(timestamps), tuple(
                        Passage(r['passage_id'], r['source_id'], r['snapshot_id'],
                                r['source_version'], r['source_url'], r['text']) for r in rows
                    ),
                )
                connection.commit()
                return snapshot
        except (sqlite3.Error, ValueError, TypeError, OverflowError) as error:
            raise IndexUnavailable() from error

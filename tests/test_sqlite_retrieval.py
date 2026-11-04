import hashlib
import sqlite3

import pytest

from indexing_worker.index import SQLiteIndexBuilder
from indexing_worker.models import DocumentUpdateEvent, SnapshotResponse
from indexing_worker.store import IndexerStore
from retrieval_api.repository import IndexUnavailable, IndexVersionNotFound
from retrieval_api.sqlite_repository import SQLitePassageRepository


def candidate(store, text, version=1, source='S001', checked='2026-10-31T12:00:00Z'):
    digest = hashlib.sha256(text.encode()).hexdigest()
    event = DocumentUpdateEvent(f'{source}:{version}', source, version, f'{source}:{digest}',
                                digest, 'https://www.irishimmigration.ie/test/', checked, 'main-text-v1')
    snapshot = SnapshotResponse(event.snapshot_id, source, digest, event.cleaner_version, text)
    store.start_attempt(event)
    return event, SQLiteIndexBuilder(store).build_index(event, snapshot)


def test_missing_database_is_unavailable_without_creating_it(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    with pytest.raises(IndexUnavailable):
        SQLitePassageRepository(path).pin()
    assert not path.exists()


def test_candidates_hidden_and_old_published_versions_retained(tmp_path):
    path = tmp_path / 'index.sqlite3'
    reader = SQLitePassageRepository(path)
    with IndexerStore(path) as store:
        event, first = candidate(store, 'Synthetic old passage')
        with pytest.raises(IndexUnavailable):
            reader.pin()
        with pytest.raises(IndexVersionNotFound):
            reader.pin(f'idx-{first}')
        store.activate(event, first)
        pinned = reader.pin()
        event, second = candidate(store, 'Synthetic new passage', version=2)
        assert reader.pin() == pinned
        store.activate(event, second)
        assert reader.pin().passages[0].text == 'Synthetic new passage'
        assert reader.pin(pinned.index_version) == pinned
        assert pinned.passages[0].source_version == 1
        assert pinned.passages[0].snapshot_id.startswith('S001:')
        assert pinned.passages[0].url == event.source_url


@pytest.mark.parametrize('version', ['idx-0', 'idx-01', 'idx--1', 'demo-idx-1',
                                    'idx-9223372036854775808', 'idx-999999999999999999999999999'])
def test_invalid_explicit_version_never_falls_back(tmp_path, version):
    with pytest.raises(IndexVersionNotFound):
        SQLitePassageRepository(tmp_path / 'missing').pin(version)


def test_reader_remains_on_one_generation_during_publication(tmp_path, monkeypatch):
    path = tmp_path / 'index.sqlite3'
    reader = SQLitePassageRepository(path)
    with IndexerStore(path) as store:
        event, first = candidate(store, 'Synthetic old passage')
        store.activate(event, first)
        newer, second = candidate(store, 'Synthetic new passage', version=2)
        connect = reader._connect
        published = False

        def traced_connect():
            connection = connect()
            def trace(sql):
                nonlocal published
                # The pointer SELECT has already established the read snapshot.
                if 'FROM published_index_versions' in sql and not published:
                    published = True
                    store.activate(newer, second)
            connection.set_trace_callback(trace)
            return connection

        monkeypatch.setattr(reader, '_connect', traced_connect)
        pinned = reader.pin()
        assert published
        assert pinned.index_version == f'idx-{first}'
        assert pinned.passages[0].text == 'Synthetic old passage'
        assert reader.pin().index_version == f'idx-{second}'


def test_readonly_access_and_conservative_freshness(tmp_path):
    path = tmp_path / 'index.sqlite3'
    reader = SQLitePassageRepository(path)
    with IndexerStore(path) as store:
        event, first = candidate(store, 'Source one', checked='2026-10-30T12:00:00Z')
        store.activate(event, first)
        event, second = candidate(store, 'Source two', source='S002')
        store.activate(event, second)
        view = reader.pin()
        assert len(view.passages) == 2
        assert view.last_success_at.isoformat() == '2026-10-30T12:00:00+00:00'
        connection = reader._connect()
        try:
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                connection.execute('DELETE FROM current_index')
        finally:
            connection.close()


def test_unreadable_schema_returns_unavailable(tmp_path):
    path = tmp_path / 'empty.sqlite3'
    sqlite3.connect(path).close()
    with pytest.raises(IndexUnavailable):
        SQLitePassageRepository(path).pin()

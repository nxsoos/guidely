"""Independent regression checks for connection reuse without weakening locks."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from backend.db import Database
from backend.errors import AppError


@pytest.fixture
def tracked_database(monkeypatch):
    import psycopg

    connections = []
    state = {'lock_owner': None}

    class Connection:
        def __init__(self):
            self.queries = []
            self.closed = False
            self.exit_kind = None
            self.result = None

        def __enter__(self):
            return self

        def __exit__(self, kind, error, traceback):
            self.closed = True
            self.exit_kind = kind
            if state['lock_owner'] is self:
                state['lock_owner'] = None

        def execute(self, sql, args=()):
            assert not self.closed
            self.queries.append(sql)
            if 'pg_try_advisory_xact_lock' in sql:
                acquired = state['lock_owner'] in (None, self)
                if acquired:
                    state['lock_owner'] = self
                self.result = {'acquired': acquired}
            return self

        def fetchone(self):
            return self.result

    def connect(*args, **kwargs):
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(psycopg, 'connect', connect)
    return Database(SimpleNamespace(database_url='unused-local-test')), connections, state


def test_regular_scopes_reuse_one_handle_and_close_at_outer_exit(tracked_database):
    db, connections, _ = tracked_database
    with db.session() as outer:
        db.execute('SELECT 1')
        with db.session() as inner:
            assert inner is outer
            db.execute('SELECT 2')
        assert not outer.closed
        assert db.local.connection is outer
    assert len(connections) == 1
    assert outer.closed
    assert db.local.connection is None


def test_reused_scope_still_acquires_and_retains_database_lock(tracked_database):
    db, connections, state = tracked_database
    with db.session() as connection:
        assert state['lock_owner'] is None
        with db.lock:
            assert state['lock_owner'] is connection
            with db.lock:
                db.execute('SELECT 1')
        assert len([sql for sql in connection.queries if 'pg_try_advisory_xact_lock' in sql]) == 1
        # Transaction locks belong to the transaction, even if an inner Python
        # context has ended. It remains protected until the outer scope closes.
        assert state['lock_owner'] is connection
    assert state['lock_owner'] is None
    assert len(connections) == 1


def test_detached_status_scope_uses_own_transaction_then_restores_lock(tracked_database):
    db, connections, state = tracked_database
    with db.lock:
        locked_connection = db.local.connection
        with db.session(detached=True) as status_connection:
            assert status_connection is not locked_connection
            db.execute('UPDATE jobs SET state=?', ('indexing',))
            with db.session() as nested_status:
                assert nested_status is status_connection
        assert status_connection.closed
        assert status_connection.exit_kind is None
        assert db.local.connection is locked_connection
        assert state['lock_owner'] is locked_connection
        assert not locked_connection.closed
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)
    assert db.local.connection is None


def test_detached_scope_does_not_inherit_outer_advisory_lock(tracked_database):
    db, _, state = tracked_database
    with db.lock:
        owner = db.local.connection
        with db.session(detached=True) as detached:
            with pytest.raises(AppError) as failure:
                with db.lock:
                    pytest.fail('A separate connection must not inherit the outer lock.')
            assert failure.value.code == 'indexing_conflict'
            assert any('pg_try_advisory_xact_lock' in sql for sql in detached.queries)
            assert db.local.connection is detached
            assert state['lock_owner'] is owner
        assert db.local.connection is owner
    assert not db.local.lock_frames


def test_error_restores_and_closes_detached_scope_without_losing_outer(tracked_database):
    db, connections, _ = tracked_database
    with db.session() as outer:
        with pytest.raises(ValueError):
            with db.session(detached=True):
                raise ValueError('simulated status-write failure')
        assert db.local.connection is outer
        assert not outer.closed
        assert connections[1].closed
        assert connections[1].exit_kind is ValueError
    assert db.local.connection is None
    assert all(connection.closed for connection in connections)


def test_reusable_connections_remain_isolated_between_threads(tracked_database):
    db, connections, _ = tracked_database
    barrier = threading.Barrier(2)

    def request():
        with db.session() as connection:
            barrier.wait(timeout=5)
            db.execute('SELECT 1')
            assert db.local.connection is connection
        assert db.local.connection is None
        return connection

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request)
        second = executor.submit(request)
        assert first.result(timeout=10) is not second.result(timeout=10)
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)


def test_failed_login_keeps_its_persisted_attempt(client):
    response = client.post('/api/auth/login', json={'username': 'missing', 'password': 'wrong'})
    assert response.status_code == 401
    attempts = client.app.state.service.db.all('SELECT attempts FROM login_attempts')
    assert attempts == [{'attempts': 1}]


def test_document_list_query_count_stays_constant_and_excludes_private_fields(client, monkeypatch):
    for index in range(4):
        response = client.post('/api/documents', files={'file': (f'guide-{index}.md', b'# Guide\nTeam policy.')})
        assert response.status_code == 201
    db = client.app.state.service.db
    original = db.all
    queries = []

    def record(sql, args=()):
        queries.append(sql)
        return original(sql, args)

    monkeypatch.setattr(db, 'all', record)
    response = client.get('/api/documents')
    assert response.status_code == 200
    assert len(response.json()) == 4
    assert len(queries) == 2  # Authorize once, fetch metadata once regardless of count.
    assert not any('SELECT *' in sql.upper() for sql in queries)
    assert all('text' not in item and 'object_key' not in item for item in response.json())
    assert all(isinstance(item['tags'], list) for item in response.json())
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username': 'reader', 'password': 'test-password-123'})
    queries.clear()
    assert client.get('/api/documents').json() == []
    assert len(queries) == 2


def test_embedding_batch_reuses_duplicate_and_cached_texts(client, monkeypatch):
    service = client.app.state.service
    provider_embed = service.provider.embed
    batches = []
    reads = []
    original = service.db.all

    def generate(texts):
        batches.append(texts)
        return provider_embed(texts)

    def record(sql, args=()):
        if 'FROM embeddings' in sql:
            reads.append(sql)
        return original(sql, args)

    monkeypatch.setattr(service.provider, 'embed', generate)
    monkeypatch.setattr(service.db, 'all', record)
    inputs = ['first unique passage', 'second unique passage', 'first unique passage']
    vectors = service.embed(inputs, 'document')
    assert len(vectors) == 3
    assert vectors[0] == vectors[2]
    assert len(batches) == 1 and len(batches[0]) == 2
    assert len(reads) == 1
    assert service.embed(inputs, 'document') == vectors
    assert len(batches) == 1
    assert len(reads) == 2

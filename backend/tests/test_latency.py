from contextlib import contextmanager
import time

from .conftest import upload_index


def test_document_list_selects_metadata_once_and_reuses_auth_connection(client, monkeypatch):
    for _ in range(3):
        upload_index(client)
    db = client.app.state.service.db
    queries = []
    connections = []
    original_all, original_connect = db.all, db.connect
    def traced(sql, args=()):
        queries.append(sql)
        return original_all(sql, args)
    @contextmanager
    def connected():
        if getattr(db.local, 'connection', None) is None:
            connections.append(True)
        with original_connect() as connection:
            yield connection
    monkeypatch.setattr(db, 'all', traced)
    monkeypatch.setattr(db, 'connect', connected)
    result = client.get('/api/documents')
    assert result.status_code == 200
    assert len(result.json()) == 3
    assert all('text' not in doc and 'object_key' not in doc for doc in result.json())
    assert len(queries) == 2  # One session lookup plus one metadata SELECT, independent of library size.
    assert 'SELECT * FROM documents' not in queries[-1]
    assert len(connections) == 1


def test_login_uses_two_connections_and_removes_expired_attempts(client, monkeypatch):
    db = client.app.state.service.db
    db.execute('INSERT INTO login_attempts VALUES (?,?,?)', ('expired-attempt', 8, time.time()-1))
    connections = []
    original_connect = db.connect
    @contextmanager
    def connected():
        if getattr(db.local, 'connection', None) is None:
            connections.append(True)
        with original_connect() as connection:
            yield connection
    monkeypatch.setattr(db, 'connect', connected)
    response = client.post('/api/auth/login', json={'username':'admin','password':'test-password-123'})
    assert response.status_code == 200
    assert len(connections) == 2
    assert db.one('SELECT key FROM login_attempts WHERE key=?', ('expired-attempt',)) is None

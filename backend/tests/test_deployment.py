import time
import pytest
from backend.errors import AppError
from backend.config import Settings
from .conftest import upload_index


def test_direct_upload_permissions_size_and_idempotency(client, monkeypatch):
    service = client.app.state.service
    monkeypatch.setattr(service.storage, 'signed_upload', lambda key: 'https://storage.example/signed')
    content = b'# Policy\nLeave is 25 days.'
    monkeypatch.setattr(service.storage, 'read', lambda key: content)
    intent = client.post('/api/uploads', json={'filename':'policy.md','size':len(content)}).json()
    first = client.post('/api/uploads/' + intent['id'] + '/complete')
    assert first.status_code == 201
    second = client.post('/api/uploads/' + intent['id'] + '/complete')
    assert second.json()['id'] == first.json()['id']
    assert service.db.one('SELECT count(*) n FROM documents')['n'] == 1
    wrong = client.post('/api/uploads', json={'filename':'bad.md','size':1}).json()
    assert client.post('/api/uploads/' + wrong['id'] + '/complete').status_code == 422
    client.post('/api/users', json={'username':'other-admin','password':'test-password-123','role':'admin'})
    client.post('/api/auth/logout')
    client.post('/api/auth/login',json={'username':'other-admin','password':'test-password-123'})
    assert client.post('/api/uploads/' + wrong['id'] + '/complete').status_code == 404
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username':'reader','password':'test-password-123'})
    assert client.post('/api/uploads', json={'filename':'x.md','size':1}).status_code == 403
    assert client.post('/api/uploads/' + wrong['id'] + '/complete').status_code == 403
    assert client.post('/api/uploads/cleanup').status_code == 403


def test_upload_owner_and_expiry(client, monkeypatch):
    service = client.app.state.service
    monkeypatch.setattr(service.storage, 'signed_upload', lambda key:'https://storage.example/signed')
    first = client.post('/api/uploads', json={'filename':'x.md','size':1}).json()
    service.db.execute('UPDATE upload_intents SET expires=? WHERE id=?', (time.time()-121,first['id']))
    assert client.post('/api/uploads/' + first['id'] + '/complete').status_code == 410
    deleted = []
    monkeypatch.setattr(service.storage, 'delete', deleted.append)
    assert client.post('/api/uploads/cleanup').json()['removed'] == 1
    assert deleted == ['documents/' + first['id']]
    assert client.post('/api/uploads/cleanup').json()['removed'] == 0


def test_deletion_hides_content_and_allows_cleanup_retry(client, monkeypatch):
    doc = upload_index(client)
    service = client.app.state.service
    def unavailable(key):
        raise AppError(503,'storage_unavailable','Retry storage later.')
    monkeypatch.setattr(service.storage, 'delete', unavailable)
    assert client.delete('/api/documents/' + doc['id']).status_code == 503
    assert client.get('/api/documents').json()[0]['state'] == 'deleting'
    assert client.get('/api/documents/' + doc['id']).status_code == 404
    assert client.post('/api/search',json={'question':'leave'}).status_code == 404
    monkeypatch.setattr(service.storage,'delete',lambda key:None)
    assert client.delete('/api/documents/' + doc['id']).status_code == 200
    assert client.delete('/api/documents/' + doc['id']).status_code == 200
    assert client.get('/api/documents').json() == []
    assert service.collection.count() == 0
    assert service.db.one('SELECT count(*) n FROM jobs')['n'] == 0


def test_demo_limits(client):
    assert client.post('/api/uploads',json={'filename':'large.md','size':1048577}).status_code == 422
    assert client.post('/api/documents',files={'file':('long.md',b'x'*24001)}).status_code == 413
    assert client.post('/api/documents',files={'file':('sections.md',b'# Header\ntext\n'*13)}).status_code == 413


def test_production_cannot_enable_local_adapter(monkeypatch):
    monkeypatch.setenv('VERCEL','1')
    with pytest.raises(RuntimeError):
        Settings(provider='fake')
    settings = Settings(provider='gemini',test_mode=False,cookie_secure=False)
    assert settings.cookie_secure is True


def test_login_attempts_are_persistent(client):
    for _ in range(10):
        assert client.post('/api/auth/login',json={'username':'missing','password':'bad'}).status_code == 401
    assert client.post('/api/auth/login',json={'username':'missing','password':'bad'}).status_code == 429

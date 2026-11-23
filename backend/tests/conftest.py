import pytest
from fastapi.testclient import TestClient

from backend.auth import create_user
from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, provider='fake', min_similarity=0.0)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app, headers={'X-Guidely': '1'}) as client:
        create_user(app.state.service.db, 'admin', 'test-password-123', 'admin')
        create_user(app.state.service.db, 'reader', 'test-password-123', 'reader')
        client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-123'})
        yield client


def upload_index(client, text='# Leave\nEmployees receive 25 annual leave days. Request leave through the People Portal.'):
    response = client.post('/api/documents', files={'file': ('policy.md', text.encode(), 'text/markdown')})
    assert response.status_code == 201, response.text
    doc = response.json()
    job = client.post(f"/api/documents/{doc['id']}/index").json()
    client.app.state.service.jobs.join()
    assert client.get(f"/api/index-jobs/{job['id']}").json()['state'] == 'complete'
    return doc

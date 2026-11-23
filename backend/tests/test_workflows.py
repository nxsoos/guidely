import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.auth import create_user
from backend.documents import MAX_UPLOAD, chunks, extract
from backend.errors import AppError
from backend.main import create_app
from backend.provider import FakeProvider
from backend.service import Service
from .conftest import upload_index


def test_full_pipeline_and_caches(client):
    doc = upload_index(client)
    query = {'question': 'How many annual leave days do employees receive?'}
    response = client.post('/api/questions', json=query)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['references'][0]['filename'] == 'policy.md'
    assert result['passages'][0]['snippet']
    assert result['elapsed_ms'] > 0
    conversation = client.get('/api/conversations/' + result['conversation_id']).json()
    assert conversation['messages'][0]['question'] == query['question']
    generated = client.get('/metrics').json()['counters']['document_embeddings_generated']
    for _ in range(5):
        assert client.post('/api/questions', json=query).status_code == 200
    counters = client.get('/metrics').json()['counters']
    assert counters['question_cache_hits'] == 5
    assert counters['document_embeddings_generated'] == generated
    client.post(f"/api/documents/{doc['id']}/index")
    assert client.get('/metrics').json()['counters']['unchanged_documents_skipped'] == 1
    followup = client.post('/api/questions', json={'question': 'How do I request it?', 'conversation_id': result['conversation_id']})
    assert followup.status_code == 200
    export = client.get('/api/query-logs/export')
    assert export.status_code == 200 and 'latency_ms' in export.text


def test_edit_removes_stale_search_and_replaces_chunks(client):
    doc = upload_index(client)
    changed = client.patch(f"/api/documents/{doc['id']}", json={'text': '# New policy\nEmployees now receive 30 leave days.', 'tags': ['people'], 'category': 'HR'})
    assert changed.json()['state'] == 'changed'
    assert client.post('/api/search', json={'question': 'leave'}).status_code == 404
    client.post(f"/api/documents/{doc['id']}/index")
    result = client.post('/api/search', json={'question': 'leave', 'tags': ['people'], 'category': 'HR'}).json()
    assert '30 leave days' in result['passages'][0]['snippet']
    assert client.post('/api/search', json={'question': 'leave', 'category': 'IT'}).status_code == 404
    assert client.app.state.service.collection.count() == 1


def test_reader_permissions_and_conversation_privacy(client):
    doc = upload_index(client)
    conversation_id = client.post('/api/questions', json={'question': 'leave days'}).json()['conversation_id']
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username': 'reader', 'password': 'test-password-123'})
    assert client.get('/api/documents').status_code == 200
    assert client.get(f"/api/documents/{doc['id']}/original").status_code == 200
    assert client.post('/api/documents', files={'file': ('x.txt', b'hello')}).status_code == 403
    assert client.patch(f"/api/documents/{doc['id']}", json={'text': 'changed'}).status_code == 403
    assert client.post(f"/api/documents/{doc['id']}/index").status_code == 403
    assert client.get('/metrics').status_code == 403
    assert client.get('/api/query-logs/export').status_code == 403
    assert client.get('/api/users').status_code == 403
    assert client.get('/api/conversations/' + conversation_id).status_code == 404
    assert client.delete('/api/conversations/' + conversation_id).status_code == 404
    assert client.post('/api/questions', json={'question': 'leave', 'conversation_id': conversation_id}).status_code == 404
    assert client.post('/api/questions', json={'question': 'leave'}).status_code == 200


@pytest.mark.parametrize('filename,content,code', [
    ('empty.txt', b'', 'empty_file'), ('spaces.md', b' \n ', 'empty_file'),
    ('bad.pdf', b'not a PDF', 'corrupt_file'), ('binary.txt', b'\x00\x01', 'corrupt_file'),
    ('bad.txt', b'\xff\xfe', 'corrupt_file'), ('bad.exe', b'hello', 'unsupported_file'),
    ('large.txt', b'x'*(MAX_UPLOAD+1), 'file_too_large')], ids=['empty','spaces','corrupt-pdf','binary','encoding','unsupported','oversized'])
def test_invalid_uploads(client, filename, content, code):
    response = client.post('/api/documents', files={'file': (filename, content)})
    assert response.status_code in (413, 415, 422)
    assert response.json()['error']['code'] == code


def test_image_only_pdf(client):
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO(); writer.write(stream)
    response = client.post('/api/documents', files={'file': ('scan.pdf', stream.getvalue())})
    assert response.json()['error']['code'] == 'image_only_pdf'


def test_text_pdf_and_page_metadata():
    # Minimal genuine PDF content stream containing selectable text.
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    for phrase in ('First page policy', 'Second page policy'):
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject(); stream.set_data(f'BT /F1 12 Tf 10 100 Td ({phrase}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output)
    text = extract('policy.pdf', output.getvalue())
    parts = chunks(text, True)
    assert [p['page'] for p in parts] == [1, 2]
    assert 'Second page' in parts[1]['snippet']


def test_empty_missing_key_no_results_and_timeout(client):
    assert client.post('/api/questions', json={'question': '   '}).json()['error']['code'] == 'empty_query'
    assert client.post('/api/questions', json={'question': 'leave'}).status_code == 404
    doc = upload_index(client)
    service = client.app.state.service
    service.settings.min_similarity = 1.1
    assert client.post('/api/questions', json={'question': 'unrelated'}).status_code == 404
    service.settings.min_similarity = 0
    class Timeout(FakeProvider):
        def answer(self, question, passages):
            raise AppError(504, 'model_timeout', 'The AI service took too long.')
    service.provider = Timeout()
    response = client.post('/api/questions', json={'question': 'leave days'})
    assert response.status_code == 504
    assert client.get('/metrics').json()['errors']['model_timeout'] == 1
    from backend.provider import OpenAIProvider
    service.settings.api_key = ''
    service.provider = OpenAIProvider(service.settings)
    response = client.post('/api/search', json={'question': 'uncached query'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'missing_model_key'


@pytest.mark.parametrize('generated', [
    {'answer': 'Invented [999]', 'source_ids': ['999'], 'supported': True},
    {'answer': 'No citation', 'source_ids': ['1'], 'supported': True},
    {'answer': 'Claim [1] and [999]', 'source_ids': ['1'], 'supported': True},
    {'answer': 'Not enough evidence', 'source_ids': [], 'supported': False},
    {'answer': 42, 'source_ids': ['1'], 'supported': True}])
def test_unverified_answers_rejected(client, generated):
    upload_index(client)
    class Invalid(FakeProvider):
        def answer(self, question, passages):
            return generated
    client.app.state.service.provider = Invalid()
    response = client.post('/api/questions', json={'question': 'leave days'})
    assert response.status_code in (502, 404)
    assert client.get('/api/conversations').json() == []


def test_accounts_and_sessions(client):
    user = client.post('/api/users', json={'username': 'second', 'password': 'long-password-123', 'role': 'reader'}).json()
    assert client.post('/api/users', json={'username': 'second', 'password': 'long-password-123'}).status_code == 409
    admin = client.get('/api/auth/me').json()
    assert client.patch('/api/users/' + admin['id'], json={'role': 'reader'}).status_code == 409
    assert client.patch('/api/users/' + user['id'], json={'role': 'admin'}).status_code == 200
    assert client.patch('/api/users/' + user['id'], json={'password': 'changed-password-123'}).status_code == 200
    client.post('/api/auth/logout')
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/login', json={'username': 'second', 'password': 'long-password-123'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'second', 'password': 'changed-password-123'}).status_code == 200
    assert client.cookies.get('guidely_session')
    token = client.cookies.get('guidely_session')
    assert not client.app.state.service.db.one('SELECT * FROM sessions WHERE token=?', (token,))
    client.headers.pop('X-Guidely')
    assert client.post('/api/auth/logout').status_code == 403


def test_chunk_size_overlap_and_headings():
    parts = chunks('# Policy\n' + 'A word about leave. ' * 500)
    assert len(parts) > 1
    assert all(len(p['snippet']) <= 2800 for p in parts)
    assert all(p['section'] == 'Policy' for p in parts)
    assert parts[0]['snippet'][-100:] in parts[1]['snippet']


def test_persistence_and_interrupted_job_recovery(client, settings):
    doc = upload_index(client)
    result = client.post('/api/questions', json={'question': 'leave days'}).json()
    service = client.app.state.service
    service.db.execute("INSERT INTO jobs(id,document_id,state,created_at) VALUES ('recover',?,'indexing','2026-01-01')", (doc['id'],))
    another = create_app(settings)
    with TestClient(another, headers={'X-Guidely': '1'}) as restarted:
        restarted.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-123'})
        assert restarted.get('/api/index-jobs/recover').json()['state'] == 'indexing'
        assert restarted.post(f"/api/documents/{doc['id']}/index").json()['state'] == 'complete'
        assert restarted.get('/api/index-jobs/recover').json()['state'] == 'failed'
        assert restarted.get('/api/conversations/' + result['conversation_id']).status_code == 200
        original = restarted.get(f"/api/documents/{doc['id']}/original")
        assert original.status_code == 200 and b'25 annual leave days' in original.content
        assert restarted.post('/api/search', json={'question': 'leave days'}).status_code == 200
        assert restarted.get('/metrics').json()['chunks'] >= 1


def test_indexing_failure_and_retry(client):
    doc = client.post('/api/documents', files={'file': ('policy.txt', b'Leave policy has 25 days.')}).json()
    class Broken(FakeProvider):
        def embed(self, texts):
            raise AppError(503, 'missing_model_key', 'Missing model key.')
    service = client.app.state.service
    service.provider = Broken()
    first = client.post(f"/api/documents/{doc['id']}/index").json()
    assert client.get('/api/index-jobs/' + first['id']).json()['state'] == 'failed'
    assert client.get(f"/api/documents/{doc['id']}").json()['state'] == 'failed'
    service.provider = FakeProvider()
    second = client.post(f"/api/documents/{doc['id']}/index").json()
    assert client.get('/api/index-jobs/' + second['id']).json()['state'] == 'complete'


def test_index_is_request_bound(client):
    doc = client.post('/api/documents', files={'file': ('policy.txt', b'Annual leave is 25 days.')}).json()
    response = client.post(f"/api/documents/{doc['id']}/index")
    assert response.status_code == 202
    assert response.json()['state'] == 'complete'
    assert client.app.state.service.collection.count() == 1


def test_reindexed_source_during_generation_is_rejected(client):
    doc = upload_index(client)
    service = client.app.state.service
    class Changed(FakeProvider):
        def answer(self, question, passages):
            service.db.execute('UPDATE documents SET revision=revision+1 WHERE id=?', (doc['id'],))
            return super().answer(question, passages)
    service.provider = Changed()
    response = client.post('/api/questions', json={'question': 'leave days'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'documents_changed'

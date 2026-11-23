import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.auth import create_user
from backend.config import Settings
from backend.errors import AppError
from backend.main import create_app
from backend.provider import GeminiProvider
from backend.service import Service
from .conftest import upload_index


def gemini(tmp_path, handler):
    settings = Settings(data_dir=tmp_path, provider='gemini', api_key='gemini-test-secret',
                        embedding_model='gemini-embedding-001', chat_model='gemini-2.5-flash-lite', min_similarity=0)
    return settings, GeminiProvider(settings, transport=httpx.MockTransport(handler))


def result(text):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]}


def test_gemini_embedding_batch_wire_format(tmp_path):
    def handler(request):
        assert request.url.host == 'generativelanguage.googleapis.com'
        assert request.url.path.endswith('/gemini-embedding-001:batchEmbedContents')
        assert request.headers['x-goog-api-key'] == 'gemini-test-secret'
        assert 'key=' not in str(request.url)
        payload = json.loads(request.content)
        assert [r['content']['parts'][0]['text'] for r in payload['requests']] == ['one', 'two']
        assert all(r['model'] == 'models/gemini-embedding-001' for r in payload['requests'])
        return httpx.Response(200, json={'embeddings': [{'values': [1, 0]}, {'values': [0, 1]}]})
    _, provider = gemini(tmp_path, handler)
    assert provider.embed(['one', 'two']) == [[1, 0], [0, 1]]
    assert provider.embed([]) == []


def test_gemini_answer_schema_and_followup(tmp_path):
    def handler(request):
        assert request.url.path.endswith('/gemini-2.5-flash-lite:generateContent')
        payload = json.loads(request.content)
        assert 'untrusted data' in payload['systemInstruction']['parts'][0]['text']
        if 'responseJsonSchema' in payload['generationConfig']:
            assert payload['generationConfig']['responseMimeType'] == 'application/json'
            return httpx.Response(200, json=result(json.dumps({'answer': '25 days [1]', 'source_ids': ['1'], 'supported': True})))
        return httpx.Response(200, json=result('How many leave days?'))
    _, provider = gemini(tmp_path, handler)
    assert provider.answer('leave?', [{'source_id': '1', 'snippet': '25 days'}])['source_ids'] == ['1']
    assert provider.rewrite('How many?', [{'question': 'Leave?', 'answer': 'Annual leave.'}]) == 'How many leave days?'
    assert provider.rewrite('initial', []) == 'initial'


@pytest.mark.parametrize('status,body,code', [
    (400, {'error': {'details': [{'reason': 'API_KEY_INVALID'}]}}, 'invalid_model_key'),
    (400, {'error': {'details': None}}, 'model_request_rejected'),
    (401, {}, 'invalid_model_key'), (403, {}, 'model_access_denied'),
    (404, {}, 'model_not_found'), (429, {}, 'model_rate_limited'),
    (500, {}, 'model_failure'), (503, {}, 'model_failure'),
])
def test_gemini_errors_are_safe(tmp_path, status, body, code):
    body.setdefault('error', {})['message'] = 'private provider account information'
    _, provider = gemini(tmp_path, lambda r: httpx.Response(status, json=body))
    with pytest.raises(AppError) as caught:
        provider.embed(['text'])
    assert caught.value.code == code
    assert 'private provider' not in caught.value.message
    assert 'gemini-test-secret' not in caught.value.message


@pytest.mark.parametrize('payload', [{}, {'embeddings': []}, {'embeddings': [{'values': []}]}, {'embeddings': [{'values': ['bad']}]}])
def test_gemini_invalid_embeddings(tmp_path, payload):
    _, provider = gemini(tmp_path, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(AppError, match='embeddings'):
        provider.embed(['text'])


@pytest.mark.parametrize('payload', [{}, {'candidates': []}, {'candidates': [{'finishReason': 'SAFETY'}]}, result('not JSON')])
def test_gemini_invalid_answers(tmp_path, payload):
    _, provider = gemini(tmp_path, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(AppError) as caught:
        provider.answer('question', [])
    assert caught.value.code == 'invalid_model_output'


def test_gemini_missing_key_and_timeout(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout('private network detail', request=request)
    settings, provider = gemini(tmp_path, handler)
    with pytest.raises(AppError) as caught:
        provider.embed(['text'])
    assert caught.value.status == 504
    settings.api_key = ''
    with pytest.raises(AppError, match='GEMINI_API_KEY'):
        provider.embed(['text'])


def test_provider_specific_settings(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'google-test-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'openai-test-key')
    monkeypatch.setenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001')
    monkeypatch.setenv('GEMINI_CHAT_MODEL', 'gemini-2.5-flash-lite')
    google = Settings(provider='gemini')
    other = Settings(provider='openai')
    assert google.api_key == 'google-test-key'
    assert other.api_key == 'openai-test-key'
    assert google.embedding_model == 'gemini-embedding-001'
    assert 'google-test-key' not in repr(google)


def test_missing_inline_citation_is_regenerated_once(tmp_path):
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        answer = '25 days.' if len(calls) == 1 else '25 days [1].'
        return httpx.Response(200, json=result(json.dumps({'answer': answer, 'source_ids': ['1'], 'supported': True})))
    _, provider = gemini(tmp_path, handler)
    answer = provider.answer('leave days?', [{'source_id': '1', 'snippet': '25 days'}])
    assert answer['answer'] == '25 days [1].'
    assert len(calls) == 2
    assert 'failed citation validation' in calls[1]['systemInstruction']['parts'][0]['text']


def test_failed_citation_repair_is_bounded_and_not_fabricated(tmp_path):
    from backend.citations import citations_valid
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=result(json.dumps({'answer': '25 days [999].', 'source_ids': ['999'], 'supported': True})))
    _, provider = gemini(tmp_path, handler)
    passages = [{'source_id': '1', 'snippet': '25 days'}]
    answer = provider.answer('leave days?', passages)
    assert len(calls) == 2
    assert not citations_valid(answer, passages)
    assert answer['source_ids'] == ['999']


def test_gemini_full_api_workflow(tmp_path):
    def handler(request):
        payload = json.loads(request.content)
        if request.url.path.endswith(':batchEmbedContents'):
            return httpx.Response(200, json={'embeddings': [{'values': [1.0, 0.0]} for _ in payload['requests']]})
        if 'responseMimeType' in payload['generationConfig']:
            return httpx.Response(200, json=result(json.dumps({'answer': '25 days [1]', 'source_ids': ['1'], 'supported': True})))
        return httpx.Response(200, json=result('How many leave days?'))
    settings, provider = gemini(tmp_path, handler)
    app = create_app(settings, provider=provider)
    with TestClient(app, headers={'X-Guidely': '1'}) as client:
        create_user(app.state.service.db, 'admin', 'test-password-123', 'admin')
        client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-123'})
        doc = upload_index(client)
        assert client.get('/health').json()['provider'] == 'gemini'
        assert client.get('/health').json()['ai_configured'] is True
        answer = client.post('/api/questions', json={'question': 'leave days'})
        assert answer.status_code == 200
        assert answer.json()['references'][0]['document_id'] == doc['id']
        followup = client.post('/api/questions', json={'question': 'How many?', 'conversation_id': answer.json()['conversation_id']})
        assert followup.status_code == 200
        assert client.post('/api/questions', json={'question': 'leave days'}).status_code == 200
        assert client.get('/metrics').json()['counters']['question_cache_hits'] >= 1
    other_settings = Settings(data_dir=tmp_path, provider='openai', api_key='test-only', min_similarity=0)
    other = Service(other_settings)
    assert other.collection.name != app.state.service.collection.name
    assert other.collection.count() == 0
    with pytest.raises(AppError) as caught:
        other.search('leave days')
    assert caught.value.code == 'no_results'

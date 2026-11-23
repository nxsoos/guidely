import json

import httpx
import pytest
from openai import OpenAI

from backend.errors import AppError
from backend.provider import OpenAIProvider


def mocked_provider(settings, handler):
    provider = OpenAIProvider(settings)
    provider.client = lambda: OpenAI(api_key='test-not-a-real-key', max_retries=0,
                                     http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return provider


def test_openai_embedding_wire_format(settings):
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == '/v1/embeddings'
        assert payload['model'] == settings.embedding_model
        assert payload['input'] == ['some text']
        return httpx.Response(200, json={'object': 'list', 'data': [{'object': 'embedding', 'embedding': [0.1, 0.2], 'index': 0}],
                                         'model': settings.embedding_model, 'usage': {'prompt_tokens': 2, 'total_tokens': 2}})
    assert mocked_provider(settings, handler).embed(['some text']) == [[0.1, 0.2]]


def test_openai_structured_answer_and_rewrite(settings):
    requests = []
    def handler(request):
        payload = json.loads(request.content); requests.append(payload)
        assert request.url.path == '/v1/responses'
        assert payload['store'] is False
        text = json.dumps({'answer': '25 days [1]', 'source_ids': ['1'], 'supported': True}) if 'text' in payload else 'How many leave days?'
        return httpx.Response(200, json={'id': 'resp_test', 'object': 'response', 'created_at': 1,
                                         'status': 'completed', 'model': settings.chat_model,
                                         'output': [{'type': 'message', 'id': 'msg_test', 'role': 'assistant', 'status': 'completed',
                                                     'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}]})
    provider = mocked_provider(settings, handler)
    assert provider.answer('leave?', [{'source_id': '1', 'snippet': '25 days'}])['source_ids'] == ['1']
    assert requests[0]['text']['format']['strict'] is True
    assert provider.rewrite('How many?', [{'question': 'Leave?', 'answer': 'Ask about leave.'}]) == 'How many leave days?'
    assert provider.rewrite('No history?', []) == 'No history?'


@pytest.mark.parametrize('status,code', [(401, 'invalid_model_key'), (429, 'model_rate_limited'), (500, 'model_failure')])
def test_provider_errors_are_sanitized(settings, status, code):
    provider = mocked_provider(settings, lambda request: httpx.Response(status, json={'error': {'message': 'private provider detail', 'type': 'api_error'}}))
    with pytest.raises(AppError) as caught:
        provider.embed(['text'])
    assert caught.value.code == code
    assert 'private provider detail' not in caught.value.message


def test_provider_timeout(settings):
    def handler(request):
        raise httpx.ReadTimeout('private networking detail', request=request)
    with pytest.raises(AppError) as caught:
        mocked_provider(settings, handler).embed(['text'])
    assert caught.value.status == 504


@pytest.mark.parametrize('provider_code,expected', [
    ('credit_balance_exhausted', 'model_credits_exhausted'),
    ('insufficient_quota', 'model_quota_exceeded'),
    ('project_spend_limit_exceeded', 'model_quota_exceeded'),
    ('organization_usage_limit_exceeded', 'model_quota_exceeded'),
    ('rate_limit_exceeded', 'model_rate_limited'),
])
def test_quota_errors_distinguished_from_rate_limits(settings, provider_code, expected):
    provider = mocked_provider(settings, lambda request: httpx.Response(429, json={
        'error': {'code': provider_code, 'message': 'private account detail'}}))
    with pytest.raises(AppError) as caught:
        provider.embed(['text'])
    assert caught.value.code == expected
    assert 'private account detail' not in caught.value.message

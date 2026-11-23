"""Production PostgreSQL adapter smoke test, using mocked Storage and AI.

Requires an EMPTY disposable database with migrations already applied. This writes
test records and counters. Never target production. It does not validate hosted
Supabase Storage, Gemini availability, or a real Vercel deployment.

Set GUIDELY_INTEGRATION_DATABASE_URL privately and
GUIDELY_INTEGRATION_ALLOW_WRITES=1. For PGlite's single-backend socket bridge only,
also set GUIDELY_INTEGRATION_EMBEDDED=1 to skip multi-connection operations.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.auth import create_user
from backend.config import Settings
from backend.db import Database, now, uid
from backend.errors import AppError
from backend.main import create_app


class StubAI:
    def embed(self, texts):
        return [[1.0] + [0.0] * 767 for _ in texts]

    def rewrite(self, question, history):
        return question

    def answer(self, question, passages):
        return {'answer': 'Employees receive 25 leave days [1].',
                'source_ids': ['1'], 'supported': True}


def check(response, status):
    if response.status_code != status:
        # Do not emit response bodies: a provider could include confidential data.
        raise AssertionError(f'Expected HTTP {status}; received {response.status_code}')
    return response.json()


def main():
    url = os.getenv('GUIDELY_INTEGRATION_DATABASE_URL', '')
    if not url or os.getenv('GUIDELY_INTEGRATION_ALLOW_WRITES') != '1':
        print('Set GUIDELY_INTEGRATION_DATABASE_URL and GUIDELY_INTEGRATION_ALLOW_WRITES=1 for an empty disposable migrated database. Never target production.')
        return 2
    embedded = os.getenv('GUIDELY_INTEGRATION_EMBEDDED') == '1'
    settings = Settings(provider='gemini', database_url=url, test_mode=False,
                        supabase_url='https://example.supabase.co',
                        supabase_key='review-dummy-key', api_key='review-dummy-key',
                        embedding_model='gemini-embedding-001',
                        chat_model='gemini-2.5-flash-lite', min_similarity=0.0)
    db = Database(settings)
    for table in ('users', 'documents', 'conversations', 'query_logs', 'embeddings', 'upload_intents'):
        if db.one('SELECT count(*) AS n FROM ' + table)['n']:
            raise RuntimeError('Refusing to write: disposable database must have empty application tables.')
    objects = {}

    def attach_storage(service):
        service.storage.signed_upload = lambda key: 'https://example.supabase.co/review-signed-upload'
        service.storage.read = lambda key: objects[key]
        service.storage.download = lambda key: 'https://example.supabase.co/review-signed-download'
        service.storage.delete = lambda key: objects.pop(key, None)

    app = create_app(settings, provider=StubAI())
    with TestClient(app, base_url='https://testserver', headers={'X-Guidely': '1'}) as client:
        service = app.state.service
        attach_storage(service)
        create_user(db, 'review_admin', 'review-password-123', 'admin')
        create_user(db, 'review_reader', 'review-password-123', 'reader')
        check(client.post('/api/auth/login', json={'username': 'review_admin', 'password': 'review-password-123'}), 200)
        token = client.cookies.get('guidely_session')
        assert not db.one('SELECT * FROM sessions WHERE token=?', (token,))
        payload = b'# Leave\nEmployees receive 25 leave days.'
        intent = check(client.post('/api/uploads', json={'filename': 'leave.md', 'size': len(payload)}), 201)['id']
        objects['documents/' + intent] = payload
        check(client.post('/api/uploads/' + intent + '/complete'), 201)
        check(client.post('/api/uploads/' + intent + '/complete'), 201)
        assert db.one('SELECT count(*) n FROM documents')['n'] == 1
        if embedded:
            # PGlite serializes connections and cannot model detached status writes
            # inside the indexing transaction. Exercise actual production index SQL.
            job = uid()
            db.execute('INSERT INTO jobs (id,document_id,state,created_at) VALUES (?,?,?,?)', (job, intent, 'indexing', now()))
            service.index(job)
            service.index(job)
        else:
            assert check(client.post('/api/documents/' + intent + '/index'), 202)['state'] == 'complete'
            assert check(client.post('/api/documents/' + intent + '/index'), 202)['state'] == 'complete'
        assert service.collection.count() == 1
        answer = check(client.post('/api/questions', json={'question': 'How many leave days?'}), 200)
        assert answer['references'][0]['document_id'] == intent
        assert answer['references'][0]['score'] == 1
        conversation_id = answer['conversation_id']
        check(client.post('/api/auth/logout'), 200)
        check(client.post('/api/auth/login', json={'username': 'review_reader', 'password': 'review-password-123'}), 200)
        check(client.post('/api/uploads', json={'filename': 'a.txt', 'size': 1}), 403)
        check(client.delete('/api/documents/' + intent), 403)
        check(client.get('/api/conversations/' + conversation_id), 404)
        reader_token = client.cookies.get('guidely_session')
    print('PASS: PostgreSQL auth, hashed sessions, permissions, conversation privacy, idempotent upload completion, pgvector indexing/re-indexing, cosine retrieval and citations.')
    with TestClient(create_app(settings, provider=StubAI()), base_url='https://testserver', headers={'X-Guidely': '1'}) as restarted:
        attach_storage(restarted.app.state.service)
        restarted.cookies.set('guidely_session', reader_token)
        check(restarted.get('/api/auth/me'), 200)
        check(restarted.get('/api/documents/' + intent), 200)
        check(restarted.post('/api/questions', json={'question': 'How many leave days?'}), 200)
        assert restarted.app.state.service.collection.count() == 1
        assert db.one('SELECT count(*) n FROM embeddings')['n'] >= 2
        if not embedded:
            check(restarted.post('/api/auth/login', json={'username': 'review_admin', 'password': 'review-password-123'}), 200)
            def fail_delete(key):
                raise AppError(503, 'storage_unavailable', 'Simulated storage interruption.')
            restarted.app.state.service.storage.delete = fail_delete
            check(restarted.delete('/api/documents/' + intent), 503)
            assert db.one('SELECT state FROM documents WHERE id=?', (intent,))['state'] == 'deleting'
            attach_storage(restarted.app.state.service)
            check(restarted.delete('/api/documents/' + intent), 200)
    print('PASS: a second backend app retains PostgreSQL sessions, documents, chunks and embedding cache. Storage and AI are mocked.')
    tables = ('users', 'sessions', 'documents', 'jobs', 'embeddings', 'counters', 'conversations', 'messages', 'query_logs', 'vector_chunks', 'upload_intents', 'login_attempts')
    for table in tables:
        for role in ('anon', 'authenticated'):
            try:
                with db.connect() as connection:
                    connection.execute('SET ROLE ' + role)
                    connection.execute('SELECT * FROM public.' + table)
            except Exception as error:
                assert type(error).__name__ == 'InsufficientPrivilege', type(error).__name__
            else:
                raise AssertionError('Unexpected direct read access: ' + role + ' / ' + table)
    print('PASS: anon and authenticated roles denied all 12 application tables.')
    if embedded:
        db.execute('DELETE FROM documents WHERE id=?', (intent,))
        print('SKIP: detached indexing status writes, deletion endpoint retries and cross-instance lock contention require native PostgreSQL/Supabase; tested index SQL and delete cascade only.')
    assert db.one('SELECT count(*) n FROM vector_chunks')['n'] == 0
    assert db.one('SELECT count(*) n FROM jobs')['n'] == 0
    print('PASS: document deletion cascades vector chunks and indexing jobs. Disposable test records/counters remain in this database.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        # Credentials/DSNs can appear in raw driver errors. Show only the type.
        print('FAIL: ' + type(error).__name__ + '. Inspect locally without sharing credentials or driver output.')
        sys.exit(1)

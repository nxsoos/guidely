import csv
import hashlib
import io
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .auth import create_user, current_user, hash_password, require_admin, verify_password
from .config import Settings
from .db import now, uid
from .documents import MAX_UPLOAD, MAX_TEXT, extract, chunks
from .errors import AppError
from .service import Service

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class UserCreate(Login):
    role: Literal['reader', 'admin'] = 'reader'


class UserUpdate(BaseModel):
    role: Literal['reader', 'admin'] | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


class DocumentUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default='', max_length=80)


class Question(BaseModel):
    question: str = Field(max_length=2000)
    conversation_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default='', max_length=80)


def create_app(settings=None, provider=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        service = Service(settings, provider)
        app.state.service = service
        service.start()
        yield
        service.stop()

    app = FastAPI(title='Guidely', lifespan=lifespan)

    @app.middleware('http')
    async def protect_writes(request: Request, call_next):
        # Custom headers cannot be sent by cross-site forms. No CORS origins are enabled;
        # the Vite proxy keeps browser requests same-origin during local development.
        if request.method in ('POST', 'PATCH', 'DELETE', 'PUT') and request.headers.get('X-Guidely') != '1':
            return JSONResponse(status_code=403, content={'error': {'code': 'csrf_check', 'message': 'Reload the application and try again.'}})
        return await call_next(request)

    def record_error(code):
        if hasattr(app.state, 'service'):
            try:
                app.state.service.db.count('error:' + code)
            except Exception:
                pass
        logging.getLogger('guidely').warning('request_failed code=%s', code)

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        record_error(exc.code)
        return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        record_error('invalid_input')
        return JSONResponse(status_code=422, content={'error': {'code': 'invalid_input', 'message': 'Check the submitted fields and their lengths.'}})

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        record_error('internal_error')
        logging.getLogger('guidely').error('Unhandled request failure type=%s', type(exc).__name__)
        return JSONResponse(status_code=500, content={'error': {'code': 'internal_error', 'message': 'Something went wrong. Please retry or contact an administrator.'}})

    def svc(request):
        return request.app.state.service

    @app.get('/health')
    def health(request: Request):
        with svc(request).db.session():
            service = svc(request)
            service.db.one('SELECT 1')
            service.collection.count()
            return {'status': 'ok', 'provider': settings.provider,
                    'ai_configured': bool(settings.api_key) if settings.provider != 'fake' else False,
                    'processing': 'bounded-request'}

    @app.post('/api/auth/login')
    def login(data: Login, request: Request, response: Response):
        db = svc(request).db
        attempt_key = hashlib.sha256(('login:' + data.username.strip().lower()).encode()).hexdigest()
        instant = time.time()
        # One atomic, committed attempt update; failed authentication must not undo it.
        with db.session():
            db.execute('DELETE FROM login_attempts WHERE key IN (SELECT key FROM login_attempts WHERE expires<? LIMIT 100)', (instant,))
            attempt = db.one('INSERT INTO login_attempts VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET '
                             'attempts=CASE WHEN login_attempts.expires<? THEN 1 ELSE login_attempts.attempts+1 END, '
                             'expires=CASE WHEN login_attempts.expires<? THEN excluded.expires ELSE login_attempts.expires END '
                             'RETURNING attempts', (attempt_key, 1, instant+900, instant, instant))
        if attempt['attempts'] > 10:
            raise AppError(429, 'login_rate_limited', 'Too many login attempts. Wait 15 minutes.')
        with db.session():
            user = db.one('SELECT * FROM users WHERE username=?', (data.username.strip().lower(),))
            if not user or not verify_password(data.password, user['password']):
                raise AppError(401, 'invalid_credentials', 'The username or password is incorrect.')
            db.execute('DELETE FROM login_attempts WHERE key=?', (attempt_key,))
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<?', (instant,))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], instant+86400))
        response.set_cookie('guidely_session', token, httponly=True, secure=settings.cookie_secure, samesite='strict', max_age=86400)
        return {k: user[k] for k in ('id', 'username', 'role')}

    @app.get('/api/auth/me')
    def me(request: Request):
        return current_user(request)

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get('guidely_session', '')
        svc(request).db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie('guidely_session')
        return {'ok': True}

    @app.get('/api/users')
    def users(request: Request):
        with svc(request).db.session():
            require_admin(request)
            return svc(request).db.all('SELECT id,username,role,created_at FROM users ORDER BY username')

    @app.post('/api/users', status_code=201)
    def add_user(data: UserCreate, request: Request):
        require_admin(request)
        return create_user(svc(request).db, data.username, data.password, data.role)

    @app.patch('/api/users/{user_id}')
    def update_user(user_id: str, data: UserUpdate, request: Request):
        actor = require_admin(request)
        service = svc(request)
        with service.lock:
            user = service.db.one('SELECT id,username,role FROM users WHERE id=?', (user_id,))
            if not user:
                raise AppError(404, 'user_not_found', 'That account was not found.')
            if data.role == 'reader' and user['role'] == 'admin' and service.db.one("SELECT count(*) n FROM users WHERE role='admin'")['n'] <= 1:
                raise AppError(409, 'last_admin', 'Keep at least one administrator account.')
            if data.role:
                service.db.execute('UPDATE users SET role=? WHERE id=?', (data.role, user_id))
            if data.password:
                service.db.execute('UPDATE users SET password=? WHERE id=?', (hash_password(data.password), user_id))
                service.db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            return {'ok': True, 'session_reset': bool(data.password), 'self_updated': actor['id'] == user_id}

    @app.get('/api/documents')
    def list_documents(request: Request):
        service = svc(request)
        with service.db.session():
            actor = current_user(request)
            sql = 'SELECT id,filename,tags,category,state,revision,indexed_hash,error,created_at FROM documents'
            if actor['role'] != 'admin':
                sql += " WHERE state='ready'"
            rows = service.db.all(sql + ' ORDER BY created_at DESC')
        return [{**d, 'tags':json.loads(d['tags'])} for d in rows]


    class UploadIntent(BaseModel):
        filename: str = Field(min_length=1, max_length=180)
        size: int = Field(gt=0, le=MAX_UPLOAD)

    def save_upload(service, doc_id, filename, key, content):
        text = extract(filename, content)
        chunks(text, filename.lower().endswith('.pdf'))
        service.db.execute('INSERT INTO documents (id,filename,text,state,created_at,object_key) VALUES (?,?,?,?,?,?)',
                           (doc_id, filename, text, 'pending', now(), key))
        return service.document(doc_id)

    @app.post('/api/uploads', status_code=201)
    def upload_intent(data: UploadIntent, request: Request):
        actor = require_admin(request)
        service = svc(request)
        filename = data.filename.replace('\\', '/').split('/')[-1]
        if Path(filename).suffix.lower() not in ('.txt', '.md', '.pdf'):
            raise AppError(415, 'unsupported_file', 'Upload TXT, Markdown, or PDF.')
        with service.lock:
            if service.db.one('SELECT count(*) n FROM documents')['n'] >= 50:
                raise AppError(409, 'demo_document_limit', 'This demo allows 50 documents. Delete a document first.')
            if service.db.one('SELECT count(*) n FROM upload_intents WHERE user_id=? AND completed=0 AND expires>?', (actor['id'], time.time()))['n'] >= 3:
                raise AppError(429, 'upload_limit', 'Complete pending uploads or wait two hours.')
            intent_id = uid()
            key = 'documents/' + intent_id
            service.db.execute('INSERT INTO upload_intents (id,user_id,filename,object_key,size,expires) VALUES (?,?,?,?,?,?)',
                               (intent_id, actor['id'], filename, key, data.size, time.time()+7200))
            signed_url = service.storage.signed_upload(key)
            return {'id': intent_id, 'upload_url': signed_url}

    if settings.test_mode:
        @app.put('/api/test-uploads/{intent_id}')
        async def test_direct_upload(intent_id: str, request: Request):
            actor = require_admin(request)
            service = svc(request)
            intent = service.db.one('SELECT * FROM upload_intents WHERE id=? AND user_id=?', (intent_id, actor['id']))
            if not intent or intent['completed'] or intent['expires'] < time.time():
                raise AppError(403, 'invalid_upload', 'Upload permission expired or was used.')
            content = bytearray()
            async for part in request.stream():
                content.extend(part)
                if len(content) > MAX_UPLOAD:
                    raise AppError(413, 'file_too_large', 'Files must be 1 MB or smaller.')
            service.storage.write_test(intent['object_key'], bytes(content))
            return {'ok': True}

    @app.post('/api/uploads/cleanup')
    def cleanup_uploads(request: Request):
        require_admin(request)
        service = svc(request)
        removed = 0
        with service.lock:
            intents = service.db.all('SELECT * FROM upload_intents WHERE completed=0 AND expires<? ORDER BY expires LIMIT 5', (time.time()-120,))
            for intent in intents:
                if intent['object_key'] != 'documents/' + intent['id']:
                    raise AppError(409, 'invalid_object_key', 'Unexpected upload key; contact the administrator.')
                if service.db.one('SELECT id FROM documents WHERE object_key=?', (intent['object_key'],)):
                    continue
                service.storage.delete(intent['object_key'])
                service.db.execute('DELETE FROM upload_intents WHERE id=? AND completed=0', (intent['id'],))
                removed += 1
        return {'removed': removed}

    @app.post('/api/uploads/{intent_id}/complete', status_code=201)
    def complete_upload(intent_id: str, request: Request):
        actor = require_admin(request)
        service = svc(request)
        with service.lock:
            intent = service.db.one('SELECT * FROM upload_intents WHERE id=? AND user_id=?', (intent_id, actor['id']))
            if not intent:
                raise AppError(404, 'upload_not_found', 'Upload permission was not found.')
            if intent['completed']:
                return service.document(intent_id)
            if intent['expires'] < time.time():
                raise AppError(410, 'upload_expired', 'Upload permission expired. Start a new upload.')
            if service.db.one('SELECT count(*) n FROM documents')['n'] >= 50:
                raise AppError(409, 'demo_document_limit', 'This demo allows 50 documents.')
            content = service.storage.read(intent['object_key'])
            if len(content) != intent['size']:
                raise AppError(422, 'upload_size_mismatch', 'Uploaded file size does not match the approved upload.')
            doc = save_upload(service, intent_id, intent['filename'], intent['object_key'], content)
            service.db.execute('UPDATE upload_intents SET completed=1 WHERE id=?', (intent_id,))
            return doc

    @app.post('/api/documents', status_code=201)
    def upload(request: Request, file: UploadFile = File(...)):
        require_admin(request)
        service = svc(request)
        if not settings.test_mode:
            raise AppError(400, 'direct_upload_required', 'Use the authenticated direct upload flow.')
        content = file.file.read(MAX_UPLOAD+1)
        filename = (file.filename or 'document').replace('\\', '/').split('/')[-1][:180]
        doc_id = uid()
        doc = save_upload(service, doc_id, filename, doc_id, content)
        service.storage.write_test(doc_id, content)
        return doc

    @app.get('/api/documents/{doc_id}')
    def get_document(doc_id: str, request: Request):
        with svc(request).db.session():
            user = current_user(request)
            doc = svc(request).document(doc_id)
            if user['role'] != 'admin' and doc['state'] != 'ready':
                raise AppError(409, 'document_not_ready', 'This document is not indexed yet.')
            return doc

    @app.get('/api/documents/{doc_id}/original')
    def original(doc_id: str, request: Request):
        user = current_user(request)
        service = svc(request)
        doc = service.document(doc_id)
        if user['role'] != 'admin' and doc['state'] != 'ready':
            raise AppError(409, 'document_not_ready', 'This document is not indexed yet.')
        if settings.test_mode:
            return FileResponse(service.storage.directory / doc['object_key'], filename=doc['filename'], media_type='application/octet-stream')
        return RedirectResponse(service.storage.download(doc['object_key']), status_code=307)

    @app.patch('/api/documents/{doc_id}')
    def edit_document(doc_id: str, data: DocumentUpdate, request: Request):
        require_admin(request)
        service = svc(request)
        if not data.text.strip():
            raise AppError(422, 'empty_file', 'Document text cannot be empty.')
        if any(len(tag) > 50 for tag in data.tags):
            raise AppError(422, 'invalid_tags', 'Tags must be at most 50 characters.')
        with service.lock:
            doc = service.document(doc_id)
            chunks(data.text, doc['filename'].lower().endswith('.pdf'))
            service.db.execute("UPDATE jobs SET state='failed',error='Interrupted; retry indexing.' WHERE document_id=? AND state IN ('queued','indexing')", (doc_id,))
            changed = data.text != doc['text']
            service.db.execute('UPDATE documents SET text=?,tags=?,category=?,state=?,revision=revision+? WHERE id=?',
                               (data.text, json.dumps(sorted(set(t.strip() for t in data.tags if t.strip()))), data.category.strip(),
                                'changed' if changed else doc['state'], int(changed), doc_id))
            return service.document(doc_id)

    @app.delete('/api/documents/{doc_id}')
    def delete_document(doc_id: str, request: Request):
        require_admin(request)
        service = svc(request)
        with service.lock:
            doc = service.db.one('SELECT * FROM documents WHERE id=?', (doc_id,))
            if not doc:
                return {'ok': True}
            # Commit tombstone before external I/O: failed cleanup remains hidden and retryable.
            connection = getattr(getattr(service.db, 'local', None), 'connection', None)
            if connection is not None:
                service.db.local.connection = None
            try:
                service.db.execute("UPDATE documents SET state='deleting' WHERE id=?", (doc_id,))
            finally:
                if connection is not None:
                    service.db.local.connection = connection
            service.storage.delete(doc['object_key'])
            service.db.execute('DELETE FROM documents WHERE id=?', (doc_id,))
            service.db.execute('DELETE FROM upload_intents WHERE id=?', (doc_id,))
            return {'ok': True}

    @app.post('/api/documents/{doc_id}/index', status_code=202)
    def index_document(doc_id: str, request: Request):
        require_admin(request)
        return svc(request).enqueue(doc_id)

    @app.get('/api/index-jobs/{job_id}')
    def get_job(job_id: str, request: Request):
        with svc(request).db.session():
            require_admin(request)
            job = svc(request).db.one('SELECT * FROM jobs WHERE id=?', (job_id,))
            if not job:
                raise AppError(404, 'job_not_found', 'That indexing job was not found.')
            return job

    @app.post('/api/search')
    def search(data: Question, request: Request):
        current_user(request)
        return {'passages': svc(request).search(data.question, data.tags, data.category)}

    @app.post('/api/questions')
    def question(data: Question, request: Request):
        user = current_user(request)
        return svc(request).ask(user, data.question, data.conversation_id, data.tags, data.category)

    @app.get('/api/conversations')
    def conversations(request: Request):
        with svc(request).db.session():
            user = current_user(request)
            return svc(request).db.all('SELECT id,title,created_at FROM conversations WHERE user_id=? ORDER BY created_at DESC', (user['id'],))

    @app.get('/api/conversations/{conversation_id}')
    def conversation(conversation_id: str, request: Request):
        with svc(request).db.session():
            user = current_user(request)
            service = svc(request)
            convo = service.conversation(conversation_id, user['id'])
            convo['messages'] = [{'question': m['question'], 'response': json.loads(m['response']), 'created_at': m['created_at']}
                                 for m in service.db.all('SELECT * FROM messages WHERE conversation_id=? ORDER BY id', (conversation_id,))]
            return convo

    @app.delete('/api/conversations/{conversation_id}')
    def delete_conversation(conversation_id: str, request: Request):
        user = current_user(request)
        service = svc(request)
        service.conversation(conversation_id, user['id'])
        service.db.execute('DELETE FROM conversations WHERE id=?', (conversation_id,))
        return {'ok': True}

    @app.get('/metrics')
    def metrics(request: Request):
        require_admin(request)
        return svc(request).metrics()

    @app.get('/api/query-logs/export')
    def export_logs(request: Request):
        require_admin(request)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['timestamp', 'question', 'latency_ms', 'retrieved_sources', 'outcome'])
        for row in svc(request).db.all('SELECT * FROM query_logs ORDER BY timestamp'):
            # Prevent spreadsheet applications treating user-controlled cells as formulas.
            safe_question = row['question'] or ''
            if safe_question.lstrip().startswith(('=', '+', '-', '@')):
                safe_question = "'" + safe_question
            writer.writerow([row['timestamp'], safe_question, row['latency_ms'], row['sources'], row['outcome']])
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="guidely-query-logs.csv"'})

    return app


app = create_app()

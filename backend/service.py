import hashlib
import json
import logging
import math
import time

from .db import database, now, uid
from .vectors import VectorCollection
from .storage import Storage
from .documents import chunks
from .errors import AppError
from .citations import citations_valid
from .provider import FakeProvider, GeminiProvider, OpenAIProvider

log = logging.getLogger('guidely')


class Service:
    def __init__(self, settings, provider=None):
        self.settings = settings
        self.db = database(settings)
        self.storage = Storage(settings)
        providers = {'fake': FakeProvider, 'openai': OpenAIProvider, 'gemini': GeminiProvider}
        if settings.provider not in providers:
            raise ValueError('GUIDELY_PROVIDER must be gemini, openai, or fake')
        if not settings.test_mode and (settings.provider != 'gemini' or settings.embedding_model != 'gemini-embedding-001'):
            raise ValueError('Deployment requires gemini-embedding-001 with 768 dimensions.')
        self.provider = provider or (FakeProvider() if settings.provider == 'fake' else providers[settings.provider](settings))
        self.model_key = settings.provider + ':' + settings.embedding_model + ':768:char-v2'
        self.collection = VectorCollection(self.db, self.model_key, settings.test_mode)
        self.lock = self.db.lock

    def start(self):
        pass

    def stop(self):
        pass

    def document(self, doc_id):
        doc = self.db.one('SELECT * FROM documents WHERE id=?', (doc_id,))
        if not doc:
            raise AppError(404, 'document_not_found', 'That document was not found.')
        if doc['state'] == 'deleting':
            raise AppError(404, 'document_not_found', 'That document was deleted.')
        doc['tags'] = json.loads(doc['tags'])
        return doc

    def embed(self, texts, kind):
        if not texts:
            return []
        keys = [hashlib.sha256((self.model_key + ':' + kind + ':' + text).encode()).hexdigest() for text in texts]
        with self.db.session():
            rows = self.db.all('SELECT key,vector FROM embeddings WHERE key IN (' + ','.join('?' for _ in set(keys)) + ')', tuple(set(keys)))
        cached = {r['key']:json.loads(r['vector']) for r in rows}
        vectors = [cached.get(key) for key in keys]
        missing = {}
        for index, (key, text) in enumerate(zip(keys, texts)):
            if key not in cached:
                missing.setdefault(key, {'text':text, 'indices':[]})['indices'].append(index)
        items = list(missing.items())
        for offset in range(0, len(items), 64):
            batch = items[offset:offset+64]
            generated = self.provider.embed([item['text'] for _, item in batch])
            if len(generated) != len(batch):
                raise AppError(502, 'invalid_embeddings', 'The AI service returned incomplete embeddings.')
            args = []
            for (key, item), vector in zip(batch, generated):
                args.extend((key, kind, json.dumps(vector)))
                for index in item['indices']:
                    vectors[index] = vector
            with self.db.session():
                self.db.execute('INSERT INTO embeddings VALUES ' + ','.join('(?,?,?)' for _ in batch) + ' ON CONFLICT(key) DO UPDATE SET vector=excluded.vector', args)
                self.db.count(kind + '_embeddings_generated', len(batch))
        hits = len(texts)-len(items)
        if hits:
            self.db.count(kind + '_cache_hits', hits)
        log.info('embedding kind=%s requested=%d generated=%d reused=%d', kind, len(texts), len(items), hits)
        return vectors

    def enqueue(self, doc_id):
        if self.settings.provider != 'fake' and not self.settings.api_key:
            raise AppError(503, 'missing_model_key', f'Set {self.settings.key_variable} on the backend before indexing documents.')
        with self.lock:
            doc = self.document(doc_id)
            if doc['state'] == 'deleting':
                raise AppError(409, 'document_deleting', 'Retry deleting this document.')
            # Acquiring the global DB lock proves earlier indexing transactions have ended.
            # Persist status on a separate connection so platform termination leaves a retryable job.
            with self.db.session(detached=True):
                self.db.execute("UPDATE jobs SET state='failed',error='Interrupted; retry indexing.' WHERE document_id=? AND state IN ('queued','indexing')", (doc_id,))
                job_id = uid()
                self.db.execute('INSERT INTO jobs (id,document_id,state,created_at) VALUES (?,?,?,?)', (job_id, doc_id, 'indexing', now()))
                self.db.execute("UPDATE documents SET state='indexing',error=NULL WHERE id=?", (doc_id,))
            self.index(job_id)
            return self.db.one('SELECT * FROM jobs WHERE id=?', (job_id,))

    def index(self, job_id):
        started = time.perf_counter()
        job = self.db.one('SELECT * FROM jobs WHERE id=?', (job_id,))
        if not job:
            return
        try:
            with self.lock:
                with self.db.savepoint():
                    doc = self.document(job['document_id'])
                    self.db.execute("UPDATE jobs SET state='indexing' WHERE id=?", (job_id,))
                    self.db.execute("UPDATE documents SET state='indexing',error=NULL WHERE id=?", (doc['id'],))
                    fingerprint = hashlib.sha256((self.model_key + ':char-v2:' + doc['text']).encode()).hexdigest()
                    parts = chunks(doc['text'], doc['filename'].lower().endswith('.pdf'))
                    if not parts:
                        raise AppError(422, 'empty_file', 'The document contains no searchable text.')
                    existing = self.collection.get(where={'document_id': doc['id']})
                    if doc['indexed_hash'] == fingerprint and len(existing['ids']) == len(parts):
                        self.db.count('document_cache_hits', len(parts))
                        self.db.count('unchanged_documents_skipped')
                    else:
                        vectors = self.embed([p['snippet'] for p in parts], 'document')
                        # PostgreSQL chunks and ready status commit atomically; deterministic IDs prevent duplicates.
                        self.collection.delete(where={'document_id': doc['id']})
                        self.collection.upsert(
                            ids=[doc['id'] + '-' + str(i) for i in range(len(parts))],
                            embeddings=vectors, documents=[p['snippet'] for p in parts],
                            metadatas=[{'document_id': doc['id'], 'section': p['section'], 'page': p['page']} for p in parts])
                    self.db.execute("UPDATE documents SET state='ready',indexed_hash=?,error=NULL WHERE id=?", (fingerprint, doc['id']))
                    elapsed = (time.perf_counter()-started)*1000
                    self.db.execute("UPDATE jobs SET state='complete',chunks=?,elapsed_ms=?,error=NULL WHERE id=?", (len(parts), elapsed, job_id))
                    log.info('index_complete job=%s chunks=%d elapsed_ms=%.2f', job_id, len(parts), elapsed)
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError) else 'indexing_failed'
            message = exc.message if isinstance(exc, AppError) else 'Indexing failed. Check the backend log and retry.'
            with self.lock:
                self.db.execute("UPDATE documents SET state='failed',error=? WHERE id=?", (message, job['document_id']))
                self.db.execute("UPDATE jobs SET state='failed',error=?,elapsed_ms=? WHERE id=?", (message, (time.perf_counter()-started)*1000, job_id))
            self.db.count('error:' + code)
            log.warning('index_failed job=%s code=%s', job_id, code)

    def search(self, question, tags=None, category='', top_k=5):
        question = question.strip()
        if not question:
            raise AppError(422, 'empty_query', 'Enter a question first.')
        with self.lock:
            docs = [{**d, 'tags':json.loads(d['tags'])} for d in self.db.all("SELECT id,filename,tags,category,state,revision,indexed_hash FROM documents WHERE state='ready'")]
            docs = [d for d in docs if (not category or d['category'] == category) and
                    (not tags or set(tags).issubset(d['tags']))]
            if not docs:
                raise AppError(404, 'no_results', 'No indexed documents match. Ask an administrator to index documents or change your filters.')
            by_id = {d['id']: d for d in docs}
            where = {'document_id': {'$in': list(by_id)}}
            available = self.collection.get(where=where)['ids']
            if not available:
                raise AppError(404, 'no_results', 'These documents need re-indexing for the configured embedding model.')
        vector = self.embed([question], 'question')[0]
        with self.lock:
            result = self.collection.query(query_embeddings=[vector], n_results=min(top_k, len(available)), where=where)
            passages = []
            for chunk_id, metadata, text, distance in zip(result['ids'][0], result['metadatas'][0], result['documents'][0], result['distances'][0]):
                # Recheck state after external embedding calls; edited content must disappear immediately.
                doc = self.document(metadata['document_id'])
                if (doc['state'] != 'ready' or (category and doc['category'] != category)
                        or (tags and not set(tags).issubset(doc['tags']))):
                    continue
                score = max(-1, min(1, 1-distance))
                if score < self.settings.min_similarity:
                    continue
                passages.append({'source_id': str(len(passages)+1), 'document_id': doc['id'],
                                 'filename': doc['filename'], 'chunk_id': chunk_id, 'snippet': text,
                                 'revision': doc['revision'], 'indexed_hash': doc['indexed_hash'],
                                 'page': metadata.get('page') or None, 'section': metadata.get('section', ''), 'score': score})
        if not passages:
            raise AppError(404, 'no_results', 'No relevant passage was found. Try a more specific question or different filters.')
        return passages

    def conversation(self, conversation_id, user_id):
        conversation = self.db.one('SELECT * FROM conversations WHERE id=? AND user_id=?', (conversation_id, user_id))
        if not conversation:
            raise AppError(404, 'conversation_not_found', 'That conversation was not found.')
        return conversation

    def ask(self, user, question, conversation_id=None, tags=None, category=''):
        started = time.perf_counter()
        sources = []
        outcome = 'success'
        try:
            question = question.strip()
            if not question:
                raise AppError(422, 'empty_query', 'Enter a question first.')
            history = []
            if conversation_id:
                self.conversation(conversation_id, user['id'])
                history = [{'question': m['question'], 'answer': json.loads(m['response'])['answer'][:2000]}
                           for m in reversed(self.db.all('SELECT question,response FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 4', (conversation_id,)))]
            rewritten = self.provider.rewrite(question, history)
            sources = self.search(rewritten, tags, category)
            generated = self.provider.answer(rewritten, sources)
            if not isinstance(generated, dict) or not isinstance(generated.get('answer'), str) or not isinstance(generated.get('source_ids'), list):
                raise AppError(502, 'invalid_model_output', 'The AI service returned an invalid answer.')
            if generated.get('supported') is not True:
                raise AppError(404, 'insufficient_evidence', 'The documents do not contain enough evidence to answer this question.')
            ids = generated['source_ids']
            if not citations_valid(generated, sources):
                raise AppError(502, 'invalid_citations', 'The AI returned unverified references. Please try again.')
            # Reject responses whose sources changed while the model was generating.
            with self.lock:
                for source in sources:
                    current = self.document(source['document_id'])
                    if (current['state'] != 'ready' or current['revision'] != source['revision']
                            or current['indexed_hash'] != source['indexed_hash']):
                        raise AppError(409, 'documents_changed', 'A source document changed. Please ask again after re-indexing.')
                if not conversation_id:
                    conversation_id = uid()
                    self.db.execute('INSERT INTO conversations VALUES (?,?,?,?)', (conversation_id, user['id'], question[:100], now()))
                result = {'answer': generated['answer'], 'conversation_id': conversation_id,
                          'references': [s for s in sources if s['source_id'] in ids],
                          'passages': sources, 'elapsed_ms': round((time.perf_counter()-started)*1000, 2)}
                self.db.execute('INSERT INTO messages (conversation_id,question,response,created_at) VALUES (?,?,?,?)',
                                (conversation_id, question, json.dumps(result), now()))
            return result
        except AppError as exc:
            outcome = exc.code
            raise
        except Exception:
            outcome = 'internal_error'
            raise
        finally:
            elapsed = (time.perf_counter()-started)*1000
            self.db.execute('INSERT INTO query_logs VALUES (?,?,?,?,?,?,?)',
                            (uid(), user['id'], question, now(), elapsed, json.dumps(sources), outcome))
            log.info('query outcome=%s latency_ms=%.2f source_count=%d', outcome, elapsed, len(sources))

    def metrics(self):
        timings = sorted(r['latency_ms'] for r in self.db.all('SELECT latency_ms FROM query_logs'))
        counters = {r['name']: r['value'] for r in self.db.all('SELECT * FROM counters')}
        return {'documents': self.db.one('SELECT count(*) AS n FROM documents')['n'],
                'chunks': self.collection.count(), 'queries_served': len(timings),
                'latency_ms': {'median': (timings[(len(timings)-1)//2]+timings[len(timings)//2])/2 if timings else None,
                               'p95': timings[math.ceil(len(timings)*.95)-1] if timings else None},
                'counters': counters,
                'errors': {k[6:]: v for k, v in counters.items() if k.startswith('error:')}}

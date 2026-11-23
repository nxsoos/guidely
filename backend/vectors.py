"""pgvector cosine retrieval; SQLite implementation is strictly an offline test adapter."""
import json
import math
from .errors import AppError


class VectorCollection:
    def __init__(self, db, model, test_mode=False):
        self.db, self.name, self.test_mode = db, model, test_mode

    def count(self):
        return self.db.one('SELECT count(*) n FROM vector_chunks WHERE model=?', (self.name,))['n']

    def get(self, where=None):
        sql, args = 'SELECT id FROM vector_chunks WHERE model=?', [self.name]
        if where:
            value = where['document_id']
            ids = value['$in'] if isinstance(value, dict) else [value]
            sql += ' AND document_id IN (' + ','.join('?' for _ in ids) + ')'
            args += ids
        return {'ids': [r['id'] for r in self.db.all(sql, args)]}

    def delete(self, where):
        self.db.execute('DELETE FROM vector_chunks WHERE document_id=? AND model=?', (where['document_id'], self.name))

    def upsert(self, ids, embeddings, documents, metadatas):
        for chunk_id, vector, text, meta in zip(ids, embeddings, documents, metadatas):
            if not self.test_mode and len(vector) != 768:
                raise AppError(502, 'invalid_embeddings', 'Expected 768-dimensional Gemini embeddings.')
            column = 'vector' if self.test_mode else 'embedding'
            cast = '?' if self.test_mode else '?::extensions.vector'
            self.db.execute(f'INSERT INTO vector_chunks (id,document_id,model,snippet,section,page,{column}) VALUES (?,?,?,?,?,?,{cast}) ON CONFLICT(id) DO UPDATE SET model=excluded.model,snippet=excluded.snippet,section=excluded.section,page=excluded.page,{column}=excluded.{column}',
                (chunk_id, meta['document_id'], self.name, text, meta['section'], meta['page'], json.dumps(vector)))

    def query(self, query_embeddings, n_results, where):
        ids = where['document_id']['$in']
        vector = query_embeddings[0]
        sql = 'SELECT * FROM vector_chunks WHERE model=? AND document_id IN (' + ','.join('?' for _ in ids) + ')'
        args = [self.name] + ids
        if self.test_mode:
            rows = self.db.all(sql, args)
            def distance(row):
                other = json.loads(row['vector'])
                norm = math.sqrt(sum(v*v for v in vector)*sum(v*v for v in other))
                return 1-sum(a*b for a,b in zip(vector,other))/norm if norm else 1
            rows = sorted([dict(r, distance=distance(r)) for r in rows], key=lambda r:r['distance'])[:n_results]
        else:
            sql = sql.replace('SELECT *', 'SELECT id,document_id,snippet,section,page,embedding OPERATOR(extensions.<=>) ?::extensions.vector AS distance')
            rows = self.db.all(sql + ' ORDER BY distance LIMIT ?', [json.dumps(vector)] + args + [n_results])
        return {'ids': [[r['id'] for r in rows]], 'documents': [[r['snippet'] for r in rows]],
                'metadatas': [[{'document_id':r['document_id'],'section':r['section'],'page':r['page']} for r in rows]],
                'distances': [[r['distance'] for r in rows]]}

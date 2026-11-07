"""FTS5 and optional CPU embeddings; indexes are derived from authoritative rows."""
from __future__ import annotations

import hashlib
import importlib.metadata
import math
import re
import struct

from .db import now, transaction

DEFAULT_MODEL = 'minishlab/potion-base-8M'
PIPELINE = 'token-chunks-192-overlap-24-l2-v1'


class Embedder:
    def __init__(self, model=DEFAULT_MODEL, cache_dir=None):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ValueError('CPU embeddings need `pip install spoq[search]`') from exc
        self.name = model
        self.model = TextEmbedding(model_name=model, cache_dir=str(cache_dir) if cache_dir else None, threads=2)
        # Pin artifacts by their file digest, not just a mutable model name.
        path = getattr(self.model.model, '_model_dir', None)
        files = sorted(path.rglob('*')) if path is not None else []
        digest = hashlib.sha256()
        for file in files:
            if file.is_file() and file.suffix in {'.onnx', '.safetensors', '.json'}:
                with file.open('rb') as source:
                    for block in iter(lambda: source.read(1024*1024), b''):
                        digest.update(block)
        self.revision = f'fastembed-{importlib.metadata.version("fastembed")}:{digest.hexdigest()}'

    def chunks(self, text):
        tokenizer = getattr(self.model.model, 'tokenizer', None) or getattr(self.model.model, '_tokenizer', None)
        if tokenizer is None:
            # Static FastEmbed models expose the underlying Model2Vec model.
            inner = getattr(self.model.model, 'model', None)
            tokenizer = getattr(inner, 'tokenizer', None)
        if tokenizer is None:
            raise ValueError('Embedding backend must expose a tokenizer for lossless chunking')
        tokens = tokenizer.encode(text, add_special_tokens=False).ids
        return [tokenizer.decode(tokens[i:i+192]) for i in range(0, len(tokens), 168)] or ['']

    def embed(self, texts, query=False):
        return list(self.model.query_embed(texts) if query else self.model.embed(texts))


def _vector(values):
    values = [float(v) for v in values]
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError('Embedding contains non-finite values')
    norm = math.sqrt(sum(v*v for v in values))
    if norm <= 0:
        raise ValueError('Embedding has zero length')
    return struct.pack(f'{len(values)}f', *(v/norm for v in values))


def _load_vec(db):
    try:
        import sqlite_vec
    except ImportError as exc:
        raise ValueError('Vector search needs `pip install spoq[search]`') from exc
    db.enable_load_extension(True)
    try:
        sqlite_vec.load(db)
    finally:
        db.enable_load_extension(False)


def _space(embedder):
    return hashlib.sha256((embedder.name + embedder.revision + PIPELINE).encode()).hexdigest()[:24]


def reindex(store, embedder):
    space = _space(embedder)
    with transaction(store.path) as db:
        documents = [dict(r) for r in db.execute('SELECT * FROM search_documents ORDER BY id')]
    chunks = [(d, text) for d in documents for text in embedder.chunks(d['title']+'\n'+d['body'])]
    if not chunks:
        return {'indexed_chunks': 0}
    # Inference deliberately runs outside the writer transaction.
    vectors = [_vector(v) for v in embedder.embed([text for _, text in chunks])]
    if len(vectors) != len(chunks):
        raise ValueError('Embedding backend returned an incorrect result count')
    dimensions = len(vectors[0])//4
    if any(len(v) != len(vectors[0]) for v in vectors):
        raise ValueError('Embedding dimension mismatch')
    with transaction(store.path, write=True) as db:
        _load_vec(db)
        db.execute(f'CREATE VIRTUAL TABLE IF NOT EXISTS vec_{space} USING vec0(embedding float[{dimensions}] distance_metric=cosine)')
        db.execute(f'DELETE FROM vec_{space}')
        db.execute('INSERT OR REPLACE INTO embedding_spaces VALUES(?,?,?,?,?)',
                   (space, embedder.name, dimensions, embedder.revision+':'+PIPELINE, now()))
        db.execute('DELETE FROM embedding_chunks WHERE space_id=?', (space,))
        inserted = 0
        for i, ((document, text), vector) in enumerate(zip(chunks, vectors), 1):
            current = db.execute('SELECT content_hash FROM search_documents WHERE id=?', (document['id'],)).fetchone()
            if current is None or current[0] != document['content_hash']:
                continue
            db.execute(f'INSERT INTO vec_{space}(rowid,embedding) VALUES(?,?)', (i, vector))
            db.execute('INSERT INTO embedding_chunks VALUES(?,?,?,?,?)', (space, i, document['id'], document['content_hash'], text))
            inserted += 1
    return {'space_id': space, 'indexed_chunks': inserted, 'dimensions': dimensions}


def search(store, query, *, limit=10, kind='', embedder=None):
    if not query.strip():
        return []
    limit = min(max(limit, 1), 100)
    # Quote terms so user punctuation never becomes executable FTS syntax.
    terms = re.findall(r'\w+', query, re.UNICODE)
    lexical = ' OR '.join('"' + term + '"' for term in terms)
    with transaction(store.path) as db:
        rows = [dict(r) for r in db.execute('''SELECT d.* FROM documents_fts f JOIN search_documents d ON d.id=f.rowid
            WHERE documents_fts MATCH ? AND (?='' OR d.kind=?) ORDER BY rank LIMIT ?''',
            (lexical, kind, kind, limit*4))] if lexical else []
        scores = {r['id']: 1/(60+i) for i, r in enumerate(rows, 1)}
        by_id = {r['id']: r for r in rows}
        if embedder:
            space = _space(embedder)
            if not db.execute('SELECT 1 FROM embedding_spaces WHERE id=?', (space,)).fetchone():
                raise ValueError('Embedding index missing or model revision changed; run spoq reindex')
            _load_vec(db)
            vector = _vector(embedder.embed([query], query=True)[0])
            # Filter before final top-k, including stale embeddings. Exact scan avoids filtered-KNN underfill.
            semantic = db.execute(f'''SELECT d.*,min(vec_distance_cosine(v.embedding,?)) AS distance
                FROM vec_{space} v JOIN embedding_chunks c ON c.row_id=v.rowid AND c.space_id=?
                JOIN search_documents d ON d.id=c.document_id AND d.content_hash=c.content_hash
                WHERE (?='' OR d.kind=?) GROUP BY d.id ORDER BY distance LIMIT ?''',
                (vector, space, kind, kind, limit*4)).fetchall()
            for i, row in enumerate(semantic, 1):
                record = dict(row)
                by_id[record['id']] = record
                scores[record['id']] = scores.get(record['id'], 0) + 1/(60+i)
        ordered = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
        return [{**by_id[key], 'score': scores[key]} for key in ordered]

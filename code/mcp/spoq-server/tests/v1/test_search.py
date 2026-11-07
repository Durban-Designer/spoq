import pytest
from spoq_server.v1.search import search,reindex


class TinyEmbedding:
    name='test-embedding'
    revision='fixed-test-revision'
    def chunks(self,text): return [text]
    def embed(self,texts,query=False):
        return [[1.,.01] if 'authentication' in text.lower() else [.01,1.] for text in texts]


def test_fts_handles_punctuation_and_kind_filters(store):
    store.journal('Authentication uses access tokens')
    hits=search(store,'authentication: (tokens) "',kind='journal')
    assert len(hits)==1 and hits[0]['kind']=='journal'
    assert search(store,'NOT: ("')==[]


def test_hybrid_search_and_stale_embedding_invalidation(store):
    pytest.importorskip('sqlite_vec')
    entry=store.journal('Authentication uses access tokens')
    store.journal('Potatoes grow in soil')
    model=TinyEmbedding()
    result=reindex(store,model)
    assert result['dimensions']==2
    assert search(store,'authentication',kind='journal',embedder=model)[0]['source_id']==entry['id']
    store.edit('feature',{'description':'Authentication changed'})
    # Edited content must not borrow the stale vector from its prior revision.
    assert all(r['source_id']!='feature' for r in search(store,'potato',kind='feature',embedder=model))


def test_model_revision_requires_reindex(store):
    pytest.importorskip('sqlite_vec')
    model=TinyEmbedding()
    reindex(store,model)
    model.revision='new-model'
    with pytest.raises(ValueError,match='revision'): search(store,'authentication',embedder=model)


def test_nonfinite_vector_does_not_replace_existing_index(store):
    pytest.importorskip('sqlite_vec')
    model=TinyEmbedding()
    reindex(store,model)
    model.embed=lambda texts,query=False:[[float('nan'),0] for _ in texts]
    with pytest.raises(ValueError,match='non-finite'): reindex(store,model)
    assert search(store,'feature',embedder=TinyEmbedding())

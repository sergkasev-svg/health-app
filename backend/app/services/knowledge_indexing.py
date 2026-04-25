"""
KnowledgeIndexing facade:
load -> chunk -> create embeddings (no-op) -> store.
"""
from typing import Any

from app.services.medical_knowledge_indexer import (
    chunk_documents,
    create_embeddings,
    load_documents,
    store_chunks,
)


def rebuild_index() -> dict[str, Any]:
    docs = load_documents()
    chunks = chunk_documents()
    embedded = create_embeddings(chunks)
    ok = store_chunks(embedded)
    return {
        "documents_count": len(docs),
        "chunks_count": len(chunks),
        "stored": bool(ok),
    }


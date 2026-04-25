"""
Medical knowledge indexer: load documents, chunk, (optional embeddings), store chunks.
Isolated from existing app logic. Reads from knowledge_cache only.
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_CACHE = _BACKEND_DIR.parent / "knowledge_cache"
CHUNKS_FILE = KNOWLEDGE_CACHE / "chunks.json"
MANIFEST_FILE = KNOWLEDGE_CACHE / "knowledge_manifest.json"


def get_cache_dir() -> Path:
    return KNOWLEDGE_CACHE


def load_documents() -> list[dict]:
    """Load manifest and chunk paths. Does not load full chunk content here."""
    if not MANIFEST_FILE.exists():
        return []
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return manifest.get("sources", [])
    except Exception as e:
        logger.warning("medical_knowledge_indexer: load_documents manifest failed: %s", e)
        return []


def chunk_documents() -> list[dict]:
    """Load chunks from knowledge_cache/chunks.json (produced by ingestion)."""
    if not CHUNKS_FILE.exists():
        return []
    try:
        with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("medical_knowledge_indexer: chunk_documents failed: %s", e)
        return []


def create_embeddings(chunks: list[dict]) -> list[dict]:
    """Optional: add embedding vector to each chunk. No-op by default (keyword search only)."""
    return chunks


def store_chunks(chunks: list[dict]) -> bool:
    """Chunks are already stored by run_ingestion. This validates and optionally rewrites index."""
    if not chunks:
        return True
    KNOWLEDGE_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("medical_knowledge_indexer: store_chunks failed: %s", e)
        return False


def load_chunks() -> list[dict]:
    """Load all chunks for search. Same as chunk_documents, explicit name for API."""
    return chunk_documents()

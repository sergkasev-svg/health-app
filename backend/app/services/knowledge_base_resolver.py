"""
KnowledgeBaseResolver: orchestrates offline + indexed knowledge retrieval.
Isolated facade for voice concierge and API routes.
"""
from typing import Any

from app.services.medical_knowledge_resolver import resolve_sources_for_query
from app.services.medical_knowledge_search import search as indexed_search
from app.services.microbiome_knowledge_lookup import get_microbiome_muscle_context


def resolve_medical_context(user_message: str, language: str = "ru") -> dict[str, Any]:
    """
    Returns combined context:
    - intent
    - clinical/local snippets
    - indexed knowledge summary/causes/tests/red_flags/sources
    - microbiome_context (если запрос про слабость/саркопению/микробиом/бутират/мышечную силу)
    """
    local_ctx = resolve_sources_for_query(user_message or "")
    indexed = indexed_search(query=user_message or "", max_results=10, language=language or "")
    microbiome_ctx = get_microbiome_muscle_context(user_message or "")

    return {
        "intent": local_ctx.get("intent") or "general",
        "clinical": local_ctx.get("clinical") or "",
        "clinical_simple": local_ctx.get("clinical_simple") or "",
        "indexed": indexed,
        "microbiome_context": microbiome_ctx,
    }


import os
import logging

logger = logging.getLogger(__name__)


class RAGRetriever:
    """Knowledge-base retrieval for /api/retrieve and the decision engine.

    Uses the fast TF-IDF index (services/kb_search.py) over the ChromaDB
    documents instead of the neural embedding model, which can take minutes
    to load on the free server and hang the request.
    """

    def search(self, query: str, k: int = 5, target_crop: str = "") -> str:
        from krishi_core.services.kb_search import search as kb_search
        try:
            crop = target_crop.strip().capitalize() if target_crop else None
            hits = kb_search(query, crop=crop, limit=k, with_meta=True)
        except Exception as e:
            logger.error("Knowledge search failed: %s", e)
            return ""
        if not hits:
            return ""
        parts = []
        for i, (doc, collection, meta) in enumerate(hits):
            source = (meta or {}).get("source") or collection or "Unknown Source"
            parts.append(f"[Source {i+1}: {os.path.basename(str(source))}]\n{doc}\n")
        return "\n".join(parts)


rag_retriever = RAGRetriever()

"""Fast knowledge-base search for AI Mitra.

The knowledge base is small (~200 documents in ChromaDB). Ranking them with
the neural embedding model costs ~0.05 s on a laptop but 7-18 s on Render's
free 0.1-CPU instance (plus re-downloading the model after each restart).
A TF-IDF index over the same documents answers in milliseconds anywhere, and
for short agronomy notes keyword relevance works well. The crop-aware rules
(timeline documents for a crop named in the question) are kept.
"""
import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_index = None  # dict(docs=[(collection, text, meta)], vectorizer, matrix)
stats = {"builds": 0, "build_seconds": None, "documents": 0, "error": None}


def _build_index():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from krishi_core import ml_loader

    client = ml_loader.state.get("chroma_client")
    if not client:
        return None
    docs = []
    for c in client.list_collections():
        name = c.name if hasattr(c, "name") else str(c)
        try:
            data = client.get_collection(name).get(include=["documents", "metadatas"])
        except Exception:
            logger.warning("kb_search: could not read collection %s", name, exc_info=True)
            continue
        for text, meta in zip(data.get("documents") or [], data.get("metadatas") or []):
            if text:
                docs.append((name, text, meta or {}))
    if not docs:
        return None
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    matrix = vectorizer.fit_transform([d[1] for d in docs])
    logger.info("kb_search: indexed %d documents", len(docs))
    return {"docs": docs, "vectorizer": vectorizer, "matrix": matrix}


def _get_index():
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                import time
                t0 = time.monotonic()
                stats["builds"] += 1
                try:
                    _index = _build_index() or {}
                except Exception as exc:  # keep chat working without context
                    logger.warning("kb_search: index build failed", exc_info=True)
                    stats["error"] = type(exc).__name__
                    _index = {}
                stats["build_seconds"] = round(time.monotonic() - t0, 2)
                stats["documents"] = len(_index.get("docs", [])) if _index else 0
    return _index or None


def search(query, crop=None, stage_specific=False, limit=6, per_collection=3, min_score=0.05):
    """Return up to `limit` relevant documents (strings) for the question."""
    index = _get_index()
    if not index:
        return []
    docs, matrix = index["docs"], index["matrix"]
    scores = (matrix @ index["vectorizer"].transform([query]).T).toarray().ravel()

    # Best matches from the other collections (disease treatments, app help).
    others, by_collection = [], {}
    for i in scores.argsort()[::-1]:
        if scores[i] < min_score:
            break
        col = docs[i][0]
        if crop and col == "timeline_kb":
            continue  # handled by the crop rule below
        if by_collection.get(col, 0) < per_collection:
            by_collection[col] = by_collection.get(col, 0) + 1
            others.append(i)
    strong = [i for i in others if scores[i] >= 0.15]
    weak = [i for i in others if scores[i] < 0.15]

    crop_ids = []
    if crop:
        crop_ids = [i for i, (col, _t, meta) in enumerate(docs)
                    if col == "timeline_kb" and str(meta.get("crop", "")).lower() == crop.lower()]
        if stage_specific:
            crop_ids.sort(key=lambda i: -scores[i])
        else:
            # General crop question: whole season in order (sowing -> harvest).
            crop_ids.sort(key=lambda i: docs[i][2].get("stage_day_start", 0))

    # Strong topic matches (e.g. a disease treatment) first, then the crop's
    # season documents, then weaker matches.
    picked = strong + crop_ids + weak

    seen, out = set(), []
    for i in picked:
        text = docs[i][1]
        if text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= limit:
            break
    return out


# NOTE: no background warm-up thread. Building the index in a thread at
# startup imported numpy/sklearn while the first request imported pandas,
# and the concurrent half-finished numpy import broke every request
# ("partially initialized module 'numpy'"). The index is built on first use.

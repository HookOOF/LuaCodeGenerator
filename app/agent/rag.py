from __future__ import annotations

import json
import logging
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

_embedder: SentenceTransformer | None = None
_qdrant: QdrantClient | None = None

KNOWLEDGE_PATH = Path(__file__).parent.parent.parent / "knowledge" / "lua_domain.json"


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(settings.embedding_model, device="cpu")
    return _embedder


def _clear_stale_lock(storage_path: str) -> None:
    lock_file = Path(storage_path) / ".lock"
    if not lock_file.exists():
        return
    try:
        import subprocess
        result = subprocess.run(
            ["fuser", str(lock_file)],
            capture_output=True, timeout=3,
        )
        if result.returncode != 0:
            lock_file.unlink(missing_ok=True)
            logger.info("Removed stale Qdrant lock: %s", lock_file)
    except Exception:
        pass


def get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        if settings.qdrant_url:
            _qdrant = QdrantClient(url=settings.qdrant_url)
        else:
            _clear_stale_lock(settings.qdrant_local_path)
            _qdrant = QdrantClient(path=settings.qdrant_local_path)
    return _qdrant


def index_knowledge() -> None:
    embedder = get_embedder()
    client = get_qdrant()
    collection = settings.qdrant_collection

    with open(KNOWLEDGE_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    texts = [e["text"] for e in entries]
    vectors = embedder.encode(texts, show_progress_bar=True).tolist()
    dim = len(vectors[0])

    existing = [c.name for c in client.get_collections().collections]
    if collection in existing:
        client.delete_collection(collection)

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    points = [
        PointStruct(id=i, vector=vec, payload={"text": entry["text"], "category": entry.get("category", "")})
        for i, (vec, entry) in enumerate(zip(vectors, entries))
    ]
    client.upsert(collection_name=collection, points=points)
    logger.info("Indexed %d knowledge entries into Qdrant", len(points))


def _normalize_query(query: str) -> str:
    """Extract the core task description, stripping JSON context for better embedding match."""
    import re
    cleaned = re.sub(r'\{["\s]*wf["\s]*:.*', '', query, flags=re.DOTALL).strip()
    if len(cleaned) < 10:
        return query
    return cleaned


def retrieve(query: str, top_k: int = 5, min_score: float = 0.3) -> list[str]:
    try:
        embedder = get_embedder()
        client = get_qdrant()

        normalized = _normalize_query(query)
        query_vec = embedder.encode(normalized).tolist()

        results = client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_vec,
            limit=top_k + 2,
        )

        hits = [
            hit for hit in results.points
            if hit.payload and hit.score >= min_score
        ]

        # Boost "example" category entries — they contain working code patterns
        def _sort_key(hit):
            score = hit.score
            if hit.payload.get("category") == "example":
                score += 0.05
            return -score

        hits.sort(key=_sort_key)

        return [hit.payload["text"] for hit in hits[:top_k]]
    except Exception:
        logger.exception("RAG retrieval failed, continuing without context")
        return []

"""Qdrant backend: dense (Ollama) + sparse BM25, RRF fusion.

The original engine, kept as the high-quality option. Needs a Qdrant endpoint
and an Ollama-compatible embedding endpoint (see ``config``).
"""
from __future__ import annotations

import requests
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

from second_brain import config
from second_brain.backends.base import Hit

NAME = "qdrant"
QUERY_PREFIX = (
    "Instruct: Given a user query, retrieve relevant notes from a personal knowledge base\nQuery: "
)


class QdrantBackend:
    name = NAME

    def __init__(self) -> None:
        self._client: QdrantClient | None = None
        self._sparse = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(url=config.QDRANT_URL, timeout=60)
        return self._client

    def _embed(self, q: str) -> list[float]:
        r = requests.post(config.OLLAMA, json={"model": config.EMBED_MODEL,
                          "input": [QUERY_PREFIX + q], "keep_alive": "24h"}, timeout=300)
        r.raise_for_status()
        return r.json()["embeddings"][0]

    def _sparse_one(self, text: str) -> models.SparseVector:
        if self._sparse is None:
            self._sparse = SparseTextEmbedding(model_name="Qdrant/bm25")
        v = next(iter(self._sparse.embed([text])))
        return models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())

    def _filter(self, tag: str | None, folder: str | None,
                exclude: str | None = None) -> models.Filter | None:
        must, must_not = [], []
        if tag:
            must.append(models.FieldCondition(key="tags", match=models.MatchValue(value=tag)))
        if folder:
            must.append(models.FieldCondition(key="file_path", match=models.MatchText(text=folder)))
        if exclude:
            must_not.append(models.FieldCondition(key="file_path", match=models.MatchValue(value=exclude)))
        return models.Filter(must=must, must_not=must_not) if (must or must_not) else None

    def search(self, query: str, k: int, *, tag: str | None = None,
               folder: str | None = None, exclude: str | None = None) -> list[Hit]:
        flt = self._filter(tag, folder, exclude)
        points = self.client.query_points(
            config.COLLECTION,
            prefetch=[
                models.Prefetch(query=self._embed(query), using="dense", limit=20, filter=flt),
                models.Prefetch(query=self._sparse_one(query), using="bm25", limit=20, filter=flt),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        ).points
        return [Hit(payload=p.payload, score=round(p.score, 4)) for p in points]

    def count(self) -> int:
        return self.client.count(config.COLLECTION, exact=True).count

    def health(self) -> dict:
        try:
            info = self.client.get_collection(config.COLLECTION)
            return {"backend": NAME, "chunks": self.client.count(config.COLLECTION, exact=True).count,
                    "infra": config.QDRANT_URL, "status": str(info.status)}
        except Exception as e:  # noqa: BLE001
            return {"backend": NAME, "infra": config.QDRANT_URL, "error": str(e)}

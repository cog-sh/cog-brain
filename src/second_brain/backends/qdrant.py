"""Qdrant backend: dense (Ollama) + sparse BM25, RRF fusion, incremental sync.

The high-quality option. Needs a Qdrant endpoint and an Ollama-compatible
embedding endpoint (see ``config``). Owns its own manifest (``config.DB``).
"""
from __future__ import annotations

import hashlib
import sys
import time
import uuid

import requests
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

from second_brain import chunking, config
from second_brain.backends.base import Hit
from second_brain.manifest import Manifest, iso, staleness

NAME = "qdrant"
DIMS = 1024
QUERY_PREFIX = (
    "Instruct: Given a user query, retrieve relevant notes from a personal knowledge base\nQuery: "
)


class QdrantBackend:
    name = NAME

    def __init__(self) -> None:
        self._client: QdrantClient | None = None
        self._sparse_model = None
        self._manifest = Manifest(config.DB)

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(url=config.QDRANT_URL, timeout=60)
        return self._client

    # ------------------------------------------------------------------ embed

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 16):
            batch = texts[i : i + 16]
            for attempt in range(3):
                try:
                    r = requests.post(config.OLLAMA, json={"model": config.EMBED_MODEL,
                                      "input": batch, "keep_alive": "24h"}, timeout=(5, 120))
                    r.raise_for_status()
                    out.extend(r.json()["embeddings"])
                    break
                except (requests.RequestException, KeyError, ValueError) as e:
                    if attempt == 2:
                        raise
                    print(f"  embed retry {attempt + 1} (batch {i // 16}): {e}", file=sys.stderr)
                    time.sleep(2 * (attempt + 1))
        return out

    def _embed_query(self, q: str) -> list[float]:
        r = requests.post(config.OLLAMA, json={"model": config.EMBED_MODEL,
                          "input": [QUERY_PREFIX + q], "keep_alive": "24h"}, timeout=300)
        r.raise_for_status()
        return r.json()["embeddings"][0]

    def _sparse(self, texts: list[str]) -> list[models.SparseVector]:
        if self._sparse_model is None:
            self._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        return [models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())
                for v in self._sparse_model.embed(texts)]

    def _sparse_one(self, text: str) -> models.SparseVector:
        return self._sparse([text])[0]

    # ----------------------------------------------------------------- index

    def ensure(self) -> None:
        if self.client.collection_exists(config.COLLECTION):
            return
        self.client.create_collection(
            config.COLLECTION,
            vectors_config={"dense": models.VectorParams(size=DIMS, distance=models.Distance.COSINE)},
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100))
        for field, schema in [
            ("file_path", models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD)),
            ("note_title", models.TextIndexParams(type=models.TextIndexType.TEXT,
             tokenizer=models.TokenizerType.MULTILINGUAL, lowercase=True)),
            ("tags", models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD)),
            ("mtime", models.DatetimeIndexParams(type=models.DatetimeIndexType.DATETIME)),
        ]:
            self.client.create_payload_index(config.COLLECTION, field, schema)

    @staticmethod
    def _point_id(rel: str, idx: int) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel}#{idx}"))

    def _delete_file(self, rel: str) -> None:
        self.client.delete(config.COLLECTION, points_selector=models.FilterSelector(
            filter=models.Filter(must=[models.FieldCondition(
                key="file_path", match=models.MatchValue(value=rel))])))

    def _index_file(self, p, rel: str, full: bool) -> bool:
        chunks = chunking.chunks_for(p, rel)
        texts = [c["embed_text"] for c in chunks]
        h = hashlib.sha256("\n\x00\n".join(texts).encode()).hexdigest()
        row = self._manifest.get(rel)
        if row and row == (h, chunking.CHUNKER_VERSION, config.EMBED_MODEL) and not full:
            return False
        self._delete_file(rel)
        dense, sp = self._embed_texts(texts), self._sparse(texts)
        points = [
            models.PointStruct(
                id=self._point_id(rel, c["idx"]),
                vector={"dense": dense[i], "bm25": sp[i]},
                payload={"file_path": rel, "note_title": c["note_title"],
                         "heading_path": c["heading_path"], "text": c["text"],
                         "tags": c["tags"], "aliases": c["aliases"], "links": c["links"],
                         "type": c["type"], "status": c["status"], "mtime": c["mtime"],
                         "content_hash": h})
            for i, c in enumerate(chunks)
        ]
        self.client.upsert(config.COLLECTION, points=points)
        self._manifest.set(rel, h, chunking.CHUNKER_VERSION, config.EMBED_MODEL)
        return True

    def sync(self, notes=None, full: bool = False) -> dict:
        notes = list(notes if notes is not None else chunking.iter_notes())
        self.ensure()
        changed = deleted = 0
        t0 = time.time()
        current = set()
        for p, rel in notes:
            current.add(rel)
            try:
                if self._index_file(p, rel, full):
                    changed += 1
            except Exception as e:  # noqa: BLE001
                print(f"  !! {rel}: {e}", file=sys.stderr)
        for rel in self._manifest.rels():
            if rel not in current:
                self._delete_file(rel)
                self._manifest.delete(rel)
                deleted += 1
        self._manifest.set_last_run(time.time())
        return {"changed": changed, "deleted": deleted, "total": self.count(),
                "elapsed": round(time.time() - t0, 1)}

    # ---------------------------------------------------------------- search

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
                models.Prefetch(query=self._embed_query(query), using="dense", limit=20, filter=flt),
                models.Prefetch(query=self._sparse_one(query), using="bm25", limit=20, filter=flt),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        ).points
        return [Hit(payload=p.payload, score=round(p.score, 4)) for p in points]

    # ----------------------------------------------------------------- state

    def count(self) -> int:
        return self.client.count(config.COLLECTION, exact=True).count

    def status(self) -> dict:
        indexed = self._manifest.rels()
        last = self._manifest.last_run()
        disk = [rel for _, rel in chunking.iter_notes()]
        stale = staleness(disk, last)
        return {"backend": NAME, "notes_on_disk": len(disk), "notes_indexed": len(indexed),
                "last_run": iso(last), "stale_count": len(stale), "stale": stale[:50]}

    def reset(self) -> None:
        if self.client.collection_exists(config.COLLECTION):
            self.client.delete_collection(config.COLLECTION)
        self._manifest.clear()

    def health(self) -> dict:
        try:
            return {"backend": NAME, "infra": config.QDRANT_URL,
                    "chunks": self.count(), **{k: v for k, v in self.status().items()
                                               if k in ("notes_on_disk", "notes_indexed", "last_run")}}
        except Exception as e:  # noqa: BLE001
            return {"backend": NAME, "infra": config.QDRANT_URL, "error": str(e)}

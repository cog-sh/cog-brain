"""Incremental Obsidian vault indexer -> Qdrant (dense qwen3-embedding + sparse bm25, RRF-ready).

Usage:
  second-brain-index                 # incremental diff
  second-brain-index --full          # full reindex
  second-brain-index --watch         # watchdog mode (2s debounce)
  python -m second_brain.indexer     # equivalent entry point
"""
import argparse, hashlib, json, re, sqlite3, sys, time
from pathlib import Path

from qdrant_client import QdrantClient, models
import requests
from fastembed import SparseTextEmbedding

from second_brain import chunking, config
from second_brain.chunking import (
    CHUNKER_VERSION, contextualize, extract_links, iter_notes, parse_note, split_by_headings,
)

VAULT = config.VAULT
DB = config.DB
LOCK = config.LOCK
QDRANT_URL = config.QDRANT_URL
COLLECTION = config.COLLECTION
EMBED_MODEL = config.EMBED_MODEL
OLLAMA = config.OLLAMA
DIMS = 1024


def embed_texts(texts: list[str]) -> list[list[float]]:
    out = []
    for i in range(0, len(texts), 16):
        batch = texts[i : i + 16]
        for attempt in range(3):
            try:
                r = requests.post(OLLAMA, json={"model": EMBED_MODEL, "input": batch, "keep_alive": "24h"}, timeout=(5, 120))
                r.raise_for_status()
                out.extend(r.json()["embeddings"])
                break
            except (requests.RequestException, KeyError, ValueError) as e:
                if attempt == 2:
                    raise
                print(f"  embed retry {attempt+1} (batch {i//16}): {e}", file=sys.stderr)
                time.sleep(2 * (attempt + 1))
    return out
_sparse_model = None
def sparse(texts: list[str]) -> list[models.SparseVector]:
    global _sparse_model
    if _sparse_model is None:
        _sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    vecs = []
    for v in _sparse_model.embed(texts):
        vecs.append(models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist()))
    return vecs

def ensure_collection(client: QdrantClient):
    if client.collection_exists(COLLECTION):
        return
    client.create_collection(
        COLLECTION,
        vectors_config={"dense": models.VectorParams(size=DIMS, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
    )
    for field, schema in [
        ("file_path", models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD)),
        ("note_title", models.TextIndexParams(type=models.TextIndexType.TEXT, tokenizer=models.TokenizerType.MULTILINGUAL, lowercase=True)),
        ("tags", models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD)),
        ("mtime", models.DatetimeIndexParams(type=models.DatetimeIndexType.DATETIME)),
    ]:
        client.create_payload_index(COLLECTION, field, schema)

def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()
def manifest():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS files (rel_path TEXT PRIMARY KEY, text_hash TEXT, chunker_version TEXT, embed_model TEXT)")
    # `meta` lets a reader (the MCP server) tell whether the index is current:
    # last_run is the wall-clock time the scan FINISHED, so a note whose mtime is
    # later than it changed after it was embedded.
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    return con

def point_id(rel: str, idx: int) -> str:
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel}#{idx}"))

def index_file(client, con, p: Path, rel: str):
    fm, title, tags, aliases, body = parse_note(p)
    chunks = split_by_headings(title, tags, aliases, body)
    texts = [contextualize(title, tags, aliases, hp, ct) for hp, ct in chunks]
    h = sha("\n\x00\n".join(texts))
    row = con.execute("SELECT text_hash, chunker_version, embed_model FROM files WHERE rel_path=?", (rel,)).fetchone()
    if row and row == (h, CHUNKER_VERSION, EMBED_MODEL):
        return False
    client.delete(COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key="file_path", match=models.MatchValue(value=rel))])))
    dense = embed_texts(texts)
    sp = sparse(texts)
    mtime = p.stat().st_mtime
    points = [
        models.PointStruct(
            id=point_id(rel, i),
            vector={"dense": dense[i], "bm25": sp[i]},
            payload={
                "file_path": rel, "note_title": title, "heading_path": hp,
                "text": ct, "tags": tags, "aliases": aliases, "links": extract_links(ct),
                "type": fm.get("type", "zettel"), "status": fm.get("status", "seedling"),
                "mtime": mtime, "content_hash": h,
            },
        )
        for i, (hp, ct) in enumerate(chunks)
    ]
    client.upsert(COLLECTION, points=points)
    con.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (rel, h, CHUNKER_VERSION, EMBED_MODEL))
    return True

def run(client, full=False):
    con = manifest()
    ensure_collection(client)
    changed = deleted = 0
    current = {}
    t0 = time.time()
    for p, rel in iter_notes():
        current[rel] = p
        try:
            if index_file(client, con, p, rel):
                changed += 1
                if full or changed <= 5 or changed % 50 == 0:
                    print(f"  embedded {changed}: {rel}")
                con.commit()  # per-file: crash-safe, no full re-embed after abort
        except Exception as e:
            print(f"  !! {rel}: {e}", file=sys.stderr)
    for (rel,) in con.execute("SELECT rel_path FROM files").fetchall():
        if rel not in current:
            client.delete(COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key="file_path", match=models.MatchValue(value=rel))])))
            con.execute("DELETE FROM files WHERE rel_path=?", (rel,))
            deleted += 1
    con.commit()
    n = client.count(COLLECTION, exact=True).count
    con.execute("INSERT OR REPLACE INTO meta VALUES ('last_run', ?)", (str(time.time()),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('last_counts', ?)",
                (json.dumps({"changed": changed, "deleted": deleted, "points": n}),))
    con.commit()
    print(f"changed={changed} deleted={deleted} total_points={n} elapsed={time.time()-t0:.1f}s")

def watch(client):
    print("watch mode: polling every 3s")
    while True:
        run(client)
        time.sleep(3)

def main() -> None:
    import fcntl
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another indexer is already running — exit"); sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    client = QdrantClient(url=QDRANT_URL, timeout=60)
    if a.watch: watch(client)
    else: run(client, full=a.full)


if __name__ == "__main__":
    main()

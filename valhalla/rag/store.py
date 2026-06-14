"""FAISS HNSW 向量库 — 无后台进程，无文件锁，启动 <200ms"""
import json
import logging
import numpy as np
from pathlib import Path

import faiss

from valhalla.core.models import Chunk

logger = logging.getLogger(__name__)

VECTOR_DIM = 512
INDEX_FILE = "faiss.index"
META_FILE = "faiss_meta.json"


class VectorStore:
    """FAISS HNSW 向量库：内存索引 + JSON 元数据，无文件锁"""

    def __init__(self, db_path: str | Path):
        self._dir = Path(db_path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index: faiss.Index | None = None
        self._meta: list[dict] = []   # [{chunk_id, bvid, heading, text, ...}]
        self._loaded = False

    # ── 加载 / 保存 ────────────────────────────────

    def load(self):
        """加载索引和元数据 (如果文件存在)"""
        idx_path = self._dir / INDEX_FILE
        meta_path = self._dir / META_FILE
        if idx_path.exists() and meta_path.exists():
            self._index = faiss.read_index(str(idx_path))
            with open(meta_path, encoding="utf-8") as f:
                self._meta = json.load(f)
            self._loaded = True
            logger.info("加载向量索引: %d 条, %d 维", len(self._meta), self._index.d)

    def save(self):
        """持久化索引和元数据到磁盘"""
        if self._index is None:
            return
        faiss.write_index(self._index, str(self._dir / INDEX_FILE))
        with open(self._dir / META_FILE, "w", encoding="utf-8") as f:
            json.dump(self._meta, f, ensure_ascii=False)
        logger.info("保存向量索引: %d 条", len(self._meta))

    # ── CRUD ──────────────────────────────────────

    def add(self, chunks: list[Chunk]):
        """增量追加"""
        valid = [c for c in chunks if c.vector is not None]
        if not valid:
            return
        vectors = np.array([c.vector for c in valid], dtype=np.float32)
        if self._index is None:
            self._index = faiss.IndexHNSWFlat(VECTOR_DIM, 32)
            self._index.hnsw.efConstruction = 200
        self._index.add(vectors)
        for c in valid:
            self._meta.append({
                "chunk_id": c.chunk_id, "bvid": c.bvid,
                "chunk_type": c.chunk_type, "heading": c.heading,
                "text": c.text[:2048],
                "start_time": c.start_time, "end_time": c.end_time,
                "keywords": ", ".join(c.keywords)[:512],
                "published_date": c.published_date,
            })
        self._loaded = False  # needs save

    def search(self, query_vector: list[float], top_k: int = 20,
               date_from: str | None = None, date_to: str | None = None,
               chunk_types: list[str] | None = None) -> list[dict]:
        """向量检索 + 元数据过滤"""
        if self._index is None or len(self._meta) == 0:
            return []

        qv = np.array([query_vector], dtype=np.float32)
        # over-retrieve, then filter
        fetch_k = top_k * 4 if date_from or date_to else top_k
        distances, indices = self._index.search(qv, min(fetch_k, len(self._meta)))

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._meta):
                continue
            meta = self._meta[idx]
            # filter
            if date_from and meta.get("published_date", "") < date_from:
                continue
            if date_to and meta.get("published_date", "") > date_to:
                continue
            if chunk_types and meta.get("chunk_type") not in chunk_types:
                continue

            results.append({
                "entity": meta,
                "distance": float(dist),
            })
            if len(results) >= top_k:
                break
        return results

    def count(self) -> int:
        return len(self._meta)

    def rebuild(self, chunks: list[Chunk]):
        """全量重建"""
        valid = [c for c in chunks if c.vector is not None]
        if not valid:
            return
        vectors = np.array([c.vector for c in valid], dtype=np.float32)
        self._index = faiss.IndexHNSWFlat(VECTOR_DIM, 32)
        self._index.hnsw.efConstruction = 200
        self._index.add(vectors)
        self._meta = [{
            "chunk_id": c.chunk_id, "bvid": c.bvid,
            "chunk_type": c.chunk_type, "heading": c.heading,
            "text": c.text[:2048],
            "start_time": c.start_time, "end_time": c.end_time,
            "keywords": ", ".join(c.keywords)[:512],
            "published_date": c.published_date,
        } for c in valid]
        self.save()

    # ── 兼容旧的 .db 路径 (去掉 Milvus 子目录) ─────
    @staticmethod
    def resolve_path(db_path: str | Path) -> Path:
        p = Path(db_path)
        # 如果传的是旧 Milvus db 文件路径，转为目录
        if p.is_file() or p.suffix == ".db":
            p = p.parent / "faiss_index"
        return p

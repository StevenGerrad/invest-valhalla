"""Milvus Lite 向量库管理"""
import logging
from pathlib import Path

from pymilvus import MilvusClient, DataType

from valhalla.core.models import Chunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "chunks"
VECTOR_DIM = 512


class VectorStore:
    """Milvus Lite 向量库：嵌入式，零运维"""

    def __init__(self, db_path: str | Path):
        self._client = MilvusClient(str(db_path))
        self._ensure_collection()

    def _ensure_collection(self):
        if self._client.has_collection(COLLECTION_NAME):
            self._client.load_collection(COLLECTION_NAME)
            return
        schema = self._client.create_schema(auto_id=False)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=128, is_primary=True)
        schema.add_field("bvid", DataType.VARCHAR, max_length=32)
        schema.add_field("chunk_type", DataType.VARCHAR, max_length=24)
        schema.add_field("heading", DataType.VARCHAR, max_length=128)
        schema.add_field("text", DataType.VARCHAR, max_length=2048)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=VECTOR_DIM)
        schema.add_field("start_time", DataType.FLOAT)
        schema.add_field("end_time", DataType.FLOAT)
        schema.add_field("keywords", DataType.VARCHAR, max_length=512)
        schema.add_field("published_date", DataType.VARCHAR, max_length=10)

        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="HNSW",
                               metric_type="COSINE", params={"M": 16, "efConstruction": 200})
        self._client.create_collection(COLLECTION_NAME, schema=schema,
                                       index_params=index_params)
        self._client.load_collection(COLLECTION_NAME)
        logger.info("创建 Milvus collection: %s", COLLECTION_NAME)

    # ── CRUD ──────────────────────────────────────

    def add(self, chunks: list[Chunk]):
        """批量追加（自动去重，已存在的 chunk_id 跳过）"""
        if not chunks:
            return
        data = [_chunk_to_row(c) for c in chunks if c.vector is not None]
        if not data:
            return
        result = self._client.upsert(COLLECTION_NAME, data)
        logger.info("入库 %d chunks (upsert)", result["upsert_count"])

    def search(self, query_vector: list[float], top_k: int = 20,
               date_from: str | None = None, date_to: str | None = None,
               chunk_types: list[str] | None = None) -> list[dict]:
        """向量检索 + 元数据过滤"""
        filter_parts = []
        if date_from:
            filter_parts.append(f'published_date >= "{date_from}"')
        if date_to:
            filter_parts.append(f'published_date <= "{date_to}"')
        if chunk_types:
            types = ", ".join(f'"{t}"' for t in chunk_types)
            filter_parts.append(f"chunk_type in [{types}]")

        expr = " and ".join(filter_parts) if filter_parts else None
        results = self._client.search(
            COLLECTION_NAME,
            data=[query_vector],
            anns_field="vector",
            limit=top_k,
            filter=expr,
            output_fields=["chunk_id", "bvid", "chunk_type", "heading",
                          "text", "start_time", "end_time", "keywords",
                          "published_date"],
        )
        return results[0] if results else []

    def count(self) -> int:
        return self._client.query(COLLECTION_NAME, filter="", output_fields=["count(*)"])[0]["count(*)"]

    def rebuild(self, chunks: list[Chunk]):
        """全量重建: 先删 collection 再建"""
        if self._client.has_collection(COLLECTION_NAME):
            self._client.drop_collection(COLLECTION_NAME)
        self._ensure_collection()
        if chunks:
            self.add(chunks)


def _chunk_to_row(c: Chunk) -> dict:
    return {
        "chunk_id": c.chunk_id,
        "bvid": c.bvid,
        "chunk_type": c.chunk_type,
        "heading": c.heading[:128],
        "text": c.text[:2048],
        "vector": c.vector,
        "start_time": c.start_time,
        "end_time": c.end_time,
        "keywords": ", ".join(c.keywords)[:512],
        "published_date": c.published_date,
    }

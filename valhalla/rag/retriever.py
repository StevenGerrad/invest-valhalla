"""混合检索: HNSW + BM25 + RRF + video_id 去重 + Parent Document"""
import logging
from collections import defaultdict
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from valhalla.core.models import Chunk, ChunkWithScore
from valhalla.rag.embeddings import BGEEmbedder
from valhalla.rag.store import VectorStore

logger = logging.getLogger(__name__)

RRF_K = 60


class HybridRetriever:
    """混合检索器：向量 + BM25 + RRF 融合"""

    def __init__(self, vector_store: VectorStore, embedder: BGEEmbedder):
        self._vs = vector_store
        self._embedder = embedder
        self._bm25 = None
        self._bm25_corpus: list[Chunk] = []

    def set_corpus(self, chunks: list[Chunk]):
        """设置 BM25 检索用的语料（分词 + 建倒排）"""
        self._bm25_corpus = chunks
        tokenized = [list(jieba.cut(c.text)) for c in chunks]
        self._bm25 = BM25Okapi(tokenized)
        logger.info("BM25 索引: %d 个文档", len(chunks))

    def search(self, query: str, top_k: int = 10,
               date_from: str | None = None,
               date_to: str | None = None,
               prefer_sections: bool = True) -> list[ChunkWithScore]:
        """混合检索主入口"""
        # 一路：向量
        qv = self._embedder.encode_single(query)
        vec_results = self._vs.search(
            qv.tolist(), top_k=20,
            date_from=date_from, date_to=date_to,
        )
        vec_scores: dict[str, float] = {}
        vec_chunks: dict[str, dict] = {}
        for rank, r in enumerate(vec_results):
            cid = r["entity"]["chunk_id"]
            vec_scores[cid] = 1.0 / (RRF_K + rank + 1)
            vec_chunks[cid] = r["entity"]

        # 二路：BM25
        bm25_scores: dict[str, float] = {}
        if self._bm25 is not None:
            tokens = list(jieba.cut(query))
            scores = self._bm25.get_scores(tokens)
            # 取 top-10
            top_indices = sorted(range(len(scores)), key=lambda i: -scores[i])[:10]
            for rank, idx in enumerate(top_indices):
                cid = self._bm25_corpus[idx].chunk_id
                bm25_scores[cid] = 1.0 / (RRF_K + rank + 1)

        # RRF 融合
        merged: dict[str, float] = defaultdict(float)
        for cid, s in vec_scores.items():
            merged[cid] += s
        for cid, s in bm25_scores.items():
            merged[cid] += s

        ranked = sorted(merged.items(), key=lambda x: -x[1])

        # video_id 去重 + 优先 section 类型
        results: list[ChunkWithScore] = []
        seen_videos: set[str] = set()
        for cid, score in ranked:
            row = vec_chunks.get(cid)
            if row is None:
                # BM25-only result, find from corpus
                for c in self._bm25_corpus:
                    if c.chunk_id == cid:
                        row = {
                            "chunk_id": c.chunk_id, "bvid": c.bvid,
                            "chunk_type": c.chunk_type, "heading": c.heading,
                            "text": c.text, "start_time": c.start_time,
                            "end_time": c.end_time, "keywords": ", ".join(c.keywords),
                            "published_date": c.published_date,
                        }
                        break
                if row is None:
                    continue

            vid = row.get("bvid", "")
            if vid and vid in seen_videos:
                continue
            if vid:
                seen_videos.add(vid)

            results.append(ChunkWithScore(
                chunk_id=row.get("chunk_id", ""),
                chunk_type=row.get("chunk_type", "section"),
                bvid=row.get("bvid", ""),
                heading=row.get("heading", ""),
                text=row.get("text", ""),
                start_time=row.get("start_time", 0.0),
                end_time=row.get("end_time", 0.0),
                keywords=row.get("keywords", "").split(", ") if row.get("keywords") else [],
                published_date=row.get("published_date", ""),
                score=score,
            ))

            if len(results) >= top_k:
                break

        return results

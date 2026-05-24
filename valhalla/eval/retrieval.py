"""检索测评: Recall@K / MRR / NDCG"""
import logging
import numpy as np

from valhalla.core.models import EvalCase, ChunkWithScore
from valhalla.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)


def recall_at_k(case: EvalCase, retriever: HybridRetriever, k: int = 5) -> float:
    """相关 chunk 在 top-K 中出现的比例"""
    hits = retriever.search(case.query, top_k=k)
    hit_ids = {h.chunk_id for h in hits}
    if not case.relevant_chunk_ids:
        return 1.0
    found = sum(1 for cid in case.relevant_chunk_ids if cid in hit_ids)
    return found / len(case.relevant_chunk_ids)


def precision_at_k(case: EvalCase, retriever: HybridRetriever, k: int = 5) -> float:
    """top-K 中相关 chunk 的比例"""
    hits = retriever.search(case.query, top_k=k)
    if not hits:
        return 0.0
    hit_ids = {h.chunk_id for h in hits}
    rel = set(case.relevant_chunk_ids)
    return len(hit_ids & rel) / k


def mrr(case: EvalCase, retriever: HybridRetriever, k: int = 10) -> float:
    """第一个相关 chunk 的倒数排名均值"""
    hits = retriever.search(case.query, top_k=k)
    rel = set(case.relevant_chunk_ids)
    for rank, h in enumerate(hits, 1):
        if h.chunk_id in rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(case: EvalCase, retriever: HybridRetriever, k: int = 5) -> float:
    """归一化折损累积增益"""
    hits = retriever.search(case.query, top_k=k)
    rel = set(case.relevant_chunk_ids)
    dcg = sum(1.0 / np.log2(i + 2) for i, h in enumerate(hits) if h.chunk_id in rel)
    ideal = sum(1.0 / np.log2(i + 2) for i in range(min(len(rel), k)))
    if ideal == 0:
        return 1.0 if dcg == 0 else 0.0
    return dcg / ideal


def evaluate(retriever: HybridRetriever, cases: list[EvalCase],
             k: int = 5) -> dict:
    """批量测评检索性能"""
    metrics = {"recall@k": [], "precision@k": [], "mrr": [], "ndcg@k": [], "n": len(cases)}
    for case in cases:
        metrics["recall@k"].append(recall_at_k(case, retriever, k))
        metrics["precision@k"].append(precision_at_k(case, retriever, k))
        metrics["mrr"].append(mrr(case, retriever))
        metrics["ndcg@k"].append(ndcg_at_k(case, retriever, k))

    result = {key: round(np.mean(vals), 4) for key, vals in metrics.items() if key != "n"}
    result["n"] = metrics["n"]
    return result

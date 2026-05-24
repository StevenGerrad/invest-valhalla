"""RAG 回答生成 + source 引用"""
import logging
from datetime import datetime, timezone

from valhalla.core.llm import ChatBackend
from valhalla.core.models import ChunkWithScore, RAGResponse
from valhalla.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """你是"史诗级韭菜"的投资知识助手。
根据以下视频字幕片段回答用户问题。如果信息不足，诚实说不知道，不要编造。

## 引用规则
- 引用具体视频标题和时间点，格式: [《视频标题》@MM:SS]
- 如果多个片段都相关，优先引用最直接的那个

## 禁止
- 不要推荐具体买卖操作
- 不要假装知道视频中没有的内容"""


class RAGGenerator:
    """RAG 回答生成器"""

    def __init__(self, retriever: HybridRetriever, backend: ChatBackend):
        self._retriever = retriever
        self._backend = backend

    def ask(self, question: str, top_k: int = 5,
            date_from: str | None = None) -> RAGResponse:
        """单轮问答"""
        hits = self._retriever.search(
            question, top_k=top_k, date_from=date_from,
        )
        context = self._build_context(hits)
        prompt = f"{context}\n\n问题：{question}"
        answer = self._backend.chat(RAG_SYSTEM_PROMPT, prompt)

        sources = [{
            "bvid": h.bvid,
            "heading": h.heading,
            "text": h.text[:120],
            "start_time": h.start_time,
            "score": round(h.score, 3),
        } for h in hits]

        return RAGResponse(answer=answer, sources=sources, query=question)

    def _build_context(self, hits: list[ChunkWithScore]) -> str:
        blocks = []
        for i, h in enumerate(hits, 1):
            ts = _format_time(h.start_time)
            blocks.append(
                f"[{i}] 《{h.heading}》 @{ts}\n{h.text}"
            )
        return "【参考片段】\n" + "\n\n".join(blocks)


def _format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

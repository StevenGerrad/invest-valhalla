"""数字人多轮对话管理 + 查询改写"""
import logging
import uuid
from datetime import datetime, timezone

from valhalla.core.llm import ChatBackend
from valhalla.core.models import Message, RAGResponse
from valhalla.rag.retriever import HybridRetriever
from valhalla.rag.generator import RAG_SYSTEM_PROMPT
from valhalla.agent.persona import PERSONA_PROMPT

logger = logging.getLogger(__name__)

MAX_HISTORY = 10


class ConversationAgent:
    """数字人对话代理"""

    def __init__(self, retriever: HybridRetriever, backend: ChatBackend):
        self._retriever = retriever
        self._backend = backend
        self._sessions: dict[str, list[Message]] = {}

    def chat(self, session_id: str | None, user_message: str) -> RAGResponse:
        """处理一轮对话，返回带来源的回答"""
        sid = session_id or str(uuid.uuid4())[:8]
        history = self._sessions.get(sid, [])

        # 1. 查询改写: 追问时用历史补充上下文
        query = self._enrich_query(user_message, history)

        # 2. 检索
        hits = self._retriever.search(query, top_k=5)

        # 3. 构建 context
        context = "\n\n".join(
            f"[{i+1}] 《{h.heading}》 @{_fmt_ts(h.start_time)}\n{h.text}"
            for i, h in enumerate(hits)
        )

        # 4. 拼接历史
        history_str = ""
        if history:
            recent = history[-MAX_HISTORY:]
            history_str = "\n".join(
                f"{'用户' if m.role == 'user' else '韭菜'}: {m.content[:200]}"
                for m in recent
            )
            history_str = f"【对话历史】\n{history_str}\n\n"

        # 5. 生成
        prompt = (
            f"{history_str}"
            f"【参考片段】\n{context}\n\n"
            f"用户: {user_message}"
        )
        answer = self._backend.chat(PERSONA_PROMPT, prompt)

        # 6. 保存历史
        history.append(Message(role="user", content=user_message))
        history.append(Message(role="assistant", content=answer))
        self._sessions[sid] = history

        sources = [{
            "bvid": h.bvid, "heading": h.heading,
            "text": h.text[:120], "start_time": h.start_time,
            "score": round(h.score, 3),
        } for h in hits]

        return RAGResponse(answer=answer, sources=sources, query=query)

    def _enrich_query(self, user_message: str, history: list[Message]) -> str:
        """用历史最后 3 轮增强查询，处理追问"""
        if not history:
            return user_message
        recent = history[-6:]  # 最近 3 轮
        if not recent:
            return user_message
        parts = [m.content for m in recent]
        parts.append(user_message)
        combined = " ".join(parts)
        if len(combined) > 500:
            combined = user_message  # 太长不用历史
        return combined


def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

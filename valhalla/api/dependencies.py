"""FastAPI 依赖注入：向量库 / embedder / retriever / session 单例"""
import json
import logging
from functools import lru_cache
from pathlib import Path

from valhalla.core.llm import DeepSeekBackend
from valhalla.rag.embeddings import BGEEmbedder
from valhalla.rag.chunker import build_all_chunks
from valhalla.rag.store import VectorStore
from valhalla.rag.retriever import HybridRetriever
from valhalla.rag.generator import RAGGenerator
from valhalla.agent.conversation import ConversationAgent

logger = logging.getLogger(__name__)
OUTPUT = Path("output")


# ── 单例（应用生命周期内复用）─────────────────────

class AppState:
    def __init__(self, mid: int):
        self.mid = mid
        self._store: VectorStore | None = None
        self._embedder: BGEEmbedder | None = None
        self._retriever: HybridRetriever | None = None
        self._generator: RAGGenerator | None = None
        self._backend: DeepSeekBackend | None = None

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            index_dir = OUTPUT / str(self.mid) / "faiss_index"
            index_dir.mkdir(parents=True, exist_ok=True)
            self._store = VectorStore(str(index_dir))
            self._store.load()
            if self._store.count() == 0:
                raise FileNotFoundError(
                    f"向量库为空: {index_dir}\n请先运行: python -m valhalla.rag build --mid {self.mid}")
        return self._store

    @property
    def embedder(self) -> BGEEmbedder:
        if self._embedder is None:
            self._embedder = BGEEmbedder()
        return self._embedder

    @property
    def retriever(self) -> HybridRetriever:
        if self._retriever is None:
            self._retriever = HybridRetriever(self.store, self.embedder)
            processed_dir = OUTPUT / str(self.mid) / "processed"
            dates = _load_dates(self.mid)
            chunks = build_all_chunks(processed_dir, dates)
            self._retriever.set_corpus(chunks)
        return self._retriever

    @property
    def generator(self) -> RAGGenerator:
        if self._generator is None:
            self._generator = RAGGenerator(self.retriever, self.backend)
        return self._generator

    @property
    def backend(self) -> DeepSeekBackend:
        if self._backend is None:
            self._backend = DeepSeekBackend()
        return self._backend


class SessionManager:
    """管理对话 session: 每个 session_id 一个 ConversationAgent"""

    def __init__(self, state: AppState):
        self._state = state
        self._agents: dict[str, ConversationAgent] = {}

    def get_or_create(self, session_id: str | None) -> tuple[str, ConversationAgent]:
        sid = session_id or _new_session_id()
        if sid not in self._agents:
            self._agents[sid] = ConversationAgent(self._state.retriever, self._state.backend)
        return sid, self._agents[sid]

    def remove(self, session_id: str):
        self._agents.pop(session_id, None)


# ── 工厂函数 ──────────────────────────────────────

@lru_cache(maxsize=1)
def get_app_state(mid: int) -> AppState:
    logger.info("初始化 AppState (mid=%d)", mid)
    return AppState(mid)


def get_session_manager(mid: int) -> SessionManager:
    return SessionManager(get_app_state(mid))


# ── 工具 ──────────────────────────────────────────

def _load_dates(mid: int) -> dict[str, str]:
    idx_path = OUTPUT / str(mid) / "index.json"
    if not idx_path.exists():
        return {}
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    return {bvid: v.get("published_date", "")
            for bvid, v in data.get("videos", {}).items()}


def _new_session_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]

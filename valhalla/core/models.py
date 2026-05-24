"""统一领域模型 (Pydantic)"""
from pydantic import BaseModel


# ── 视频与字幕 ──────────────────────────────

class Segment(BaseModel):
    start: float
    end: float
    text: str


class VideoMeta(BaseModel):
    bvid: str
    title: str
    author: str
    length: str              # "MM:SS"
    published_ts: int
    published_date: str      # "YYYY-MM-DD"
    play_count: int = 0
    srt_file: str = ""
    segment_count: int = 0


# ── Layer 3 语义文本 ────────────────────────

class ProcessedSection(BaseModel):
    heading: str
    start_time: float
    end_time: float
    text: str
    keywords: list[str] = []


class ProcessedText(BaseModel):
    bvid: str
    title: str
    sections: list[ProcessedSection]
    global_keywords: list[str] = []


# ── Layer 4 检索分段 ────────────────────────

class Chunk(BaseModel):
    chunk_id: str            # {bvid}_{section_id}_{sub_id}
    chunk_type: str          # "section" | "section_fragment" | "keywords" | "video_summary"
    bvid: str
    heading: str
    text: str
    start_time: float
    end_time: float
    keywords: list[str] = []
    published_date: str = ""
    vector: list[float] | None = None


class ChunkWithScore(Chunk):
    score: float = 0.0
    full_context: str = ""   # Parent Document: 完整 section 文本


# ── 对话 ────────────────────────────────────

class Message(BaseModel):
    role: str                # "user" | "assistant"
    content: str


# ── RAG 响应 ────────────────────────────────

class RAGResponse(BaseModel):
    answer: str
    sources: list[dict]      # [{bvid, heading, text, start_time, score}]
    query: str = ""


# ── 测评 ────────────────────────────────────

class EvalCase(BaseModel):
    query: str
    type: str                # "factual" | "multi_hop" | "global" | "persona"
    relevant_chunk_ids: list[str] = []
    min_sources: int = 1

"""对话路由: POST /chat (全量) + GET /chat/stream (SSE流式)"""
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from valhalla.api.dependencies import SessionManager, get_session_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _sse(data: dict) -> str:
    """SSE data 行, 中文直接输出 (不用 \\uXXXX)"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mid: int = 322005137


class SourceItem(BaseModel):
    bvid: str
    heading: str
    text: str
    start_time: float
    score: float
    url: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    session_id: str


def _format_sources(sources: list[dict]) -> list[SourceItem]:
    items = []
    for s in sources:
        ts = int(s.get("start_time", 0))
        bvid = s.get("bvid", "")
        url = f"https://www.bilibili.com/video/{bvid}?t={ts}" if bvid else ""
        items.append(SourceItem(
            bvid=bvid,
            heading=s.get("heading", ""),
            text=s.get("text", "")[:200],
            start_time=s.get("start_time", 0),
            score=s.get("score", 0),
            url=url,
        ))
    return items


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        sm = get_session_manager(req.mid)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        _, agent = sm.get_or_create(req.session_id)
        resp = agent.chat(req.session_id, req.message)
        return ChatResponse(
            answer=resp.answer,
            sources=_format_sources(resp.sources),
            session_id=resp.sources[0].get("bvid", "")[:8] if resp.sources else "",
        )
    except Exception as e:
        logger.error("对话失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
async def chat_stream(
    message: str = Query(...),
    session_id: str | None = Query(None),
    mid: int = Query(322005137),
):
    try:
        sm = get_session_manager(mid)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    async def event_stream():
        try:
            yield _sse({'type': 'connected'})

            try:
                _, agent = sm.get_or_create(session_id)
            except Exception as e:
                yield _sse({'type': 'error', 'message': f'会话初始化失败: {e}'})
                yield _sse({'type': 'done'})
                return

            yield _sse({'type': 'step', 'step': 'agent_ready'})

            # 流式输出 (agent.chat_stream 内部已含 search + LLM)
            try:
                for event_type, content in agent.chat_stream(session_id, message):
                    if event_type == "reasoning":
                        yield _sse({'type': 'reasoning', 'content': content})
                    elif event_type == "text":
                        yield _sse({'type': 'text', 'content': content})
                    elif event_type == "sources":
                        items = _format_sources(content)
                        yield _sse({'type': 'sources', 'sources': [s.model_dump() for s in items]})
                    elif event_type == "step":
                        payload = {"type": content["type"]}
                        payload.update({k: v for k, v in content.items() if k != "type"})
                        yield _sse(payload)
                    elif event_type == "ping":
                        yield ": keepalive\n\n"  # SSE comment, 保持连接
                    elif event_type == "done":
                        yield _sse({'type': 'done'})
            except Exception as e:
                logger.error("Agent 流式失败: %s", e, exc_info=True)
                yield _sse({'type': 'error', 'message': f'生成失败: {e}'})
                yield _sse({'type': 'done'})

        except Exception as e:
            logger.error("SSE 连接级失败: %s", e, exc_info=True)
            yield _sse({'type': 'error', 'message': str(e)})
            yield _sse({'type': 'done'})

    return StreamingResponse(event_stream(), media_type="text/event-stream")

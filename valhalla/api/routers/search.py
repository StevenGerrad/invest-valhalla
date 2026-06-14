"""搜索路由: GET /search"""
import logging

from fastapi import APIRouter, HTTPException, Query

from valhalla.api.dependencies import get_app_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(5, ge=1, le=50),
    mid: int = Query(322005137),
):
    try:
        state = get_app_state(mid)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    hits = state.retriever.search(q, top_k=top_k)
    return {
        "query": q,
        "results": [{
            "bvid": h.bvid,
            "heading": h.heading,
            "text": h.text[:200],
            "start_time": h.start_time,
            "score": round(h.score, 4),
        } for h in hits],
    }

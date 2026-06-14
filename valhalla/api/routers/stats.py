"""统计路由: GET /stats"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from valhalla.api.dependencies import get_app_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])
OUTPUT = Path("output")


@router.get("")
async def stats(mid: int = Query(322005137)):
    idx_path = OUTPUT / str(mid) / "index.json"
    videos = 0
    if idx_path.exists():
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        videos = len(data.get("videos", {}))

    chunks = 0
    try:
        state = get_app_state(mid)
        chunks = state.store.count()
    except Exception:
        pass

    return {
        "mid": mid,
        "videos": videos,
        "chunks": chunks,
    }

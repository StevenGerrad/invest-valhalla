"""前端页面路由: GET /"""
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["pages"])


@router.get("/")
async def index():
    return FileResponse("web/index.html")

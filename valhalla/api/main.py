"""FastAPI 应用入口 + lifespan"""
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from valhalla.core.logging import setup as setup_logging, access_logger

setup_logging()
logger = logging.getLogger(__name__)
access = access_logger()


class AccessMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的方法/路径/状态码/耗时"""

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0
        sid = request.query_params.get("session_id", "-") or "-"
        access.info("%s %s %s %.2fs session=%s",
                    request.method, request.url.path,
                    response.status_code, elapsed, sid[:16])
        return response


def create_app(mid: int = 322005137) -> FastAPI:

    app = FastAPI(
        title="Valhalla API",
        description="史诗级韭菜 — 数字人对话服务",
        version="0.4.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Access 日志 (放在中间件链最外层)
    app.add_middleware(AccessMiddleware)

    # 前端静态文件
    web_dir = Path("web")
    if web_dir.exists():
        app.mount("/static/web", StaticFiles(directory=str(web_dir)), name="web_static")

    # 路由
    from valhalla.api.routers import chat, search, stats, pages
    app.include_router(chat.router, prefix="/chat")
    app.include_router(search.router, prefix="/search")
    app.include_router(stats.router, prefix="/stats")
    app.include_router(pages.router)

    # 健康检查
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # 启动预热 (带重试)
    @app.on_event("startup")
    async def warmup():
        for attempt in range(3):
            try:
                from valhalla.api.dependencies import get_app_state
                state = get_app_state(mid)
                _ = state.retriever
                logger.info("预热完成 (mid=%d)", mid)
                return
            except FileNotFoundError:
                logger.warning("向量库未构建: python -m valhalla.rag build --mid %d", mid)
                return
            except Exception as e:
                logger.warning("预热失败 (尝试 %d/3): %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(3)
        logger.error("预热失败，服务可能不可用")

    return app

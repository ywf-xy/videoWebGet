"""FastAPI 应用入口：日志 → 数据库 → 引擎启动 → 路由 → 静态托管。

启动顺序（缺一不可）：
1. ``setup_logging`` 让后续所有模块日志落盘 ``logs/app.log``；
2. ``init_db`` 建表 + 迁移 + 种子数据（首启生成 data/crawlerhub.db）；
3. ``CrawlerEngine.start`` 复位孤儿任务、同步并发上限、探测 ffmpeg；
4. 挂载 ``/api`` 路由；若 ``frontend/dist`` 存在则单端口托管前端产物。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import build_router
from app.common.errors import BizError, ErrCode, http_status_for
from app.common.logger import get_logger, setup_logging
from app.config import (
    API_PREFIX,
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    ensure_base_dirs,
    settings,
)
from app.db.base import dispose_engine, init_db
from app.engine.crawler_engine import get_engine
from app.schemas.common import fail

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动与关闭钩子。"""
    setup_logging(settings.log_path)
    ensure_base_dirs()
    init_db()
    engine = get_engine()
    engine.start()
    logger.info(
        "%s v%s 启动完成：http://%s:%s%s/docs",
        APP_NAME,
        APP_VERSION,
        settings.host,
        settings.port,
        API_PREFIX,
    )
    try:
        yield
    finally:
        engine.shutdown()
        dispose_engine()
        logger.info("%s 已关闭", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 异常处理：业务码与 HTTP 码并存，响应体统一 {"code","data","message"}
# ---------------------------------------------------------------------------
@app.exception_handler(BizError)
async def handle_biz_error(_request: Request, exc: BizError) -> JSONResponse:
    """业务异常 → 对应 HTTP 状态 + 业务码。"""
    logger.info("业务异常：%s", exc)
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """入参校验失败 → 1001，message 拼接首个错误位置。"""
    errors = exc.errors()
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = f"{location}: {first.get('msg', '参数校验失败')}" if location else str(
            first.get("msg", "参数校验失败")
        )
    else:
        message = "参数校验失败"
    logger.warning("参数校验失败：%s", message)
    return JSONResponse(status_code=400, content=fail(ErrCode.PARAM_INVALID, message))


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTP 异常 → 统一响应体（404 路由不存在归入入参错误段）。"""
    code = ErrCode.PARAM_INVALID if exc.status_code < 500 else ErrCode.INTERNAL
    message = str(exc.detail or http_status_for(int(code)))
    return JSONResponse(status_code=exc.status_code, content=fail(code, message))


@app.exception_handler(Exception)
async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    """兜底异常 → 5000（不向客户端暴露内部细节）。"""
    logger.exception("未预期异常：%s", exc)
    return JSONResponse(
        status_code=500,
        content=fail(ErrCode.INTERNAL, "服务内部错误，请查看 logs/app.log"),
    )


# ---------------------------------------------------------------------------
# 路由与静态资源
# ---------------------------------------------------------------------------
app.include_router(build_router())

# 头像等静态资源
settings.static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

# 前端构建产物（存在才托管，开发态走 5173）
if settings.frontend_dist.exists():
    app.mount(
        "/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="web"
    )
    logger.info("已托管前端产物：%s", settings.frontend_dist)
else:
    logger.info("未找到前端产物目录（%s），仅提供 API 服务", settings.frontend_dist)

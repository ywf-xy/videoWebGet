"""开发/生产启动脚本。

用法::

    python backend/run.py               # 或
    python -m backend.run               # 在项目根目录执行

端口与绑定地址来自环境变量 ``CRAWLERHUB_PORT`` / ``CRAWLERHUB_HOST``，
默认仅监听 127.0.0.1:8000（PRD NFR-18）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许以 `python -m backend.run` 方式启动时正确导入 app 包
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import APP_NAME, APP_VERSION, settings  # noqa: E402


def main() -> None:
    """启动 uvicorn（不使用 uvicorn 自带日志配置，保持统一格式）。"""
    import uvicorn

    print(
        f"{APP_NAME} v{APP_VERSION} 启动中：http://{settings.host}:{settings.port}/docs"
    )
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=int(settings.port),
        reload=False,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()

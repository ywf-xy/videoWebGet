"""SQLAlchemy 2.x 引擎 / 会话 / PRAGMA。

关键约定（ARCHITECTURE §11.7）：
- SQLite 必须 ``check_same_thread=False``（引擎线程池跨线程使用）；
- 必开 ``journal_mode=WAL``、``synchronous=NORMAL``、``busy_timeout=5000``、``foreign_keys=ON``；
- 写操作全部走 ``session_scope()`` 短事务，禁止跨线程共享 Session。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""


def _build_engine() -> Engine:
    """创建 SQLite 引擎（连接串使用正斜杠，兼容 Windows）。"""
    db_file = settings.db_file
    db_file.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_file.as_posix()}"
    return create_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15.0},
    )


engine: Engine = _build_engine()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
    """每个连接建立时设置 SQLite PRAGMA（WAL 等）。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """短事务上下文：成功提交、异常回滚、始终关闭。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """新建一个调用方自管的 Session（引擎线程内按需使用）。"""
    return SessionLocal()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用的会话生成器（提交由 services 层负责）。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """初始化数据库：建表 → 版本化迁移 → 种子数据（幂等）。"""
    from app.db import migrate, models, seed  # noqa: F401  确保模型已注册到 metadata

    Base.metadata.create_all(bind=engine)
    migrate.run()
    seed.run()
    logger.info("数据库初始化完成：%s", settings.db_file)


def dispose_engine() -> None:
    """释放连接池（进程退出时调用）。"""
    engine.dispose()

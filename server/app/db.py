# -*- coding: utf-8 -*-
"""数据库连接与会话。所有时间统一用 UTC。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from starlette.requests import Request

from .config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Database:
    """一个进程一份 engine；测试里每个用例独立一个 SQLite 文件。"""

    def __init__(self, settings: Settings):
        kwargs: dict = {"pool_pre_ping": True, "future": True}
        if settings.sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(settings.database_url, **kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False, class_=Session
        )

    def create_all(self) -> None:
        from . import models  # noqa: F401  确保模型已注册

        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def get_db(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    session = db.session()
    try:
        yield session
    finally:
        session.close()

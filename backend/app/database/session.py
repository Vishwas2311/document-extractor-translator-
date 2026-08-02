from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, future=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        if database_url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", self._configure_sqlite)

    @staticmethod
    def _configure_sqlite(dbapi_connection: Any, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async def create_schema(self) -> None:
        from app.database.base import Base
        from app.models import document, processing_job  # noqa: F401

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def ensure_prd_columns(self) -> None:
        """Add PRD-readiness columns on existing SQLite databases (create_all won't alter)."""
        statements = [
            "ALTER TABLE documents ADD COLUMN data_class VARCHAR(32) DEFAULT 'synthetic'",
            "ALTER TABLE documents ADD COLUMN processing_profile VARCHAR(64) DEFAULT 'GENAI_PSEUDONYMIZED'",
        ]
        async with self.engine.begin() as connection:

            def _migrate(sync_conn: Any) -> None:
                for statement in statements:
                    try:
                        sync_conn.exec_driver_sql(statement)
                    except Exception:
                        # Column already exists — ignore.
                        pass

            await connection.run_sync(_migrate)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()

import datetime
from logging import INFO, Logger, getLogger

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tiny_ca.db.async_db_manager import AsyncDBHandler
from tiny_ca.db.models import Base

from tiny_ca_gateway.models import API_SETTINGS


class SystemSettings(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True)

    internal_token_valid_until = Column(DateTime)


class LocalDBHandler(AsyncDBHandler):
    async def get_system_init_time(self) -> SystemSettings | None:
        async with self._db.get_session() as session:
            stmt = select(SystemSettings)

            result = await session.execute(stmt)
            cert = result.scalar_one_or_none()

            return cert  # type: ignore[no-any-return]

    async def _init_sys_time(self) -> None:
        async with self._db.get_session() as session:
            try:
                internal_token_valid_until = (
                    datetime.datetime.now()
                    + datetime.timedelta(minutes=API_SETTINGS.ttl_token)
                )

                new_cert = SystemSettings(
                    internal_token_valid_until=internal_token_valid_until
                )
                session.add(new_cert)
                API_SETTINGS.internal_token_valid_until = internal_token_valid_until
                await session.commit()
            except Exception:
                self._logger.warning("Can't save init time")

    async def init_system_time_if_empty(self) -> None:
        sys_settings = await self.get_system_init_time()
        if sys_settings is None:
            await self._init_sys_time()
        else:
            API_SETTINGS.internal_token_valid_until = (
                sys_settings.internal_token_valid_until  # type: ignore
            )

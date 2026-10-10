from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker as async_sessionmaker
from app.core.config import settings


engine = create_async_engine(
    settings.database_url,
    echo=True,
    future=True)

async_session = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession)

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session

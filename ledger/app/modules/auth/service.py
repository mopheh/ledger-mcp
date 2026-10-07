import hashlib
import secrets
import string
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.model import APIKey
from app.modules.auth.schema import APIKeyCreateSchema, APIKeyResponseSchema, Environment
from app.modules.users.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _generate_api_key(environment: Environment, length: int = 32) -> tuple[str, str]:
    """Return (plaintext_key, sha256_hash) for a new key."""
    prefix = f"sk_{environment.value}_"
    alphabet = string.ascii_letters + string.digits
    api_key = prefix + "".join(secrets.choice(alphabet) for _ in range(length))
    return api_key, _hash_key(api_key)


async def generate_api_key_service(
    session: AsyncSession, data: APIKeyCreateSchema, user: User
) -> APIKeyResponseSchema:
    """Create an API key owned by `user`. The plaintext is returned only once."""
    api_key, hashed_key = _generate_api_key(data.environment)
    session.add(
        APIKey(
            key_hash=hashed_key,
            prefix=f"sk_{data.environment.value}_",
            user_id=user.id,
            name=data.name,
        )
    )
    await session.commit()
    return APIKeyResponseSchema(key=api_key)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: resolve `Authorization: Bearer sk_...` to its User."""
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or invalid Authorization header"
        )

    result = await session.execute(
        select(APIKey).where(
            APIKey.key_hash == _hash_key(credentials.credentials),
            APIKey.is_active.is_(True),
            or_(APIKey.expires_at.is_(None), APIKey.expires_at > datetime.now(timezone.utc)),
        )
    )
    key = result.scalars().first()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    user = await session.get(User, key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    key.last_used_at = datetime.now(timezone.utc)
    session.add(key)
    await session.commit()
    return user

async def list_api_keys(session: AsyncSession, user: User) -> list[APIKey]:
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(session: AsyncSession, key_id: int, user: User) -> APIKey:
    """Deactivate one of the user's keys. Idempotent; 404 if it isn't theirs."""
    key = await session.get(APIKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if key.is_active:
        key.is_active = False
        session.add(key)
        await session.commit()
        await session.refresh(key)
    return key

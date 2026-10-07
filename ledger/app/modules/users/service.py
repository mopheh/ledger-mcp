from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.modules.users.models import User
from app.modules.users.schemas import SignInRequest, SignUpRequest

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/sign-in")


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Password must be at most 72 bytes"
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expires_minutes
    )
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def sign_up(session: AsyncSession, data: SignUpRequest) -> User:
    if await get_user_by_email(session, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")


    user = User(
                name=data.name,
                email=data.email,
                password_hash=hash_password(data.password),    
            )
    
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def sign_in(session: AsyncSession, data: SignInRequest) -> str:
    user = await get_user_by_email(session, data.email)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is deactivated")

    return create_access_token(user.id)


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User))
    return list(result.scalars().all())

async def get_current_user(
    session: AsyncSession = Depends(get_session),
    token: str = Depends(oauth2_scheme),
) -> User:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = await get_user(session, user_id)
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is deactivated")
    return user
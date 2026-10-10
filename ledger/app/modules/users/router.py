from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.users import service
from app.modules.users.models import User
from app.modules.users.schemas import (
    SignInRequest,
    SignUpRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)


@router.post("/sign-up", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def sign_up(data: SignUpRequest, session: AsyncSession = Depends(get_session)):
    return await service.sign_up(session, data)


@router.post("/sign-in", response_model=TokenResponse)
async def sign_in(data: SignInRequest, session: AsyncSession = Depends(get_session)):
    token = await service.sign_in(session, data)
    return TokenResponse(access_token=token)


@router.post("/token", response_model=TokenResponse, include_in_schema=True)
async def token(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    """OAuth2 password flow for Swagger's Authorize button. `username` is the email."""
    access_token = await service.sign_in(
        session, SignInRequest(email=form.username, password=form.password)
    )
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(service.get_current_user)):
    return current_user

@router.get("/list-users", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(service.get_current_user),
):
    users = await service.list_users(session)
    return users
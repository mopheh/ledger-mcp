from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth import service
from app.modules.auth.schema import APIKeyCreateSchema, APIKeyReadSchema, APIKeyResponseSchema
from app.modules.users.models import User
from app.modules.users.service import get_current_user

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "/generate-api-key",
    response_model=APIKeyResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def generate_api_key(
    data: APIKeyCreateSchema,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Generate an API key for the signed-in user (JWT required).
    The plaintext key is returned once and cannot be retrieved later.
    """
    return await service.generate_api_key_service(session, data, current_user)


@router.get("/api-keys", response_model=list[APIKeyReadSchema])
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List the signed-in user's API keys (metadata only, never the secret)."""
    return await service.list_api_keys(session, current_user)


@router.delete("/api-keys/{key_id}", response_model=APIKeyReadSchema)
async def revoke_api_key(
    key_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Revoke one of the signed-in user's API keys. Takes effect immediately."""
    return await service.revoke_api_key(session, key_id, current_user)


@router.post("/verify-api-key", response_model=bool)
async def verify_api_key(_: User = Depends(service.verify_api_key)):
    """Returns True if the Bearer API key is valid; otherwise responds 401."""
    return True

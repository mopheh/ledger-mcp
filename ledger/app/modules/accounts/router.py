from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_session
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountRead,
    AccountTransaction,
    TransactionRead,
    TransferRequest,
)
from app.modules.users.models import User
from app.modules.auth.service import verify_api_key
from app.modules.users.service import get_current_user


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    responses={404: {"description": "Not found"}},
)


@router.get("/check-balance", response_model=dict)
async def check_balance(
    session: AsyncSession = Depends(get_session),
    auth_user: User = Depends(verify_api_key),
    account_id: int | None = None,
):
    # account_id may be omitted when the caller has exactly one account.
    balance = await service.check_balance(session, account_id, auth_user)
    return { "balance": balance }



@router.post("/create-account")
async def create_account(
    data: service.AccountCreate,
    session: AsyncSession = Depends(get_session),
    auth_user: User = Depends(get_current_user),
):
    account = await service.create_account(session, data, auth_user)
    return account


@router.get("/list-accounts", response_model=list[AccountRead])
async def list_accounts(
    session: AsyncSession = Depends(get_session),
    auth_user: User = Depends(get_current_user),
):
    """List the signed-in user's own accounts."""
    return await service.list_accounts(session, auth_user)


@router.post("/{account_id}/deposit", response_model=AccountRead)
async def deposit(
    account_id: int,
    data: AccountTransaction,
    session: AsyncSession = Depends(get_session),
    auth_user: User = Depends(get_current_user),
):
    """Fund one of your own accounts (counter-entry on the system account)."""
    await service.get_account(session, account_id, auth_user)  # ownership check
    return await service.deposit(session, account_id, data.amount)


@router.post("/{account_id}/withdraw", response_model=AccountRead)
async def withdraw(
    account_id: int,
    data: AccountTransaction,
    session: AsyncSession = Depends(get_session),
    auth_user: User = Depends(get_current_user),
):
    await service.get_account(session, account_id, auth_user)  # ownership check
    return await service.withdraw(session, account_id, data.amount)


@router.post("/transfer", response_model=TransactionRead)
async def transfer(
    data: TransferRequest,
    session: AsyncSession = Depends(get_session),
    auth_user: User = Depends(verify_api_key),
):
    
    to_account = await service.get_account_by_number(session, data.to_account_number)
    if not to_account:
        raise HTTPException(status_code=404, detail="Receiving account not found")
    return await service.transfer(
        session,
        from_account_id=data.from_account_id,
        to_account_id=to_account.id,
        amount=data.amount,
        idempotency_key=data.idempotency_key,
        auth_user=auth_user,
    )
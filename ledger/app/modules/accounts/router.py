from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_session
from app.modules.accounts import service
from app.modules.accounts.schemas import TransactionRead, TransferRequest
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


@router.get("/list-accounts")
async def list_accounts(session: AsyncSession = Depends(get_session)):
    accounts = await service.list_accounts(session)
    return accounts


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
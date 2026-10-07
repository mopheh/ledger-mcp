from datetime import datetime

from pydantic import BaseModel

from app.modules.accounts.models import TransactionType


class AccountCreate(BaseModel):
    user_id: int
    accountNumber: str
    currency: str
    accountType: str


class AccountRead(BaseModel):
    id: int
    accountNumber: str
    currency: str
    accountType: str
    balance: int

    class Config:
        from_attributes = True


class AccountTransaction(BaseModel):
    amount: int


class TransferRequest(BaseModel):
    from_account_id: int 
    to_account_number: str
    amount: int
    idempotency_key: str


class TransactionRead(BaseModel):
    id: int
    idempotency_key: str
    type: TransactionType
    from_account_id: int | None
    to_account_id: int | None
    amount: int
    initiated_by_user_id: int | None
    created_at: datetime

    class Config:
        from_attributes = True

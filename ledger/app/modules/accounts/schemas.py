from datetime import datetime

from pydantic import BaseModel, field_validator

from app.modules.accounts.models import AccountType, TransactionType


class AccountCreate(BaseModel):
    accountNumber: str
    currency: str
    accountType: AccountType = AccountType.USER

    @field_validator("accountType")
    @classmethod
    def no_system_accounts(cls, v: AccountType) -> AccountType:
        if v == AccountType.SYSTEM:
            raise ValueError("System accounts cannot be created via the API")
        return v


class AccountRead(BaseModel):
    id: int
    accountNumber: str
    currency: str
    accountType: AccountType
    balance: int

    class Config:
        from_attributes = True


class AccountTransaction(BaseModel):
    amount: int
    # Retrying a request with the same key returns the original result.
    idempotency_key: str


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

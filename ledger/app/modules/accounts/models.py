import enum
from datetime import datetime, timezone

from sqlmodel import SQLModel, Field, UniqueConstraint


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"


class Account(SQLModel, table=True):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("accountType", "user_id", "currency", name="uq_user_account_type"),                )

    id: int  = Field(default=None, primary_key=True)
    accountNumber: str = Field(index=True, unique=True)
    currency: str = Field(index=True)
    accountType: str = Field(index=True)
    balance: int = Field(default=0)
    user_id: int = Field(foreign_key="user.id", index=True)


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"

    id: int | None = Field(default=None, primary_key=True)
    idempotency_key: str = Field(index=True, unique=True)
    type: TransactionType
    from_account_id: int | None = Field(default=None, foreign_key="accounts.id")
    to_account_id: int | None = Field(default=None, foreign_key="accounts.id")
    amount: int
    initiated_by_user_id: int | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
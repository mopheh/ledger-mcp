import enum
from datetime import datetime, timezone

from sqlalchemy import Enum as SAEnum
from sqlalchemy import CheckConstraint
from sqlmodel import SQLModel, Field, UniqueConstraint


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"

class AccountType(str, enum.Enum):
    USER = "user"
    SYSTEM = "system"


class Account(SQLModel, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("accountType", "user_id", "currency", name="uq_user_account_type"),
        # Only system accounts may go negative (they mirror all user deposits).
        CheckConstraint(
            """balance >= 0 OR "accountType" = 'system'""",
            name="ck_accounts_balance_non_negative",
        ),
    )

    id: int  = Field(default=None, primary_key=True)
    accountNumber: str = Field(index=True, unique=True)
    currency: str = Field(index=True)
    # Stored as VARCHAR holding the enum *values* ("user"/"system"), not names.
    accountType: AccountType = Field(
        sa_type=SAEnum(
            AccountType,
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        index=True,
    )
    balance: int = Field(default=0)
    user_id: int = Field(foreign_key="user.id", index=True, nullable=True)


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    # Keys are scoped per user: two users may reuse the same key string.
    __table_args__ = (
        UniqueConstraint(
            "initiated_by_user_id",
            "idempotency_key",
            name="uq_transactions_user_idempotency_key",
        ),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )

    id: int | None = Field(default=None, primary_key=True)
    idempotency_key: str = Field(index=True)
    type: TransactionType
    from_account_id: int | None = Field(default=None, foreign_key="accounts.id")
    to_account_id: int | None = Field(default=None, foreign_key="accounts.id")
    amount: int
    initiated_by_user_id: int | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
from sqlmodel import Field, SQLModel
from datetime import datetime, timezone

from app.modules.ledger_entries.schema import LedgerDirection

class LedgerEntry(SQLModel, table=True):
    __tablename__ = "ledger_entries"
    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id")
    transaction_id: int = Field(foreign_key="transactions.id")
    direction: LedgerDirection = Field(index=True)
    amount: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

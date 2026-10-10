import datetime
import enum

class LedgerDirection(str, enum.Enum):
    credit = "credit"
    debit = "debit"

class LedgerEntryCreate:
    account_id: int
    transaction_id: int
    direction: LedgerDirection
    amount: int

class LedgerEntryRead(LedgerEntryCreate):
    id: int
    created_at: datetime
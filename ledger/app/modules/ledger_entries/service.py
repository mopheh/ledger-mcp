from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.ledger_entries.models import LedgerEntry


async def create_ledger_entry(session: AsyncSession, data) -> LedgerEntry:
    """
    Create a new ledger entry in the database.

    Args:
        data (dict): A dictionary containing the ledger entry details.

    Returns:
        LedgerEntry: The created ledger entry object.
    """
    # Assuming LedgerEntry is a SQLAlchemy model
    new_entry = LedgerEntry(**data)
    session.add(new_entry)
    await session.commit()
    return new_entry
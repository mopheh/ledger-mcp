"""Idempotent seed data. Run from the `ledger/` directory: python -m app.seed"""
import asyncio

from sqlalchemy import select

from app.core.database import async_session, engine
from app.modules.accounts.models import Account, AccountType
from app.modules.users.models import User  # noqa: F401  (registers FK target)

SYSTEM_CURRENCIES = ["NGN"]  # one system account per currency


async def seed_system_accounts() -> None:
    async with async_session() as session:
        for currency in SYSTEM_CURRENCIES:
            number = f"SYSTEM-{currency}"
            existing = await session.execute(
                select(Account).where(Account.accountNumber == number)
            )
            if existing.scalars().first():
                continue
            # user_id stays NULL: the system account belongs to no user.
            session.add(
                Account(
                    accountNumber=number,
                    currency=currency,
                    accountType=AccountType.SYSTEM,
                )
            )
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_system_accounts())

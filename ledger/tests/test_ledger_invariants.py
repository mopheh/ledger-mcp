import asyncio

from sqlalchemy import case, func, select

from app.core.database import async_session
from app.modules.accounts import service
from app.modules.accounts.models import Account
from app.modules.ledger_entries.models import LedgerEntry
from app.modules.ledger_entries.schema import LedgerDirection


async def assert_ledger_balanced():
    async with async_session() as session:
        total = (await session.execute(select(func.sum(Account.balance)))).scalar()
        assert (total or 0) == 0, "balances across all accounts must net to zero"

        def entries(direction):
            return select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.direction == direction
            )

        credits = (await session.execute(entries(LedgerDirection.credit))).scalar()
        debits = (await session.execute(entries(LedgerDirection.debit))).scalar()
        assert credits == debits

        # Every transaction is exactly one debit plus one credit of equal size.
        per_tx = await session.execute(
            select(
                LedgerEntry.transaction_id,
                func.count(),
                func.sum(
                    case(
                        (LedgerEntry.direction == LedgerDirection.credit, LedgerEntry.amount),
                        else_=-LedgerEntry.amount,
                    )
                ),
            ).group_by(LedgerEntry.transaction_id)
        )
        for _, n, net in per_tx.all():
            assert n == 2 and net == 0

        # Each account's balance equals credits minus debits posted to it.
        for account in (await session.execute(select(Account))).scalars():
            rows = await session.execute(
                select(LedgerEntry.direction, func.sum(LedgerEntry.amount))
                .where(LedgerEntry.account_id == account.id)
                .group_by(LedgerEntry.direction)
            )
            posted = {d: s for d, s in rows.all()}
            expected = posted.get(LedgerDirection.credit, 0) - posted.get(LedgerDirection.debit, 0)
            assert account.balance == expected, account.accountNumber


async def test_ledger_balances_after_mixed_activity(call, alice, bob):
    (ua, a), (ub, b) = alice, bob
    await call(service.deposit, a.id, 1000, "d1", ua.id)
    await call(service.deposit, b.id, 500, "d2", ub.id)
    await call(service.transfer, a.id, b.id, 300, "t1", ua)
    await call(service.withdraw, b.id, 200, "w1", ub.id)
    await assert_ledger_balanced()


async def test_ledger_balances_under_concurrent_transfers(call, alice, bob, balance):
    (ua, a), (ub, b) = alice, bob
    await call(service.deposit, a.id, 1000, "da", ua.id)
    await call(service.deposit, b.id, 1000, "db", ub.id)
    await asyncio.gather(
        *[call(service.transfer, a.id, b.id, 10, f"ab{i}", ua) for i in range(10)],
        *[call(service.transfer, b.id, a.id, 7, f"ba{i}", ub) for i in range(10)],
    )
    assert await balance(a.id) == 1000 - 100 + 70
    assert await balance(b.id) == 1000 + 100 - 70
    await assert_ledger_balanced()


async def test_rejected_operations_leave_no_trace(call, alice, bob, balance):
    (ua, a), (_, b) = alice, bob
    await call(service.deposit, a.id, 100, "d", ua.id)
    assert (await call(service.withdraw, a.id, 101, "w", ua.id)).startswith("400")
    assert (await call(service.transfer, a.id, b.id, 101, "t", ua)).startswith("400")
    assert (await call(service.deposit, a.id, 0, "z", ua.id)).startswith("400")
    assert await balance(a.id) == 100
    await assert_ledger_balanced()

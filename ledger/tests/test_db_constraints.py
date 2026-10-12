"""The database itself must refuse what application code is trusted not to do."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.database import async_session
from app.modules.accounts import service


@pytest.fixture
async def posted(call, alice, bob):
    """Alice has deposited and transferred once, so every table has rows."""
    (ua, a), (_, b) = alice, bob
    await call(service.deposit, a.id, 1000, "d", ua.id)
    await call(service.transfer, a.id, b.id, 100, "t", ua)
    return a, b


async def execute(sql: str, **params):
    async with async_session() as session:
        await session.execute(text(sql), params)
        await session.commit()


# --- CHECK constraints -------------------------------------------------------

async def test_user_balance_cannot_go_negative(alice):
    _, acct = alice
    with pytest.raises(IntegrityError, match="ck_accounts_balance_non_negative"):
        await execute("UPDATE accounts SET balance = -1 WHERE id = :id", id=acct.id)


async def test_system_balance_may_go_negative(call, alice):
    # A deposit drives the system account negative; the constraint must allow it.
    user, acct = alice
    assert await call(service.deposit, acct.id, 500, "d", user.id) == "ok"
    async with async_session() as session:
        system = await service.get_system_account(session, "NGN")
        assert system.balance == -500


@pytest.mark.parametrize("amount", [0, -5])
async def test_transaction_amount_must_be_positive(alice, amount):
    _, acct = alice
    with pytest.raises(IntegrityError, match="ck_transactions_amount_positive"):
        await execute(
            "INSERT INTO transactions (idempotency_key, type, to_account_id, amount, created_at) "
            "VALUES ('x', 'DEPOSIT', :id, :amount, now())",
            id=acct.id,
            amount=amount,
        )


@pytest.mark.parametrize("amount", [0, -5])
async def test_ledger_entry_amount_must_be_positive(posted, amount):
    a, _ = posted
    with pytest.raises(IntegrityError, match="ck_ledger_entries_amount_positive"):
        await execute(
            "INSERT INTO ledger_entries (account_id, transaction_id, direction, amount, created_at) "
            "VALUES (:id, 1, 'credit', :amount, now())",
            id=a.id,
            amount=amount,
        )


async def test_overdraw_is_stopped_even_if_the_app_check_is_bypassed(posted):
    a, _ = posted
    with pytest.raises(IntegrityError, match="ck_accounts_balance_non_negative"):
        await execute("UPDATE accounts SET balance = balance - 10000 WHERE id = :id", id=a.id)


# --- append-only ledger ------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ledger_entries SET amount = amount + 1",
        "DELETE FROM ledger_entries",
        "UPDATE transactions SET amount = amount + 1",
        "DELETE FROM transactions",
        "TRUNCATE ledger_entries, transactions CASCADE",
        "TRUNCATE ledger_entries",
        "TRUNCATE transactions CASCADE",
    ],
)
async def test_ledger_rows_cannot_be_changed_or_removed(posted, sql):
    with pytest.raises(DBAPIError, match="append-only"):
        await execute(sql)


async def test_rejected_mutation_changes_nothing(posted, call, balance):
    a, _ = posted
    with pytest.raises(DBAPIError):
        await execute("UPDATE ledger_entries SET amount = 1")
    async with async_session() as session:
        total = (await session.execute(text("SELECT sum(amount) FROM ledger_entries"))).scalar()
    assert total == 2200  # deposit: 2 entries x 1000, transfer: 2 entries x 100
    assert await balance(a.id) == 900


async def test_normal_operations_still_work_with_triggers_on(call, alice, bob, balance):
    (ua, a), (ub, b) = alice, bob
    assert await call(service.deposit, a.id, 1000, "d", ua.id) == "ok"
    assert await call(service.transfer, a.id, b.id, 250, "t", ua) == "ok"
    assert await call(service.withdraw, b.id, 50, "w", ub.id) == "ok"
    assert (await balance(a.id), await balance(b.id)) == (750, 200)

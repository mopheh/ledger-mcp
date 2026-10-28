import asyncio

from sqlalchemy import select

from app.core.database import async_session
from app.modules.accounts import service
from app.modules.accounts.models import Transaction, TransactionType
from app.modules.ledger_entries.models import LedgerEntry
from app.modules.ledger_entries.schema import LedgerDirection
from tests.test_ledger_invariants import assert_ledger_balanced

MISMATCH = "400 Idempotency key already used with different parameters"
ALREADY_REVERSED = "409 This transaction has already been reversed"
INSUFFICIENT = "409 Insufficient funds to reverse the transaction"


async def test_reversal_mirrors_the_original(call, admin, alice, bob, funded_transfer, balance, transactions_of):
    (_, a), (_, b) = alice, bob
    assert await call(service.reverse_transaction, funded_transfer.id, "r", admin) == "ok"

    assert (await balance(a.id), await balance(b.id)) == (1000, 0)
    (reversal,) = await transactions_of(TransactionType.REVERSAL)
    assert reversal.reverse_transaction_id == funded_transfer.id
    assert (reversal.from_account_id, reversal.to_account_id) == (b.id, a.id)
    assert reversal.amount == 200
    assert reversal.initiated_by_user_id == admin.id

    async with async_session() as session:
        entries = (
            await session.execute(
                select(LedgerEntry).where(LedgerEntry.transaction_id == reversal.id)
            )
        ).scalars().all()
    assert {(e.account_id, e.direction, e.amount) for e in entries} == {
        (b.id, LedgerDirection.debit, 200),
        (a.id, LedgerDirection.credit, 200),
    }
    await assert_ledger_balanced()


async def test_second_reversal_with_new_key_is_rejected(call, admin, alice, bob, funded_transfer, balance):
    (_, a), (_, b) = alice, bob
    assert await call(service.reverse_transaction, funded_transfer.id, "r1", admin) == "ok"
    assert await call(service.reverse_transaction, funded_transfer.id, "r2", admin) == ALREADY_REVERSED
    assert (await balance(a.id), await balance(b.id)) == (1000, 0)
    await assert_ledger_balanced()


async def test_concurrent_reversals_with_different_keys_apply_once(call, admin, alice, bob, funded_transfer, balance):
    (_, a), (_, b) = alice, bob
    results = await asyncio.gather(
        *[call(service.reverse_transaction, funded_transfer.id, f"race{i}", admin) for i in range(8)]
    )
    assert sorted(results) == sorted(["ok"] + [ALREADY_REVERSED] * 7)
    assert (await balance(a.id), await balance(b.id)) == (1000, 0)
    await assert_ledger_balanced()


async def test_non_admin_cannot_reverse(call, alice, bob, funded_transfer, balance):
    (ua, a), (_, b) = alice, bob
    expected = "403 Only admin users can reverse transactions"
    assert await call(service.reverse_transaction, funded_transfer.id, "r", ua) == expected
    assert (await balance(a.id), await balance(b.id)) == (800, 200)


async def test_reversal_rejected_when_recipient_already_spent_it(call, admin, alice, bob, make_user, make_account, funded_transfer, balance):
    (_, a), (ub, b) = alice, bob
    carol = await make_account(await make_user("carol"), "ACC-CAROL")
    await call(service.transfer, b.id, carol.id, 150, "spend", ub)

    assert await call(service.reverse_transaction, funded_transfer.id, "r", admin) == INSUFFICIENT
    assert (await balance(a.id), await balance(b.id), await balance(carol.id)) == (800, 50, 150)
    await assert_ledger_balanced()


async def test_deposit_and_withdrawal_cannot_be_reversed(call, admin, alice, transactions_of):
    user, acct = alice
    await call(service.deposit, acct.id, 1000, "d", user.id)
    await call(service.withdraw, acct.id, 100, "w", user.id)
    expected = "400 Cannot reverse a deposit or withdrawal transaction"
    for kind in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL):
        (tx,) = await transactions_of(kind)
        assert await call(service.reverse_transaction, tx.id, f"r-{kind.value}", admin) == expected


async def test_reversal_cannot_be_reversed(call, admin, funded_transfer, transactions_of):
    await call(service.reverse_transaction, funded_transfer.id, "r", admin)
    (reversal,) = await transactions_of(TransactionType.REVERSAL)
    assert (
        await call(service.reverse_transaction, reversal.id, "r2", admin)
        == "400 Cannot reverse a reversal transaction"
    )


async def test_reversing_unknown_transaction_is_404(call, admin):
    assert await call(service.reverse_transaction, 9999, "r", admin) == "404 Transaction not found"


async def test_key_reused_for_a_different_original_is_rejected(call, admin, alice, bob, funded_transfer, transactions_of, balance):
    (ua, a), (_, b) = alice, bob
    # A second transfer with identical accounts and amount: only the original id differs.
    await call(service.transfer, a.id, b.id, 200, "t2", ua)
    first, second = await transactions_of(TransactionType.TRANSFER)

    assert await call(service.reverse_transaction, first.id, "r", admin) == "ok"
    assert await call(service.reverse_transaction, second.id, "r", admin) == MISMATCH
    assert (await balance(a.id), await balance(b.id)) == (800, 200)
    await assert_ledger_balanced()

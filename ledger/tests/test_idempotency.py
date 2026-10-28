import asyncio

from app.modules.accounts import service

MISMATCH = "400 Idempotency key already used with different parameters"


async def test_deposit_replay_applies_once(call, alice, balance):
    user, acct = alice
    assert await call(service.deposit, acct.id, 1000, "k", user.id) == "ok"
    assert await call(service.deposit, acct.id, 1000, "k", user.id) == "ok"
    assert await balance(acct.id) == 1000


async def test_reversal_replay_applies_once(call, admin, alice, bob, funded_transfer, balance):
    (_, a), (_, b) = alice, bob
    assert await call(service.reverse_transaction, funded_transfer.id, "r", admin) == "ok"
    assert await call(service.reverse_transaction, funded_transfer.id, "r", admin) == "ok"
    assert (await balance(a.id), await balance(b.id)) == (1000, 0)


async def test_concurrent_duplicate_reversals_apply_once(call, admin, alice, bob, funded_transfer, balance):
    (_, a), (_, b) = alice, bob
    results = await asyncio.gather(
        *[call(service.reverse_transaction, funded_transfer.id, "race", admin) for _ in range(8)]
    )
    assert set(results) == {"ok"}
    assert (await balance(a.id), await balance(b.id)) == (1000, 0)


async def test_deposit_key_reused_with_other_amount_is_rejected(call, alice, balance):
    user, acct = alice
    await call(service.deposit, acct.id, 1000, "k", user.id)
    assert await call(service.deposit, acct.id, 999, "k", user.id) == MISMATCH
    assert await balance(acct.id) == 1000


async def test_key_reused_across_operation_types_is_rejected(call, alice, balance):
    user, acct = alice
    await call(service.deposit, acct.id, 1000, "k", user.id)
    assert await call(service.withdraw, acct.id, 1000, "k", user.id) == MISMATCH
    assert await balance(acct.id) == 1000


async def test_withdraw_replay_applies_once(call, alice, balance):
    user, acct = alice
    await call(service.deposit, acct.id, 1000, "d", user.id)
    assert await call(service.withdraw, acct.id, 100, "w", user.id) == "ok"
    assert await call(service.withdraw, acct.id, 100, "w", user.id) == "ok"
    assert await balance(acct.id) == 900


async def test_transfer_replay_applies_once(call, alice, bob, balance):
    (ua, a), (_, b) = alice, bob
    await call(service.deposit, a.id, 1000, "d", ua.id)
    assert await call(service.transfer, a.id, b.id, 200, "t", ua) == "ok"
    assert await call(service.transfer, a.id, b.id, 200, "t", ua) == "ok"
    assert (await balance(a.id), await balance(b.id)) == (800, 200)


async def test_transfer_key_reused_with_other_destination_is_rejected(call, alice, bob, make_account):
    (ua, a), (ub, b) = alice, bob
    other = await make_account(ub, "ACC-BOB-2", currency="USD")
    await call(service.deposit, a.id, 1000, "d", ua.id)
    await call(service.transfer, a.id, b.id, 200, "t", ua)
    assert await call(service.transfer, a.id, other.id, 200, "t", ua) == MISMATCH


async def test_keys_are_scoped_per_user(call, alice, bob, balance):
    (ua, a), (ub, b) = alice, bob
    assert await call(service.deposit, a.id, 1000, "same", ua.id) == "ok"
    # Bob using Alice's key string is neither a replay nor a conflict.
    assert await call(service.deposit, b.id, 500, "same", ub.id) == "ok"
    assert (await balance(a.id), await balance(b.id)) == (1000, 500)


async def test_transfer_keys_are_scoped_per_user(call, alice, bob, balance):
    (ua, a), (ub, b) = alice, bob
    await call(service.deposit, a.id, 1000, "da", ua.id)
    await call(service.deposit, b.id, 1000, "db", ub.id)
    assert await call(service.transfer, a.id, b.id, 100, "t", ua) == "ok"
    assert await call(service.transfer, b.id, a.id, 50, "t", ub) == "ok"
    assert (await balance(a.id), await balance(b.id)) == (950, 1050)


async def test_concurrent_duplicate_deposits_apply_once(call, alice, balance):
    user, acct = alice
    results = await asyncio.gather(
        *[call(service.deposit, acct.id, 10, "race", user.id) for _ in range(8)]
    )
    assert set(results) == {"ok"}
    assert await balance(acct.id) == 10


async def test_concurrent_duplicate_withdrawals_apply_once(call, alice, balance):
    user, acct = alice
    await call(service.deposit, acct.id, 100, "d", user.id)
    results = await asyncio.gather(
        *[call(service.withdraw, acct.id, 10, "race", user.id) for _ in range(8)]
    )
    assert set(results) == {"ok"}
    assert await balance(acct.id) == 90


async def test_concurrent_duplicate_transfers_apply_once(call, alice, bob, balance):
    (ua, a), (_, b) = alice, bob
    await call(service.deposit, a.id, 100, "d", ua.id)
    results = await asyncio.gather(
        *[call(service.transfer, a.id, b.id, 10, "race", ua) for _ in range(8)]
    )
    assert set(results) == {"ok"}
    assert (await balance(a.id), await balance(b.id)) == (90, 10)

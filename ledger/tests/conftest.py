"""Test harness.

These tests TRUNCATE every table, so they only run against a database named in
TEST_DATABASE_URL (the name must contain "test"). They never fall back to the
DATABASE_URL in app/.env.local.

    createdb ledger_test
    TEST_DATABASE_URL=postgresql+psycopg://localhost/ledger_test pytest
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text

LEDGER_DIR = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    _db_name = urlparse(TEST_DATABASE_URL).path.lstrip("/")
    if "test" not in _db_name:
        raise pytest.UsageError(
            f"Refusing to run: TEST_DATABASE_URL database {_db_name!r} must contain 'test'."
        )
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    # Settings must still load for imports to work, but point nowhere real.
    os.environ["DATABASE_URL"] = "postgresql+psycopg://invalid/none"
os.environ["JWT_SECRET"] = "test-secret"

# Imported after the environment is pinned: app.core.config reads it at import.
from app.core.database import async_session, engine  # noqa: E402
from app.modules.accounts import service  # noqa: E402
from app.modules.accounts.models import Account, AccountType, Transaction, TransactionType  # noqa: E402
from app.modules.users.models import User  # noqa: E402


def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="set TEST_DATABASE_URL to a database whose name contains 'test'")
    for item in items:
        item.add_marker(skip)


def run_alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=LEDGER_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Rebuild the schema from scratch with the real migrations."""
    if not TEST_DATABASE_URL:
        yield
        return
    with psycopg.connect(TEST_DATABASE_URL.replace("+psycopg", ""), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    result = run_alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr
    yield


@pytest_asyncio.fixture(autouse=True)
async def clean_db(migrated_db):
    """Empty every table and seed the NGN system account before each test."""
    async with engine.begin() as conn:
        # The ledger tables reject TRUNCATE; switch their triggers off for the reset only.
        for table in ("ledger_entries", "transactions"):
            await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        await conn.execute(
            text(
                'TRUNCATE ledger_entries, transactions, api_keys, accounts, "user" '
                "RESTART IDENTITY CASCADE"
            )
        )
        for table in ("ledger_entries", "transactions"):
            await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    async with async_session() as session:
        session.add(
            Account(accountNumber="SYSTEM-NGN", currency="NGN", accountType=AccountType.SYSTEM)
        )
        await session.commit()
    yield


@pytest_asyncio.fixture
async def make_user():
    async def _make(name: str, is_admin: bool = False) -> User:
        async with async_session() as session:
            user = User(
                name=name, email=f"{name}@example.com", password_hash="x", is_admin=is_admin
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _make


@pytest_asyncio.fixture
async def make_account():
    async def _make(user: User, number: str, currency: str = "NGN") -> Account:
        async with async_session() as session:
            account = Account(
                accountNumber=number,
                currency=currency,
                accountType=AccountType.USER,
                user_id=user.id,
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

    return _make


@pytest_asyncio.fixture
async def balance():
    async def _balance(account_id: int) -> int:
        async with async_session() as session:
            return (await session.get(Account, account_id)).balance

    return _balance


@pytest_asyncio.fixture
async def call():
    """Run a service function on its own session, like one request would.

    Returns "ok" on success or "<status> <detail>" for an HTTPException.
    """

    async def _call(fn, *args) -> str:
        async with async_session() as session:
            try:
                await fn(session, *args)
                return "ok"
            except HTTPException as exc:
                return f"{exc.status_code} {exc.detail}"

    return _call


@pytest_asyncio.fixture
async def transactions_of():
    """Fetch committed transactions of one type, oldest first."""

    async def _fetch(type: TransactionType) -> list[Transaction]:
        async with async_session() as session:
            result = await session.execute(
                select(Transaction).where(Transaction.type == type).order_by(Transaction.id)
            )
            return list(result.scalars().all())

    return _fetch


@pytest_asyncio.fixture
async def funded_transfer(call, alice, bob, transactions_of):
    """Alice deposits 1000, then transfers 200 to Bob. Returns the transfer row."""
    (ua, a), (_, b) = alice, bob
    await call(service.deposit, a.id, 1000, "d", ua.id)
    await call(service.transfer, a.id, b.id, 200, "t", ua)
    return (await transactions_of(TransactionType.TRANSFER))[0]


@pytest_asyncio.fixture
async def admin(make_user):
    return await make_user("admin", is_admin=True)


@pytest_asyncio.fixture
async def alice(make_user, make_account):
    user = await make_user("alice")
    return user, await make_account(user, "ACC-ALICE")


@pytest_asyncio.fixture
async def bob(make_user, make_account):
    user = await make_user("bob")
    return user, await make_account(user, "ACC-BOB")

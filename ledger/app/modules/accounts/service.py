from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.models import Account, AccountType, Transaction, TransactionType
from app.modules.accounts.schemas import AccountCreate
from app.modules.users.models import User
from app.modules.ledger_entries.models import LedgerEntry
from app.modules.ledger_entries.schema import LedgerDirection

async def check_balance(session: AsyncSession, account_id: int, auth_user: User) -> int:
    if account_id is None:
        # Only unambiguous when the user has exactly one account.
        result = await session.execute(
            select(Account.id).where(Account.user_id == auth_user.id).limit(2)
        )
        ids = list(result.scalars().all())
        if not ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No account associated with this user")
        if len(ids) > 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Multiple accounts found; specify account_id",
            )
        account_id = ids[0]
    account = await get_account(session, account_id, auth_user)
    return account.balance


async def create_account(session: AsyncSession, data: AccountCreate, auth_user: User) -> Account:
    existing = await get_account_by_number(session, data.accountNumber)
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Account number already exists"
        )

    account = Account(**data.model_dump(), user_id=auth_user.id)
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account

async def get_system_account(session: AsyncSession, currency: str) -> Account:
    results = await session.execute(
        select(Account).where(
            Account.accountType == AccountType.SYSTEM, Account.currency == currency
        )
    )
    result = results.scalars().first()
    if not result:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No system account found for currency {currency}",
        )
    return result


async def get_account(session: AsyncSession, account_id: int, auth_user: User | None = None) -> Account:
    account = await session.get(Account, account_id)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    
    if auth_user is not None and account.user_id != auth_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    if account.accountType == AccountType.SYSTEM and auth_user is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


async def get_account_by_number(
    session: AsyncSession, account_number: str
) -> Account | None:
    result = await session.execute(
        select(Account).where(Account.accountNumber == account_number)
    )
    return result.scalars().first()


async def list_accounts(session: AsyncSession, auth_user: User) -> list[Account]:
    result = await session.execute(
        select(Account).where(Account.user_id == auth_user.id)
    )
    return list(result.scalars().all())


async def deposit(session: AsyncSession, account_id: int, amount: int) -> Account:
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Deposit amount must be positive"
        )

    account = await lock_accounts(session, account_id)
    if account.accountType == AccountType.SYSTEM:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot deposit into a system account"
        )
    system_account = await get_system_account(session, account.currency)
    system_locked = await lock_accounts(session, system_account.id)
    account.balance += amount
    system_locked.balance -= amount
    session.add(account)
    transaction = Transaction(
                idempotency_key=str(uuid4()),
                type=TransactionType.DEPOSIT,
                to_account_id=account_id,
                amount=amount,
            )
    session.add(
        transaction
    )
    await session.flush()  # Ensure transaction.id is populated before creating ledger entries
    session.add(
        LedgerEntry(
            account_id=system_locked.id,
            transaction_id=transaction.id,
            direction=LedgerDirection.debit,
            amount=amount,
        )
    )
    session.add(
        LedgerEntry(
            account_id=account.id,
            transaction_id=transaction.id,
            direction=LedgerDirection.credit,
            amount=amount,
        )
    )
    await session.commit()
    await session.refresh(account)
    return account


async def withdraw(session: AsyncSession, account_id: int, amount: int) -> Account:
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Withdrawal amount must be positive"
        )

    account = await lock_accounts(session, account_id)
    if account.balance < amount:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Insufficient funds")
    if account.accountType == AccountType.SYSTEM:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot withdraw from a system account"
        )
    system_account = await get_system_account(session, account.currency)
    system_locked = await lock_accounts(session, system_account.id)
    account.balance -= amount
    system_locked.balance += amount
    session.add(account)
    transaction = Transaction(
            idempotency_key=str(uuid4()),
            type=TransactionType.WITHDRAWAL,
            from_account_id=account_id,
            amount=amount,
        )
    session.add(
        transaction
    )
    await session.flush()  # Ensure transaction.id is populated before creating ledger entries
    session.add(
        LedgerEntry(
            account_id=account.id,
            transaction_id=transaction.id,
            direction=LedgerDirection.debit,
            amount=amount,
        )
    )
    session.add(
        LedgerEntry(
            account_id=system_locked.id,
            transaction_id=transaction.id,
            direction=LedgerDirection.credit,
            amount=amount,
        )
    )
    await session.commit()
    await session.refresh(account)
    return account


async def lock_accounts(session: AsyncSession, account_id: int) -> Account:

    account = await session.get(Account, account_id, with_for_update=True)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account

async def get_transaction_by_idempotency_key(session: AsyncSession, idempotency_key: str) -> Transaction:
    result = await session.execute(
        select(Transaction).where(Transaction.idempotency_key == idempotency_key)
    )
    transaction = result.scalars().first()
    if not transaction:
        return None
    return transaction

async def transfer(session: AsyncSession, from_account_id: int, to_account_id: int, amount: int, idempotency_key: str, auth_user: User) -> Transaction:

    # Raises 404 if the source account doesn't exist or isn't the caller's.
    await get_account(session, from_account_id, auth_user)
    if from_account_id == to_account_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot transfer to the same account"
        )


    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Transfer amount must be positive"
        )


    existing = await get_transaction_by_idempotency_key(session, idempotency_key)
    if existing: 
        if existing.amount == amount and existing.from_account_id == from_account_id and existing.to_account_id == to_account_id and existing.type == TransactionType.TRANSFER:
            return existing
        else: 
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Idempotency key already used with different parameters")
    
    firstId, secondId = sorted([from_account_id, to_account_id])

    locked = {firstId: await lock_accounts(session, firstId), secondId: await lock_accounts(session, secondId)}
    from_account = locked[from_account_id]
    to_account = locked[to_account_id]
    if from_account.accountType == AccountType.SYSTEM or to_account.accountType == AccountType.SYSTEM:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot transfer to or from a system account"
        )

    if from_account.currency != to_account.currency:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot transfer between accounts with different currencies",
        )

    if from_account.balance < amount:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Insufficient funds")

    from_account.balance -= amount
    to_account.balance += amount



    record = Transaction(
        idempotency_key=idempotency_key,
        type=TransactionType.TRANSFER,
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        amount=amount,
        initiated_by_user_id=auth_user.id,
    )

    session.add(from_account)
    session.add(to_account)
    
   

    try:
        session.add(record)
        await session.flush()  # Ensure record.id is populated before creating ledger entries
        session.add(
                LedgerEntry(
                    account_id=from_account.id,
                    transaction_id=record.id,
                    direction=LedgerDirection.debit,
                    amount=amount,
                )
            )
        session.add(
                LedgerEntry(
                    account_id=to_account.id,
                    transaction_id=record.id,
                    direction=LedgerDirection.credit,
                    amount=amount,
                )
            )
        await session.commit()
    except IntegrityError:
        
        await session.rollback()
        existing = await get_transaction_by_idempotency_key(session, idempotency_key)
        if existing:
            return existing
        raise

    await session.refresh(record)
    return record


async def get_transaction(session: AsyncSession, transaction_id: int) -> Transaction:
    transaction = await session.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return transaction


async def list_transactions_for_account(
    session: AsyncSession, account_id: int
) -> list[Transaction]:
    result = await session.execute(
        select(Transaction)
        .where(
            or_(
                Transaction.from_account_id == account_id,
                Transaction.to_account_id == account_id,
            )
        )
        .order_by(Transaction.created_at)
    )
    return list(result.scalars().all())
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


async def deposit(
    session: AsyncSession,
    account_id: int,
    amount: int,
    idempotency_key: str,
    user_id: int,
) -> Account:
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Deposit amount must be positive"
        )

    existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
    if existing:
        _ensure_same_request(existing, TransactionType.DEPOSIT, None, account_id, amount)
        return await session.get(Account, account_id)

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
        idempotency_key=idempotency_key,
        type=TransactionType.DEPOSIT,
        to_account_id=account_id,
        amount=amount,
        initiated_by_user_id=user_id,
    )
    try:
        session.add(transaction)
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
    except IntegrityError:
        # A concurrent request with the same key won the race; replay its result.
        await session.rollback()
        existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
        if existing:
            _ensure_same_request(existing, TransactionType.DEPOSIT, None, account_id, amount)
            return await session.get(Account, account_id)
        raise
    await session.refresh(account)
    return account


async def withdraw(
    session: AsyncSession,
    account_id: int,
    amount: int,
    idempotency_key: str,
    user_id: int,
) -> Account:
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Withdrawal amount must be positive"
        )

    existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
    if existing:
        _ensure_same_request(existing, TransactionType.WITHDRAWAL, account_id, None, amount)
        return await session.get(Account, account_id)

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
        idempotency_key=idempotency_key,
        type=TransactionType.WITHDRAWAL,
        from_account_id=account_id,
        amount=amount,
        initiated_by_user_id=user_id,
    )
    try:
        session.add(transaction)
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
    except IntegrityError:
        # A concurrent request with the same key won the race; replay its result.
        await session.rollback()
        existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
        if existing:
            _ensure_same_request(existing, TransactionType.WITHDRAWAL, account_id, None, amount)
            return await session.get(Account, account_id)
        raise
    await session.refresh(account)
    return account


async def lock_accounts(session: AsyncSession, account_id: int) -> Account:

    account = await session.get(Account, account_id, with_for_update=True)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account

async def get_transaction_by_idempotency_key(
    session: AsyncSession, user_id: int, idempotency_key: str
) -> Transaction | None:
    """Idempotency keys are scoped to the user who initiated the transaction."""
    result = await session.execute(
        select(Transaction).where(
            Transaction.initiated_by_user_id == user_id,
            Transaction.idempotency_key == idempotency_key,
        )
    )
    return result.scalars().first()


def _ensure_same_request(
    existing: Transaction,
    type: TransactionType,
    from_account_id: int | None,
    to_account_id: int | None,
    amount: int,
    reverse_transaction_id: int | None = None,
) -> None:
    """A reused key is only a retry if it describes the same operation."""
    if (
        existing.type != type
        or existing.from_account_id != from_account_id
        or existing.to_account_id != to_account_id
        or existing.amount != amount
        or existing.reverse_transaction_id != reverse_transaction_id
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Idempotency key already used with different parameters",
        )


async def transfer(session: AsyncSession, from_account_id: int, to_account_id: int, amount: int, idempotency_key: str, auth_user: User) -> Transaction:

    # Read now: rollback expires auth_user, and async can't lazy-load it afterwards.
    user_id = auth_user.id
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


    existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
    if existing:
        _ensure_same_request(existing, TransactionType.TRANSFER, from_account_id, to_account_id, amount)
        return existing
    
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
        initiated_by_user_id=user_id,
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
        existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
        if existing:
            _ensure_same_request(existing, TransactionType.TRANSFER, from_account_id, to_account_id, amount)
            return existing
        raise

    await session.refresh(record)
    return record


async def reverse_transaction(session: AsyncSession, transaction_id: int, idempotency_key: str, auth_user: User) -> Transaction:
    if not auth_user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admin users can reverse transactions"
        )
    # Read now: rollback expires every loaded object, and async can't lazy-load them afterwards.
    user_id = auth_user.id
    original = await get_transaction(session, transaction_id)
    original_id = original.id
    original_type = original.type
    original_from_id = original.from_account_id
    original_to_id = original.to_account_id
    amount = original.amount

    existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
    if existing:
        _ensure_same_request(existing, TransactionType.REVERSAL, original_to_id, original_from_id, amount, original_id)
        return existing
    if original_type == TransactionType.REVERSAL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot reverse a reversal transaction"
        )
    if original_type in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot reverse a deposit or withdrawal transaction"
        )

    # Lock the accounts involved in the original transaction
    firstId, secondId = sorted([original_from_id, original_to_id])
    locked = {firstId: await lock_accounts(session, firstId), secondId: await lock_accounts(session, secondId)}
    from_account = locked[original_from_id]
    to_account = locked[original_to_id]

    # Both checks below run after the locks: concurrent reversals of the same transaction
    # queue on them. A retry that waited behind the winner replays its result, not a 409.
    existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
    if existing:
        _ensure_same_request(existing, TransactionType.REVERSAL, original_to_id, original_from_id, amount, original_id)
        return existing
    if await _find_reversal_id(session, original_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This transaction has already been reversed"
        )

    if to_account.balance < amount:
        raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient funds to reverse the transaction")

    # Perform the reversal
    to_account.balance -= amount
    from_account.balance += amount

    reversal_record = Transaction(
        idempotency_key=idempotency_key,
        type=TransactionType.REVERSAL,
        from_account_id=original_to_id,
        to_account_id=original_from_id,
        amount=amount,
        initiated_by_user_id=user_id,
        reverse_transaction_id=original_id,
    )

    session.add(from_account)
    session.add(to_account)

    try:
        session.add(reversal_record)
        await session.flush()  # Ensure reversal_record.id is populated before creating ledger entries
        session.add(
                LedgerEntry(
                    account_id=to_account.id,
                    transaction_id=reversal_record.id,
                    direction=LedgerDirection.debit,
                    amount=amount,
                )
            )
        session.add(
                LedgerEntry(
                    account_id=from_account.id,
                    transaction_id=reversal_record.id,
                    direction=LedgerDirection.credit,
                    amount=amount,
                )
            )
        await session.commit()
        await session.refresh(reversal_record)
        return reversal_record
    except IntegrityError:
        await session.rollback()
        existing = await get_transaction_by_idempotency_key(session, user_id, idempotency_key)
        if existing:
            _ensure_same_request(existing, TransactionType.REVERSAL, original_to_id, original_from_id, amount, original_id)
            return existing
        if await _find_reversal_id(session, original_id) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This transaction has already been reversed"
            )
        raise


async def _find_reversal_id(session: AsyncSession, original_id: int) -> int | None:
    result = await session.execute(
        select(Transaction.id).where(Transaction.reverse_transaction_id == original_id)
    )
    return result.scalars().first()


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
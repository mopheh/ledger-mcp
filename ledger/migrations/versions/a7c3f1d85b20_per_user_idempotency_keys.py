"""per-user idempotency keys

Revision ID: a7c3f1d85b20
Revises: d2007331c93e
Create Date: 2026-10-12 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7c3f1d85b20'
down_revision: Union[str, Sequence[str], None] = 'd2007331c93e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Scope idempotency keys to the user who initiated the transaction.

    Deposits and withdrawals used to be saved without `initiated_by_user_id`;
    backfill it from the owner of the account they touched, so the new
    (user, key) uniqueness covers them too.
    """
    op.execute(
        """
        UPDATE transactions t
        SET initiated_by_user_id = a.user_id
        FROM accounts a
        WHERE t.initiated_by_user_id IS NULL
          AND a.id = COALESCE(t.to_account_id, t.from_account_id)
        """
    )
    op.drop_index(op.f('ix_transactions_idempotency_key'), table_name='transactions')
    op.create_index(op.f('ix_transactions_idempotency_key'), 'transactions', ['idempotency_key'], unique=False)
    op.create_unique_constraint(
        'uq_transactions_user_idempotency_key',
        'transactions',
        ['initiated_by_user_id', 'idempotency_key'],
    )


def downgrade() -> None:
    """Restore global uniqueness. Fails if two users have since reused a key."""
    op.drop_constraint('uq_transactions_user_idempotency_key', 'transactions', type_='unique')
    op.drop_index(op.f('ix_transactions_idempotency_key'), table_name='transactions')
    op.create_index(op.f('ix_transactions_idempotency_key'), 'transactions', ['idempotency_key'], unique=True)

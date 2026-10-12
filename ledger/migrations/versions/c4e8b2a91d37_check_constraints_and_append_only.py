"""check constraints and append-only ledger

Revision ID: c4e8b2a91d37
Revises: a7c3f1d85b20
Create Date: 2026-10-12 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4e8b2a91d37'
down_revision: Union[str, Sequence[str], None] = 'a7c3f1d85b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = ('ledger_entries', 'transactions')


def upgrade() -> None:
    """Enforce money invariants in the database, not just in application code.

    Fails (and rolls back) if existing rows already violate a constraint, e.g.
    a negative user balance. Fix the data first rather than weakening the check.
    """
    # System accounts hold the counter-balance of every user deposit, so they
    # are the only accounts allowed to go negative.
    op.create_check_constraint(
        'ck_accounts_balance_non_negative',
        'accounts',
        """balance >= 0 OR "accountType" = 'system'""",
    )
    op.create_check_constraint('ck_transactions_amount_positive', 'transactions', 'amount > 0')
    op.create_check_constraint('ck_ledger_entries_amount_positive', 'ledger_entries', 'amount > 0')

    op.execute(
        """
        CREATE FUNCTION forbid_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% on % is not allowed: the ledger is append-only. Post a reversing transaction instead.',
                TG_OP, TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION forbid_ledger_mutation()
            """
        )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION forbid_ledger_mutation()")
    op.drop_constraint('ck_ledger_entries_amount_positive', 'ledger_entries', type_='check')
    op.drop_constraint('ck_transactions_amount_positive', 'transactions', type_='check')
    op.drop_constraint('ck_accounts_balance_non_negative', 'accounts', type_='check')

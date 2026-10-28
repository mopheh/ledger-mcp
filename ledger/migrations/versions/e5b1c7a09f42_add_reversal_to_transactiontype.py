"""add reversal to transactiontype enum

Revision ID: e5b1c7a09f42
Revises: 3f48a864217d
Create Date: 2026-10-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5b1c7a09f42'
down_revision: Union[str, Sequence[str], None] = '3f48a864217d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # transactions.type is a native Postgres enum; adding a member to the Python
    # enum does nothing until the database type learns about it too.
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'REVERSAL'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum, so this is intentionally a no-op.
    # An unused extra value is harmless.
    pass

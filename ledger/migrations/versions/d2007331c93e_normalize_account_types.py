"""normalize account types

Revision ID: d2007331c93e
Revises: 41eca5d2f39a
Create Date: 2026-10-10 13:49:32.054016

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd2007331c93e'
down_revision: Union[str, Sequence[str], None] = '41eca5d2f39a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """accountType is now an enum stored as 'user' / 'system'; coerce stray free-text values."""
    op.execute("""UPDATE accounts SET "accountType" = 'user' WHERE "accountType" NOT IN ('user', 'system')""")


def downgrade() -> None:
    """Data-only change; the original free-text values are not recoverable."""
    pass

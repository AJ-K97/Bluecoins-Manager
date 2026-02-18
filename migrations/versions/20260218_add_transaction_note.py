"""add_transaction_note

Revision ID: 20260218_tx_note
Revises: 20260217_mka
Create Date: 2026-02-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260218_tx_note"
down_revision: Union[str, Sequence[str], None] = "20260217_mka"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "note" in columns:
        return

    op.execute(sa.text("SET LOCAL statement_timeout = 0"))
    op.add_column("transactions", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "note" not in columns:
        return

    op.execute(sa.text("SET LOCAL statement_timeout = 0"))
    op.drop_column("transactions", "note")

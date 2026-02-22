"""add_operation_logs

Revision ID: 20260221_op_logs
Revises: 20260218_tx_note
Create Date: 2026-02-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260221_op_logs"
down_revision: Union[str, Sequence[str], None] = "20260218_tx_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "operation_logs"
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)} if inspector.has_table(table_name) else set()

    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("operation_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("undone_at", sa.DateTime(), nullable=True),
        )
        existing_indexes = set()

    if "ix_operation_logs_id" not in existing_indexes:
        op.create_index("ix_operation_logs_id", table_name, ["id"])
    if "ix_operation_logs_operation_type" not in existing_indexes:
        op.create_index("ix_operation_logs_operation_type", table_name, ["operation_type"])
    if "ix_operation_logs_created_at" not in existing_indexes:
        op.create_index("ix_operation_logs_created_at", table_name, ["created_at"])
    if "ix_operation_logs_undone_at" not in existing_indexes:
        op.create_index("ix_operation_logs_undone_at", table_name, ["undone_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "operation_logs"
    if not inspector.has_table(table_name):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if "ix_operation_logs_undone_at" in existing_indexes:
        op.drop_index("ix_operation_logs_undone_at", table_name=table_name)
    if "ix_operation_logs_created_at" in existing_indexes:
        op.drop_index("ix_operation_logs_created_at", table_name=table_name)
    if "ix_operation_logs_operation_type" in existing_indexes:
        op.drop_index("ix_operation_logs_operation_type", table_name=table_name)
    if "ix_operation_logs_id" in existing_indexes:
        op.drop_index("ix_operation_logs_id", table_name=table_name)
    op.drop_table(table_name)

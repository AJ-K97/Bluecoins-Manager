"""add_merchant_keyword_aliases

Revision ID: 20260217_mka
Revises: e5822cf44049
Create Date: 2026-02-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260217_mka"
down_revision: Union[str, Sequence[str], None] = "e5822cf44049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "merchant_keyword_aliases"
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)} if inspector.has_table(table_name) else set()

    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("normalized_phrase", sa.String(), nullable=False),
            sa.Column("canonical_keyword", sa.String(), nullable=False),
            sa.Column("support_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("verified_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
        )
        existing_indexes = set()

    if "ix_merchant_keyword_aliases_id" not in existing_indexes:
        op.create_index("ix_merchant_keyword_aliases_id", table_name, ["id"])
    if "ix_merchant_keyword_aliases_normalized_phrase" not in existing_indexes:
        op.create_index(
            "ix_merchant_keyword_aliases_normalized_phrase",
            table_name,
            ["normalized_phrase"],
        )
    if "ix_merchant_keyword_aliases_canonical_keyword" not in existing_indexes:
        op.create_index(
            "ix_merchant_keyword_aliases_canonical_keyword",
            table_name,
            ["canonical_keyword"],
        )
    if "ix_merchant_keyword_aliases_last_seen_at" not in existing_indexes:
        op.create_index(
            "ix_merchant_keyword_aliases_last_seen_at",
            table_name,
            ["last_seen_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "merchant_keyword_aliases"
    if not inspector.has_table(table_name):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if "ix_merchant_keyword_aliases_last_seen_at" in existing_indexes:
        op.drop_index("ix_merchant_keyword_aliases_last_seen_at", table_name=table_name)
    if "ix_merchant_keyword_aliases_canonical_keyword" in existing_indexes:
        op.drop_index("ix_merchant_keyword_aliases_canonical_keyword", table_name=table_name)
    if "ix_merchant_keyword_aliases_normalized_phrase" in existing_indexes:
        op.drop_index("ix_merchant_keyword_aliases_normalized_phrase", table_name=table_name)
    if "ix_merchant_keyword_aliases_id" in existing_indexes:
        op.drop_index("ix_merchant_keyword_aliases_id", table_name=table_name)
    op.drop_table(table_name)

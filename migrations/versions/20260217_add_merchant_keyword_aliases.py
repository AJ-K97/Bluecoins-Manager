"""add_merchant_keyword_aliases

Revision ID: 20260217_add_merchant_keyword_aliases
Revises: e5822cf44049
Create Date: 2026-02-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260217_add_merchant_keyword_aliases"
down_revision: Union[str, Sequence[str], None] = "e5822cf44049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_keyword_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("normalized_phrase", sa.String(), nullable=False),
        sa.Column("canonical_keyword", sa.String(), nullable=False),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_merchant_keyword_aliases_id", "merchant_keyword_aliases", ["id"])
    op.create_index(
        "ix_merchant_keyword_aliases_normalized_phrase",
        "merchant_keyword_aliases",
        ["normalized_phrase"],
    )
    op.create_index(
        "ix_merchant_keyword_aliases_canonical_keyword",
        "merchant_keyword_aliases",
        ["canonical_keyword"],
    )
    op.create_index(
        "ix_merchant_keyword_aliases_last_seen_at",
        "merchant_keyword_aliases",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_keyword_aliases_last_seen_at", table_name="merchant_keyword_aliases")
    op.drop_index("ix_merchant_keyword_aliases_canonical_keyword", table_name="merchant_keyword_aliases")
    op.drop_index("ix_merchant_keyword_aliases_normalized_phrase", table_name="merchant_keyword_aliases")
    op.drop_index("ix_merchant_keyword_aliases_id", table_name="merchant_keyword_aliases")
    op.drop_table("merchant_keyword_aliases")

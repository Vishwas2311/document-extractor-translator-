"""Persist reviewer decisions for reconstructed table structure.

Revision ID: 0007_financial_structure_reviews
Revises: 0006_financial_reviews
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_financial_structure_reviews"
down_revision = "0006_financial_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("financial_reviews") as batch:
        batch.add_column(
            sa.Column(
                "structure_decisions",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_reviews") as batch:
        batch.drop_column("structure_decisions")

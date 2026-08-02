"""Add PRD-readiness columns for data class and processing profile.

Revision ID: 0003_prd_readiness
Revises: 0002_drop_translation_batches
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_prd_readiness"
down_revision = "0002_drop_translation_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column("data_class", sa.String(length=32), nullable=False, server_default="synthetic")
        )
        batch.add_column(
            sa.Column(
                "processing_profile",
                sa.String(length=64),
                nullable=False,
                server_default="GENAI_PSEUDONYMIZED",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("processing_profile")
        batch.drop_column("data_class")

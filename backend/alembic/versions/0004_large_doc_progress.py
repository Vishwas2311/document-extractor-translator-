"""Add progressive large-document progress columns.

Revision ID: 0004_large_doc_progress
Revises: 0003_prd_readiness
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_large_doc_progress"
down_revision = "0003_prd_readiness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("pages_ready", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("translation_batches_done", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("translation_batches_total", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("translation_batches_total")
        batch.drop_column("translation_batches_done")
        batch.drop_column("pages_ready")

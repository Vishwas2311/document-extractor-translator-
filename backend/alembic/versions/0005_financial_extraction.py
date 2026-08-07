"""Add financial extraction summary fields.

Revision ID: 0005_financial_extraction
Revises: 0004_large_doc_progress
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_financial_extraction"
down_revision = "0004_large_doc_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column(
                "financial_extraction_mode",
                sa.String(length=32),
                nullable=False,
                server_default="post_extract",
            )
        )
        batch.add_column(sa.Column("financial_page_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("uncertain_page_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("financial_table_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("financial_issue_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("financial_issue_count")
        batch.drop_column("financial_table_count")
        batch.drop_column("uncertain_page_count")
        batch.drop_column("financial_page_count")
        batch.drop_column("financial_extraction_mode")

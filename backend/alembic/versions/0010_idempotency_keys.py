"""Add idempotency_keys table for request idempotency.

Revision ID: 0010_idempotency_keys
Revises: 0009_review_status_constraints
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_idempotency_keys"
down_revision = "0009_review_status_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=512), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", name="uq_idempotency_scope"),
    )
    op.create_index(
        "ix_idempotency_keys_scope", "idempotency_keys", ["scope"], unique=False
    )
    op.create_index(
        "ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_scope", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

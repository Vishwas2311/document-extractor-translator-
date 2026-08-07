"""PRD ownership, translation review, and audit tables.

Revision ID: 0008_prd_authorization_reviews
Revises: 0007_financial_structure_reviews
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_prd_authorization_reviews"
down_revision = "0007_financial_structure_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column("organization_id", sa.String(length=64), nullable=False, server_default="org-local")
        )
        batch.add_column(
            sa.Column(
                "owner_subject",
                sa.String(length=255),
                nullable=False,
                server_default="local-api-token",
            )
        )
        batch.add_column(sa.Column("assigned_reviewer_subject", sa.String(length=255), nullable=True))
        batch.add_column(
            sa.Column(
                "assignment_status",
                sa.String(length=32),
                nullable=False,
                server_default="unassigned",
            )
        )
        batch.add_column(
            sa.Column(
                "document_review_status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            )
        )
        batch.add_column(sa.Column("translation_result_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("translation_review_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("translation_reviewed_by", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("translation_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_documents_organization_id", ["organization_id"])
        batch.create_index("ix_documents_owner_subject", ["owner_subject"])
        batch.create_index("ix_documents_assigned_reviewer_subject", ["assigned_reviewer_subject"])
        batch.create_index("ix_documents_document_review_status", ["document_review_status"])

    op.create_table(
        "translation_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_subject", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("corrections", sa.JSON(), nullable=False),
        sa.Column("processing_version", sa.String(length=64), nullable=False),
        sa.Column("result_schema_version", sa.String(length=64), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_translation_reviews_document_id", "translation_reviews", ["document_id"])
    op.create_index("ix_translation_reviews_decision", "translation_reviews", ["decision"])
    op.create_index("ix_translation_reviews_result_sha256", "translation_reviews", ["result_sha256"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index("ix_audit_events_actor_subject", "audit_events", ["actor_subject"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_resource_id", "audit_events", ["resource_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_subject", table_name="audit_events")
    op.drop_index("ix_audit_events_organization_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_translation_reviews_result_sha256", table_name="translation_reviews")
    op.drop_index("ix_translation_reviews_decision", table_name="translation_reviews")
    op.drop_index("ix_translation_reviews_document_id", table_name="translation_reviews")
    op.drop_table("translation_reviews")

    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_document_review_status")
        batch.drop_index("ix_documents_assigned_reviewer_subject")
        batch.drop_index("ix_documents_owner_subject")
        batch.drop_index("ix_documents_organization_id")
        batch.drop_column("translation_reviewed_at")
        batch.drop_column("translation_reviewed_by")
        batch.drop_column("translation_review_status")
        batch.drop_column("translation_result_sha256")
        batch.drop_column("document_review_status")
        batch.drop_column("assignment_status")
        batch.drop_column("assigned_reviewer_subject")
        batch.drop_column("owner_subject")
        batch.drop_column("organization_id")

"""QR codes + high-load indexes for all critical queries.

Revision ID: 003
Revises: 002
Create Date: 2026-01-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── QR codes table ────────────────────────────────────────────────────────
    op.create_table(
        "qr_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("image_data", BYTEA(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("payment_details_snapshot", sa.Text(), nullable=True),
        sa.Column("telegram_file_id", sa.String(512), nullable=True),
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tariff_id"),
    )
    op.create_index("ix_qr_codes_tariff_id", "qr_codes", ["tariff_id"])

    # ─── High-load indexes for access checks ───────────────────────────────────
    # user_access: most critical path — called on EVERY message
    op.create_index(
        "ix_user_access_group_user_active",
        "user_access",
        ["group_id", "user_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "ix_user_access_expires",
        "user_access",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL AND is_active = true"),
    )
    op.create_index(
        "ix_user_access_user_id",
        "user_access",
        ["user_id"],
    )

    # payments: approval queue
    op.create_index(
        "ix_payments_status_group",
        "payments",
        ["status", "group_id"],
    )
    op.create_index(
        "ix_payments_user_id",
        "payments",
        ["user_id"],
    )
    op.create_index(
        "ix_payments_created_at",
        "payments",
        ["created_at"],
    )

    # tariffs: group lookup
    op.create_index(
        "ix_tariffs_group_active",
        "tariffs",
        ["group_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # users: telegram_id lookup (start/registration)
    op.create_index(
        "ix_users_telegram_id",
        "users",
        ["telegram_id"],
        unique=True,
        postgresql_where=sa.text("telegram_id IS NOT NULL"),
    )
    op.create_index(
        "ix_users_username",
        "users",
        ["username"],
        postgresql_where=sa.text("username IS NOT NULL"),
    )

    # referral codes: lookup by code
    op.create_index(
        "ix_referral_codes_code",
        "referral_codes",
        ["code"],
        unique=True,
    )

    # groups: owner lookup
    op.create_index(
        "ix_groups_owner_id",
        "groups",
        ["owner_id"],
    )
    op.create_index(
        "ix_groups_access_control",
        "groups",
        ["access_control_enabled", "is_active"],
        postgresql_where=sa.text("access_control_enabled = true AND is_active = true"),
    )

    # scheduled_posts: scheduler pickup
    op.create_index(
        "ix_scheduled_posts_scheduled_at",
        "scheduled_posts",
        ["scheduled_at"],
        postgresql_where=sa.text("is_sent = false"),
    )

    # ─── PostgreSQL tuning hints (comments) ────────────────────────────────────
    op.execute("""
        COMMENT ON INDEX ix_user_access_group_user_active IS
          'Primary access check index — covers O(1) cache-miss DB fallback';
        COMMENT ON INDEX ix_payments_status_group IS
          'Payment queue lookup — owner panel pending payments list';
    """)


def downgrade() -> None:
    op.drop_table("qr_codes")

    for idx in [
        "ix_user_access_group_user_active",
        "ix_user_access_expires",
        "ix_user_access_user_id",
        "ix_payments_status_group",
        "ix_payments_user_id",
        "ix_payments_created_at",
        "ix_tariffs_group_active",
        "ix_users_telegram_id",
        "ix_users_username",
        "ix_referral_codes_code",
        "ix_groups_owner_id",
        "ix_groups_access_control",
        "ix_scheduled_posts_scheduled_at",
    ]:
        try:
            op.drop_index(idx)
        except Exception:
            pass

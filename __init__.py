"""Full access control system

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add columns to users ---
    op.add_column("users", sa.Column("referral_code", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("referred_by", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("messages_deleted", sa.Integer(), nullable=False, server_default="0"))
    op.create_unique_constraint("uq_users_referral_code", "users", ["referral_code"])
    op.create_index("ix_users_referral_code", "users", ["referral_code"])

    # --- Add columns to groups ---
    op.add_column("groups", sa.Column("access_control_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("groups", sa.Column("delete_unauthorized", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("groups", sa.Column("flood_mute_duration", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("groups", sa.Column("notification_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("groups", sa.Column("payment_details", sa.Text(), nullable=True))

    # --- tariffs ---
    op.create_table(
        "tariffs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("is_lifetime", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="RUB"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_details", sa.Text(), nullable=True),
        sa.Column("qr_code_file_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tariffs_group_id", "tariffs", ["group_id"])

    # --- payments ---
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("receipt_file_id", sa.String(512), nullable=True),
        sa.Column("receipt_type", sa.String(20), nullable=True),
        sa.Column("user_comment", sa.Text(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referral_code", sa.String(50), nullable=True),
        sa.Column("access_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_group_id", "payments", ["group_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    # --- user_access ---
    op.create_table(
        "user_access",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_lifetime", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_access_user_id", "user_access", ["user_id"])
    op.create_index("ix_user_access_group_id", "user_access", ["group_id"])
    op.create_index("ix_user_access_is_active", "user_access", ["is_active"])
    op.create_index("ix_user_access_expires_at", "user_access", ["expires_at"])

    # --- referrals ---
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("referrer_id", sa.BigInteger(), nullable=False),
        sa.Column("referred_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("bonus_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_rewarded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referred_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("referred_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_index("ix_referrals_code", "referrals", ["code"])

    # --- referral_codes ---
    op.create_table(
        "referral_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("total_referrals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bonus_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("code"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referral_codes_code", "referral_codes", ["code"])

    # Remove old subscriptions if you want (optional – keep for backwards compat)


def downgrade() -> None:
    op.drop_table("referral_codes")
    op.drop_table("referrals")
    op.drop_table("user_access")
    op.drop_table("payments")
    op.drop_table("tariffs")
    op.drop_column("groups", "payment_details")
    op.drop_column("groups", "notification_chat_id")
    op.drop_column("groups", "flood_mute_duration")
    op.drop_column("groups", "delete_unauthorized")
    op.drop_column("groups", "access_control_enabled")
    op.drop_index("ix_users_referral_code", "users")
    op.drop_column("users", "messages_deleted")
    op.drop_column("users", "referred_by")
    op.drop_column("users", "referral_code")

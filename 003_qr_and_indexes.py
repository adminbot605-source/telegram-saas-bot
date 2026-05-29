"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(64), nullable=True),
        sa.Column('first_name', sa.String(255), nullable=False),
        sa.Column('last_name', sa.String(255), nullable=True),
        sa.Column('language_code', sa.String(10), nullable=True),
        sa.Column('is_bot', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('total_groups', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_username', 'users', ['username'])

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('plan', sa.String(20), nullable=False, server_default='free'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payment_id', sa.String(255), nullable=True),
        sa.Column('amount_paid', sa.Numeric(10, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_subscriptions_user_id', 'subscriptions', ['user_id'])

    op.create_table(
        'groups',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('owner_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('username', sa.String(64), nullable=True),
        sa.Column('chat_type', sa.String(20), nullable=False, server_default='group'),
        sa.Column('member_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('welcome_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('welcome_message', sa.Text(), nullable=True),
        sa.Column('welcome_delete_after', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('anti_spam_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('anti_flood_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('flood_limit', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('delete_joins', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('delete_links', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('delete_forwards', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_groups_owner_id', 'groups', ['owner_id'])

    op.create_table(
        'scheduled_posts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('group_id', sa.BigInteger(), nullable=False),
        sa.Column('owner_id', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('parse_mode', sa.String(10), nullable=False, server_default='HTML'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('repeat_interval', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_scheduled_posts_group_id', 'scheduled_posts', ['group_id'])
    op.create_index('ix_scheduled_posts_status', 'scheduled_posts', ['status'])


def downgrade() -> None:
    op.drop_table('scheduled_posts')
    op.drop_table('groups')
    op.drop_table('subscriptions')
    op.drop_table('users')

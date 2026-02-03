"""init

Revision ID: 0001_init
Revises: 
Create Date: 2026-02-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tg_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_update_id", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "tg_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_group_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "message_id", name="uq_tg_msg"),
    )
    op.create_index("ix_tg_posts_channel_id", "tg_posts", ["channel_id"])
    op.create_index("ix_tg_posts_message_id", "tg_posts", ["message_id"])
    op.create_index("ix_tg_posts_media_group_id", "tg_posts", ["media_group_id"])

    op.create_table(
        "tg_media_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_post_id", sa.Integer(), sa.ForeignKey("tg_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("file_id", sa.String(length=256), nullable=False),
        sa.Column("file_unique_id", sa.String(length=256), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("file_name", sa.String(length=256), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tg_media_items_tg_post_id", "tg_media_items", ["tg_post_id"])

    op.create_table(
        "vk_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_post_id", sa.Integer(), sa.ForeignKey("tg_posts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("vk_owner_id", sa.BigInteger(), nullable=False),
        sa.Column("vk_post_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attachments_count", sa.Integer(), nullable=False),
        sa.Column("vk_response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "album_state",
        sa.Column("media_group_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_tg_post_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("tg_post_id", sa.Integer(), nullable=True),
        sa.Column("media_group_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jobs_tg_post_id", "jobs", ["tg_post_id"])
    op.create_index("ix_jobs_media_group_id", "jobs", ["media_group_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_media_group_id", table_name="jobs")
    op.drop_index("ix_jobs_tg_post_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("album_state")
    op.drop_table("vk_posts")
    op.drop_index("ix_tg_media_items_tg_post_id", table_name="tg_media_items")
    op.drop_table("tg_media_items")
    op.drop_index("ix_tg_posts_media_group_id", table_name="tg_posts")
    op.drop_index("ix_tg_posts_message_id", table_name="tg_posts")
    op.drop_index("ix_tg_posts_channel_id", table_name="tg_posts")
    op.drop_table("tg_posts")
    op.drop_table("settings")
    op.drop_table("tg_state")

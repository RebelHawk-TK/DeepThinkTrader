"""Users table — auth identity + admin-controlled access.

Phase B+: stores Google OAuth users, their role (admin/user), and whether
they are enabled to access the dashboard. The bot's trade data is NOT yet
user-scoped (that's Phase C) — this table is for auth and access control
only. Other tables gain user_id in a later migration.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text),
        sa.Column("picture_url", sa.Text),
        # role: 'admin' or 'user'. Admins see the admin page and can toggle access.
        sa.Column("role", sa.Text, nullable=False, server_default="user"),
        # enabled: new users default false and need admin approval before seeing data.
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")

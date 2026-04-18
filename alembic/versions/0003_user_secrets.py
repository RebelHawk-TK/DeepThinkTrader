"""user_secrets — encrypted Alpaca credentials per user.

Phase D: users enter their Alpaca paper API keys through a Streamlit form in
the dashboard. The form encrypts both values with a Fernet key loaded from
GCP Secret Manager and writes them here. The bot reads + decrypts per-user
keys when it runs a cycle for that user (Phase C wiring).

We store raw Fernet tokens (bytes). Fernet tokens are base64-encoded but
contain NULs, so BYTEA is the right type.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_secrets",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("alpaca_key_id_enc", sa.LargeBinary, nullable=False),
        sa.Column("alpaca_secret_enc", sa.LargeBinary, nullable=False),
        # Last four chars of the plaintext key id, for UI display ("…AB12") so
        # users can tell at a glance which key pair is saved.
        sa.Column("alpaca_key_id_tail", sa.String(8), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_secrets")

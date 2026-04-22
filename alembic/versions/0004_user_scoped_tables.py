"""user_scoped_tables — add user_id FK to tenant-owned tables and wipe legacy rows.

Phase C wiring: the bot moves from a single shared Alpaca account to per-user
accounts. Every row that represents one user's trading activity needs a
user_id. Tables that hold cross-user data (atr_history as a ticker cache,
alpaca_request_ids as an audit log) stay global.

We wipe the existing rows rather than backfill. The existing data was produced
by the shared bot against Tom's paper account; once the shared keys are
retired there's no meaningful owner to assign, and the dashboard had not yet
been shared with any real users.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


# Tables that hold per-user activity. All wiped, all get user_id NOT NULL.
USER_SCOPED_TABLES = (
    "research_reports",
    "analysis_results",
    "trades",
    "slippage_records",
    "edge_performance",
    "reflections",
    "daily_pnl",
)


def upgrade() -> None:
    # Wipe order matters: tables with FKs into `trades` must be emptied
    # before `trades` itself (partial_exits, edge_performance, reflections
    # all reference trades.id). Within the USER_SCOPED_TABLES loop, delete
    # children first so the trades DELETE doesn't trip an FK constraint.
    for table in (
        "partial_exits",
        "edge_performance",
        "reflections",
        "trades",
        "research_reports",
        "analysis_results",
        "slippage_records",
        "daily_pnl",
    ):
        op.execute(f"DELETE FROM {table}")

    # daily_pnl had UNIQUE(date); becomes UNIQUE(user_id, date).
    with op.batch_alter_table("daily_pnl") as batch:
        batch.drop_constraint("daily_pnl_date_key", type_="unique")

    for table in USER_SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
        )
        op.create_index(f"idx_{table}_user_id", table, ["user_id"])

    op.create_unique_constraint(
        "uq_daily_pnl_user_date", "daily_pnl", ["user_id", "date"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_daily_pnl_user_date", "daily_pnl", type_="unique")

    for table in USER_SCOPED_TABLES:
        op.drop_index(f"idx_{table}_user_id", table_name=table)
        op.drop_column(table, "user_id")

    op.create_unique_constraint("daily_pnl_date_key", "daily_pnl", ["date"])

"""Initial schema — mirrors the SQLite schema created by utils/database.py _init_tables.

Revision ID: 0001
Revises:
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("news_impact_score", sa.Float),
        sa.Column("reddit_sentiment_score", sa.Float),
        sa.Column("combined_catalyst_score", sa.Float),
        sa.Column("report_json", sa.Text, nullable=False),
        sa.Column("portfolio", sa.Text, server_default="main"),
    )
    op.create_index("idx_research_ticker", "research_reports", ["ticker"])

    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("conviction", sa.Float, nullable=False),
        sa.Column("position_size_pct", sa.Float),
        sa.Column("stop_loss_pct", sa.Float),
        sa.Column("take_profit_pct", sa.Float),
        sa.Column("reasoning", sa.Text),
        sa.Column("analysis_json", sa.Text, nullable=False),
        sa.Column("portfolio", sa.Text, server_default="main"),
    )
    op.create_index("idx_analysis_ticker", "analysis_results", ["ticker"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("entry_price", sa.Float),
        sa.Column("stop_loss_price", sa.Float),
        sa.Column("take_profit_price", sa.Float),
        sa.Column("conviction", sa.Float),
        sa.Column("status", sa.Text, server_default="OPEN"),
        sa.Column("exit_price", sa.Float),
        sa.Column("exit_timestamp", sa.Text),
        sa.Column("pnl", sa.Float),
        sa.Column("order_id", sa.Text),
        sa.Column("reasoning", sa.Text),
        sa.Column("portfolio", sa.Text, server_default="main"),
        # Trailing stop / scale-out migration columns
        sa.Column("trailing_stop_price", sa.Float),
        sa.Column("highest_price", sa.Float),
        sa.Column("trailing_stop_active", sa.Integer, server_default="0"),
        sa.Column("original_quantity", sa.Integer),
        sa.Column("exit_reason", sa.Text),
        sa.Column("edges_fired", sa.Integer),
        sa.Column("edge_details", sa.Text),
        sa.Column("risk_amount", sa.Float),
        sa.Column("sector", sa.Text),
    )
    op.create_index("idx_trades_status", "trades", ["status"])
    op.create_index("idx_trades_ticker", "trades", ["ticker"])
    op.create_index("idx_trades_portfolio", "trades", ["portfolio"])
    op.create_index("idx_trades_timestamp", "trades", ["timestamp"])

    op.create_table(
        "daily_pnl",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("date", sa.Text, nullable=False, unique=True),
        sa.Column("realized_pnl", sa.Float, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float, server_default="0"),
        sa.Column("trades_taken", sa.Integer, server_default="0"),
        sa.Column("trades_won", sa.Integer, server_default="0"),
        sa.Column("trades_lost", sa.Integer, server_default="0"),
    )

    op.create_table(
        "partial_exits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=False),
        sa.Column("pnl", sa.Float),
        sa.Column("reason", sa.Text),
        sa.Column("order_id", sa.Text),
    )

    op.create_table(
        "atr_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("date", sa.Text, nullable=False),
        sa.Column("atr_value", sa.Float, nullable=False),
        sa.UniqueConstraint("ticker", "date", name="uq_atr_history_ticker_date"),
    )

    op.create_table(
        "alpaca_request_ids",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("request_id", sa.Text, nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("ticker", sa.Text),
        sa.Column("order_id", sa.Text),
        sa.Column("http_status", sa.Integer),
        sa.Column("success", sa.Integer, server_default="1"),
    )

    op.create_table(
        "slippage_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("expected_price", sa.Float, nullable=False),
        sa.Column("filled_price", sa.Float, nullable=False),
        sa.Column("slippage_pct", sa.Float, nullable=False),
        sa.Column("order_type", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("shares", sa.Integer),
        sa.Column("hour_of_day", sa.Integer),
        sa.Column("portfolio", sa.Text, server_default="main"),
    )

    op.create_table(
        "edge_performance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("edge_combo", sa.Text, nullable=False),
        sa.Column("edges_fired", sa.Integer, nullable=False),
        sa.Column("fund_passed", sa.Integer),
        sa.Column("tech_passed", sa.Integer),
        sa.Column("sent_passed", sa.Integer),
        sa.Column("conviction", sa.Float),
        sa.Column("pnl", sa.Float),
        sa.Column("won", sa.Integer),
        sa.Column("portfolio", sa.Text, server_default="main"),
    )

    op.create_table(
        "reflections",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("ticker", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("thesis", sa.Text, nullable=False),
        sa.Column("outcome_pnl", sa.Float, nullable=False),
        sa.Column("outcome_label", sa.Text, nullable=False),
        sa.Column("lesson", sa.Text, nullable=False),
    )
    op.create_index("idx_reflections_ticker", "reflections", ["ticker"])
    op.create_index("idx_reflections_created", "reflections", ["created_at"])


def downgrade() -> None:
    op.drop_table("reflections")
    op.drop_table("edge_performance")
    op.drop_table("slippage_records")
    op.drop_table("alpaca_request_ids")
    op.drop_table("atr_history")
    op.drop_table("partial_exits")
    op.drop_table("daily_pnl")
    op.drop_table("trades")
    op.drop_table("analysis_results")
    op.drop_table("research_reports")

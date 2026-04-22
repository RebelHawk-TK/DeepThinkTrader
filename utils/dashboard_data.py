"""Dashboard data builders — compute the inputs for dashboard_widgets.

Stateless helpers. No Streamlit imports here (keeps the widgets thin and
these functions independently testable if we ever want to).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


# ─────────────────────────── Banner data ────────────────────────────────


def compute_bot_status(log_path: str) -> tuple[str, str]:
    """Return (status, detail) where status ∈ {"ok", "warning", "down"}.

    Uses the last line of the log file to infer heartbeat age. Heartbeat is
    logged every 2 min by the main loop, so >5 min is yellow, >15 min red.
    """
    try:
        import os
        if not os.path.exists(log_path):
            return "warning", "log not found"
        mtime = os.path.getmtime(log_path)
        age_sec = max(0, (datetime.now().timestamp() - mtime))
        if age_sec > 900:
            return "down", f"silent {int(age_sec / 60)} min"
        if age_sec > 300:
            return "warning", f"last log {int(age_sec / 60)} min ago"
        return "ok", f"last log {int(age_sec)}s ago"
    except Exception as e:
        return "warning", f"check failed ({type(e).__name__})"


def compute_market_state(clock) -> tuple[str, bool]:
    """Return ('OPEN — closes Xh Ym' | 'CLOSED — opens Xh Ym', is_open)."""
    try:
        status = clock.get_status()
        is_open = bool(status.get("is_open"))
        if is_open:
            mins = status.get("minutes_to_close")
            if mins is None:
                return "OPEN", True
            h, m = divmod(int(mins), 60)
            suffix = f"{h}h {m}m" if h else f"{m}m"
            return f"OPEN — closes in {suffix}", True
        mins = status.get("minutes_to_open")
        if mins is None:
            # Fall back: compute from next_open timestamp if available.
            try:
                next_open = datetime.fromisoformat(status.get("next_open", ""))
                mins = max(0, int((next_open - datetime.now(next_open.tzinfo)).total_seconds() / 60))
            except Exception:
                return "CLOSED", False
        h, m = divmod(int(mins), 60)
        suffix = f"{h}h {m}m" if h else f"{m}m"
        return f"CLOSED — opens in {suffix}", False
    except Exception:
        return "CLOSED", False


def compute_regime(config) -> dict[str, Any]:
    """Classify current regime. Fails gracefully to 'unknown' if any deps miss."""
    try:
        from analytics.regime import classify_regime
        from brokers.alpaca import AlpacaBroker
        broker = AlpacaBroker(config)
        a = classify_regime(broker)
        return {
            "label": a.label,
            "vol_pct": a.annualized_vol * 100,
            "recommended_mode": a.recommended_mode,
        }
    except Exception:
        return {"label": "unknown", "vol_pct": 0.0, "recommended_mode": "normal"}


def compute_alerts(
    *,
    paused_portfolios: set[str] | None,
    drawdown_pct: float,
    drawdown_halt_pct: float,
    consecutive_losses: int,
    circuit_breaker_active: bool,
) -> list[str]:
    alerts: list[str] = []
    if circuit_breaker_active:
        alerts.append("SPY or VIX circuit breaker active — new entries blocked")
    if drawdown_pct > drawdown_halt_pct * 0.75:
        alerts.append(
            f"Drawdown {drawdown_pct:.1f}% is {drawdown_pct / drawdown_halt_pct * 100:.0f}% "
            f"of the {drawdown_halt_pct:.1f}% halt threshold"
        )
    if consecutive_losses >= 3:
        alerts.append(f"{consecutive_losses} consecutive losing trades — revenge-trading watch")
    if paused_portfolios:
        for p in paused_portfolios:
            alerts.append(f"Portfolio '{p}' paused due to strategy degradation")
    return alerts


# ─────────────────────────── KPI row data ───────────────────────────────


def compute_30day_pnl(
    portfolio_hist: dict | None,
    current_equity: float | None = None,
) -> tuple[float, float]:
    """Return (absolute_pnl, percent_pnl) over the last 30 days.

    Uses Alpaca portfolio_history to anchor the 30-days-ago start. For the
    endpoint, prefers the live `current_equity` when provided — Alpaca's
    daily-timeframe history caches yesterday's close during market hours,
    so without this override the value would freeze mid-day.
    """
    if not portfolio_hist:
        return 0.0, 0.0
    eq = portfolio_hist.get("equity") or []
    ts = portfolio_hist.get("timestamp") or []
    if len(eq) < 2 or len(ts) < 2:
        return 0.0, 0.0
    # 1-day grace so a timestamp that's ~exactly 30 days ago still counts.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
    start_eq = None
    for i, t in enumerate(ts):
        if t >= cutoff and (eq[i] or 0) > 0:
            start_eq = eq[i]
            break
    if start_eq is None:
        start_eq = next((e for e in eq if e and e > 0), None)
    if current_equity is not None and current_equity > 0:
        end_eq = current_equity
    else:
        end_eq = next((e for e in reversed(eq) if e and e > 0), None)
    if start_eq is None or end_eq is None or start_eq <= 0:
        return 0.0, 0.0
    return end_eq - start_eq, (end_eq - start_eq) / start_eq * 100


def compute_today_pnl(account: dict | None) -> tuple[float, float]:
    """Return (absolute_pnl, percent_pnl) for today only.

    Uses Alpaca's `last_equity` (yesterday's market-close equity) as the
    baseline. This is the authoritative intraday P&L — resets at midnight ET.
    """
    if not account:
        return 0.0, 0.0
    try:
        equity = float(account.get("equity", 0))
        last_equity = float(account.get("last_equity", 0))
    except (TypeError, ValueError):
        return 0.0, 0.0
    if last_equity <= 0:
        return 0.0, 0.0
    pnl = equity - last_equity
    return pnl, pnl / last_equity * 100


def compute_total_exposure_pct(positions: list[dict], equity: float) -> float:
    if equity <= 0 or not positions:
        return 0.0
    mv = sum(abs(float(p.get("market_value", 0) or 0)) for p in positions)
    return mv / equity * 100


def compute_drawdown_from_peak(portfolio_hist: dict | None) -> float:
    """Current drawdown from 30-day peak equity, as a positive percent."""
    if not portfolio_hist:
        return 0.0
    eq = [e for e in (portfolio_hist.get("equity") or []) if e and e > 0]
    if len(eq) < 2:
        return 0.0
    peak = max(eq)
    current = eq[-1]
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak * 100)


# ─────────────────────────── Risk & Memory data ─────────────────────────


def compute_kelly_state(db, risk_manager, user_id: int, portfolio: str = "main") -> dict[str, Any]:
    """Return the current Kelly fraction the bot would use + context."""
    try:
        stats = db.get_strategy_stats(user_id, portfolio)
        n = stats["trade_count"]
        if n >= 20 and stats["payoff_ratio"] > 0:
            f = risk_manager._kelly_fraction(
                stats["win_rate"], stats["payoff_ratio"], n_trades=n,
            )
            return {"fraction": f, "n_trades": n, "win_rate": stats["win_rate"]}
        return {"fraction": None, "n_trades": n, "win_rate": stats.get("win_rate")}
    except Exception:
        return {"fraction": None, "n_trades": 0, "win_rate": None}


def compute_portfolio_cvar(positions: list[dict], api_key: str, secret_key: str) -> float | None:
    """Historical-simulation 5%-CVaR on current open positions.

    Callers supply the signed-in user's Alpaca keys; CVaR is computed per user
    because each user's open positions are their own.
    """
    try:
        from analytics.cvar import portfolio_cvar
        from brokers.alpaca import AlpacaBroker
        holdings = {
            p["symbol"]: abs(float(p.get("market_value", 0) or 0))
            for p in positions
        }
        if not holdings:
            return 0.0
        broker = AlpacaBroker(api_key=api_key, secret_key=secret_key)
        return portfolio_cvar(broker, holdings)
    except Exception:
        return None


def compute_top_correlation(positions: list[dict], api_key: str, secret_key: str) -> tuple[str, str, float] | None:
    """Find the pair of held tickers with the highest pairwise correlation.

    Returns (ticker_a, ticker_b, corr) or None if fewer than 2 positions or
    no data available.
    """
    try:
        from analytics.correlation import _log_returns, _pearson  # reuse helpers
        from brokers.alpaca import AlpacaBroker
        tickers = [p["symbol"] for p in positions]
        if len(tickers) < 2:
            return None
        broker = AlpacaBroker(api_key=api_key, secret_key=secret_key)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=80)
        returns_by_ticker: dict[str, list[float]] = {}
        for t in tickers:
            try:
                bars = broker.get_bars(t, start=start, end=end, timeframe="1Day")
                rs = _log_returns([b.close for b in bars])
                if len(rs) >= 10:
                    returns_by_ticker[t] = rs
            except Exception:
                continue
        if len(returns_by_ticker) < 2:
            return None
        ticker_list = list(returns_by_ticker.keys())
        best: tuple[str, str, float] | None = None
        for i in range(len(ticker_list)):
            for j in range(i + 1, len(ticker_list)):
                a, b = ticker_list[i], ticker_list[j]
                corr = _pearson(returns_by_ticker[a], returns_by_ticker[b])
                if corr is None:
                    continue
                if best is None or abs(corr) > abs(best[2]):
                    best = (a, b, corr)
        return best
    except Exception:
        return None


def compute_recent_reflections(db, user_id: int, limit: int = 3) -> list[dict]:
    try:
        return db.get_reflections(user_id, limit=limit)
    except Exception:
        return []

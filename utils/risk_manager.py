from __future__ import annotations

import logging
import math
from datetime import datetime

from config import Config
from utils.database import Database
from utils.market_clock import get_market_clock

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        user_id: int,
        api_key: str | None = None,
        secret_key: str | None = None,
        db: Database | None = None,
    ):
        """Per-user risk manager. Every db query is scoped to self.user_id;
        Alpaca-authenticated calls (market clock, account reads) require the
        user's keys. Keys are optional for callers that only need read-only
        helpers like check_sector_trend — those use yfinance and don't need
        credentials.
        """
        self.db = db or Database()
        self.config = Config()
        self.user_id = user_id
        self._api_key = api_key
        self._secret_key = secret_key
        # In-memory cache for earnings dates (ticker -> (date_str, fetched_at))
        self._earnings_cache: dict[str, tuple[str | None, datetime]] = {}

    def _get_params(self, portfolio: str) -> dict:
        """Return risk parameters for the given portfolio."""
        if portfolio == "penny":
            return {
                "max_risk_per_trade": self.config.PENNY_MAX_RISK_PER_TRADE,
                "max_daily_loss": self.config.PENNY_MAX_DAILY_LOSS,
                "min_conviction": self.config.PENNY_MIN_CONVICTION,
                "min_reward_risk_ratio": self.config.PENNY_MIN_REWARD_RISK_RATIO,
                "max_position_pct": self.config.PENNY_MAX_POSITION_PCT,
                "max_open_positions": self.config.PENNY_MAX_OPEN_POSITIONS,
            }
        return {
            "max_risk_per_trade": self.config.MAX_RISK_PER_TRADE,
            "max_daily_loss": self.config.MAX_DAILY_LOSS,
            "min_conviction": self.config.MIN_CONVICTION,
            "min_reward_risk_ratio": self.config.MIN_REWARD_RISK_RATIO,
            "max_position_pct": self.config.MAX_POSITION_PCT,
            "max_open_positions": self.config.MAX_OPEN_POSITIONS,
        }

    # ── Phase 1a: Kelly-Based Position Sizing ─────────────────────

    def calculate_position_size(
        self, account_value: float, entry_price: float, stop_loss_pct: float,
        portfolio: str = "main",
        ticker: str | None = None,
        broker=None,
    ) -> int:
        """Calculate shares using fractional Kelly when enough history exists,
        falling back to fixed-risk sizing (1% of equity).

        When `ticker` and `broker` are provided, the result is additionally
        scaled by a correlation multiplier: a candidate highly correlated
        with existing holdings gets 0.5x size. This is coarser than CVaR
        but cheaper to compute on every trade.
        """
        if entry_price <= 0:
            return 0
        params = self._get_params(portfolio)

        # Try Kelly sizing if we have enough trade history
        stats = self.db.get_strategy_stats(self.user_id, portfolio)
        if stats["trade_count"] >= 20 and stats["payoff_ratio"] > 0:
            kelly_fraction = self._kelly_fraction(
                stats["win_rate"], stats["payoff_ratio"], n_trades=stats["trade_count"],
            )
            risk_pct = kelly_fraction
            logger.info(
                f"Kelly sizing: f*={kelly_fraction:.4f} "
                f"(win_rate={stats['win_rate']:.2f}, payoff={stats['payoff_ratio']:.2f}, "
                f"N={stats['trade_count']})"
            )
        else:
            risk_pct = self.config.RISK_PCT_PER_TRADE
            logger.info(f"Fixed-risk sizing: {risk_pct*100:.1f}% (insufficient history: {stats['trade_count']} trades)")

        # Correlation-aware scaling — applied before risk/value caps so we
        # don't over-concentrate in a correlated cluster.
        corr_mult = self._correlation_multiplier(ticker, broker)
        if corr_mult < 1.0:
            logger.info(
                f"Correlation-aware size multiplier: {corr_mult:.2f}x "
                f"(candidate: {ticker})"
            )
        risk_pct *= corr_mult

        risk_amount = account_value * risk_pct
        risk_per_share = entry_price * (stop_loss_pct / 100)
        if risk_per_share <= 0:
            return 0
        shares_by_risk = int(risk_amount / risk_per_share)

        # Cap position value (mode-driven); scale the cap by corr_mult too.
        max_position_value = account_value * params["max_position_pct"] * corr_mult
        shares_by_value = int(max_position_value / entry_price)

        return max(0, min(shares_by_risk, shares_by_value))

    def _correlation_multiplier(self, ticker: str | None, broker) -> float:
        """Compute sizing multiplier based on correlation with held positions."""
        if not ticker or broker is None:
            return 1.0
        try:
            from analytics.correlation import (
                average_correlation,
                correlation_size_multiplier,
            )
            held = [t["ticker"] for t in self.db.get_open_trades(self.user_id)]
            if not held:
                return 1.0
            avg = average_correlation(broker, ticker, held)
            return correlation_size_multiplier(avg)
        except Exception as e:
            logger.warning(f"Correlation multiplier failed for {ticker}: {e}")
            return 1.0

    # Bayesian prior for win-rate: beta(alpha, beta) with both = 20.
    # Equivalent to 40 pseudo-trades at 50% win rate. This dominates the
    # estimate at low N (where sample win rate is noisy) and fades as N grows.
    _KELLY_PRIOR_ALPHA = 20.0
    _KELLY_PRIOR_BETA = 20.0

    def _kelly_fraction(
        self, win_rate: float, payoff_ratio: float, n_trades: int = 0
    ) -> float:
        """Shrinkage-adjusted fractional Kelly: f* = (p - q) / b × safety_multiplier.

        p = Bayesian-shrunk win rate, q = 1 - p, b = payoff ratio.

        Kelly estimates are extremely sensitive to win-rate error at low N.
        Overestimating win rate by 5% can double the ruin probability. We
        address this two ways:

        1. **Shrinkage toward a beta(20, 20) prior.** At N=20 sample has
           equal weight with prior → shrunk estimate splits the difference.
           At N=100 sample dominates. At N=5 prior dominates.
        2. **Quarter-Kelly at low N, half-Kelly at high N.** Below 50 trades
           the variance of the estimate is high enough that quarter-Kelly
           is safer; above 50 we switch to the config default (half-Kelly).

        PyQuantLab and the practitioner literature both recommend fractional
        Kelly with some form of shrinkage until you have ~100+ observations.
        """
        if payoff_ratio <= 0:
            return self.config.RISK_PCT_PER_TRADE

        # 1. Bayesian shrinkage on win rate.
        wins = win_rate * n_trades
        losses = (1 - win_rate) * n_trades
        a = wins + self._KELLY_PRIOR_ALPHA
        b = losses + self._KELLY_PRIOR_BETA
        p_shrunk = a / (a + b)
        q_shrunk = 1 - p_shrunk

        kelly = (p_shrunk - q_shrunk) / payoff_ratio

        # 2. Adaptive safety multiplier: quarter-Kelly when sample is small.
        if n_trades < 50:
            safety = min(0.25, self.config.KELLY_SAFETY_MULTIPLIER)
        else:
            safety = self.config.KELLY_SAFETY_MULTIPLIER

        safe_kelly = kelly * safety
        # Clamp: never risk more than mode's max, never less than 0.5%.
        return max(0.005, min(safe_kelly, self.config.MAX_RISK_PER_TRADE))

    # ── Phase 1b: Volatility Adjustment ───────────────────────────

    def check_volatility_adjustment(self, current_atr: float, median_atr: float) -> float:
        """If current ATR > VOLATILITY_ATR_MULTIPLIER × median ATR, cut risk in half.

        Returns a multiplier (1.0 = normal, 0.5 = high volatility).
        """
        if median_atr <= 0 or current_atr <= 0:
            return 1.0
        ratio = current_atr / median_atr
        if ratio > self.config.VOLATILITY_ATR_MULTIPLIER:
            logger.warning(
                f"High volatility detected: ATR ratio {ratio:.1f}x "
                f"(current={current_atr:.2f}, median={median_atr:.2f}) — cutting risk 50%"
            )
            return 0.5
        return 1.0

    # ── Phase 1c: Portfolio-Level Guards ───────────────────────────

    def _fetch_alpaca_equity_history(self, days: int = 30) -> list[float]:
        """Fetch daily equity values from Alpaca /v2/account/portfolio/history.

        Returns a list of positive equity values filtered to the lookback window
        and (if configured) the BASELINE_DATE. Returns empty list on failure.
        """
        try:
            import requests as _rq
            headers = {
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
            }
            # Request ~days of daily bars. Alpaca accepts "1A","3M","1M","5D" — pick nearest.
            period = "1M" if days <= 30 else ("3M" if days <= 90 else "1A")
            resp = _rq.get(
                f"{self.config.ALPACA_BASE_URL}/v2/account/portfolio/history",
                headers=headers,
                params={
                    "period": period,
                    "timeframe": "1D",
                    "intraday_reporting": "market_hours",
                },
                timeout=10,
            )
            if not resp.ok:
                return []
            data = resp.json()
            eq = data.get("equity") or []
            ts = data.get("timestamp") or []
            baseline = getattr(self.config, "BASELINE_DATE", None) or ""
            baseline_ts = 0
            if baseline:
                try:
                    baseline_ts = int(datetime.strptime(baseline, "%Y-%m-%d").timestamp())
                except ValueError:
                    baseline_ts = 0
            prev = None
            out = []
            for i, e in enumerate(eq):
                if not e or e <= 0:
                    continue
                if i < len(ts) and ts[i] < baseline_ts:
                    continue
                # Skip settlement artifacts: one-bar crash of >40% that recovers
                # (mirrors the filter used in dashboard.py:390).
                if prev is not None and e < prev * 0.6:
                    continue
                out.append(e)
                prev = e
            return out
        except Exception as e:
            logger.warning(f"Failed to fetch Alpaca equity history: {e}")
            return []

    def check_drawdown_halt(self, account_value: float) -> bool:
        """Return True if drawdown from peak is within limits (OK to trade).

        Blocks new entries if drawdown > MAX_DRAWDOWN_HALT_PCT in last 30 days.

        Uses Alpaca's portfolio_history endpoint for an authoritative equity
        curve; falls back to permitting trading if history can't be fetched or
        is too short to evaluate (less scary than blocking on transient errors).
        """
        equity = self._fetch_alpaca_equity_history(days=30)
        if len(equity) < 5:
            return True  # Not enough history yet, allow trading.

        peak = max(equity)
        # Use Alpaca's authoritative current equity rather than caller-passed value
        # (they should match, but if they don't, Alpaca wins).
        current = equity[-1] if account_value <= 0 else account_value
        if peak <= 0:
            return True

        drawdown_pct = max(0.0, (peak - current) / peak)
        if drawdown_pct > self.config.MAX_DRAWDOWN_HALT_PCT:
            logger.warning(
                f"DRAWDOWN HALT: {drawdown_pct*100:.1f}% drawdown from 30-day peak "
                f"${peak:,.0f} (current ${current:,.0f}) exceeds "
                f"{self.config.MAX_DRAWDOWN_HALT_PCT*100:.0f}% limit"
            )
            return False
        return True

    def check_risk_of_ruin(self, account_value: float, portfolio: str = "main") -> bool:
        """Return True if risk of ruin is acceptable (OK to trade).

        RoR ≈ e^(-2 × edge × capital / risk_per_trade). Block if > MAX_RISK_OF_RUIN_PCT.
        """
        stats = self.db.get_strategy_stats(self.user_id, portfolio)
        if stats["trade_count"] < 20:
            return True  # Not enough data, allow trading

        edge = stats["expectancy"]
        if edge <= 0:
            logger.warning(f"Negative expectancy (${edge:.2f}) — risk of ruin is high")
            return False

        risk_per_trade = account_value * self.config.RISK_PCT_PER_TRADE
        if risk_per_trade <= 0:
            return True

        exponent = -2 * edge * account_value / (risk_per_trade * risk_per_trade)
        # Clamp exponent to avoid overflow
        exponent = max(exponent, -500)
        ror = math.exp(exponent)

        if ror > self.config.MAX_RISK_OF_RUIN_PCT:
            logger.warning(
                f"RISK OF RUIN too high: {ror*100:.2f}% > {self.config.MAX_RISK_OF_RUIN_PCT*100:.0f}% limit"
            )
            return False
        return True

    # ── Phase 1d: Pre-Trade Liquidity Check ───────────────────────

    def check_liquidity(self, proposed_shares: int, avg_daily_volume: int) -> bool:
        """Return True if proposed shares < ADV / MIN_ADV_RATIO.

        Prevents outsized orders in illiquid names.
        """
        if avg_daily_volume <= 0:
            logger.warning("No volume data — blocking trade for liquidity safety")
            return False
        max_shares = avg_daily_volume // self.config.MIN_ADV_RATIO
        if proposed_shares > max_shares:
            logger.warning(
                f"LIQUIDITY CHECK FAILED: {proposed_shares} shares > ADV/{self.config.MIN_ADV_RATIO} "
                f"({max_shares} shares, ADV={avg_daily_volume:,})"
            )
            return False
        return True

    # ── Phase 5a: Market Circuit Breaker ──────────────────────────

    def check_market_health(
        self, spy_intraday_change_pct: float, action: str = "BUY", vix_level: float = 0.0
    ) -> bool:
        """Return True if market conditions allow the trade.

        Blocks new entries if:
        - SPY drops > CIRCUIT_BREAKER_SPY_DROP_PCT intraday (longs only)
        - VIX > CIRCUIT_BREAKER_VIX_THRESHOLD (all entries)
        """
        # VIX circuit breaker — blocks ALL new entries when fear is extreme
        if vix_level > 0 and vix_level >= self.config.CIRCUIT_BREAKER_VIX_THRESHOLD:
            logger.warning(
                f"VIX CIRCUIT BREAKER: VIX at {vix_level:.1f} "
                f"(threshold: {self.config.CIRCUIT_BREAKER_VIX_THRESHOLD}) — blocking ALL entries"
            )
            return False

        if action != "BUY":
            return True  # SPY check only blocks longs
        if spy_intraday_change_pct < self.config.CIRCUIT_BREAKER_SPY_DROP_PCT:
            logger.warning(
                f"CIRCUIT BREAKER: SPY down {spy_intraday_change_pct:.2f}% "
                f"(threshold: {self.config.CIRCUIT_BREAKER_SPY_DROP_PCT}%) — blocking LONG entries"
            )
            return False
        return True

    # ── Phase 6a: Bid-Ask Spread Validation ────────────────────

    def check_spread(self, spread_pct: float, portfolio: str = "main") -> bool:
        """Return True if bid-ask spread is acceptable for the order type.

        Wide spreads cause hidden slippage on market orders.
        """
        max_spread = (
            self.config.PENNY_MAX_SPREAD_PCT
            if portfolio == "penny"
            else self.config.MAX_SPREAD_PCT
        )
        if spread_pct > max_spread:
            logger.warning(
                f"SPREAD CHECK FAILED: spread {spread_pct:.2f}% > max {max_spread:.1f}% — "
                f"order would suffer excessive slippage"
            )
            return False
        return True

    # ── Phase 6b: Sector Concentration ─────────────────────────

    def check_sector_concentration(
        self, ticker: str, sector: str, account_value: float, entry_value: float
    ) -> bool:
        """Return True if adding this position won't exceed sector exposure limit.

        Prevents correlated drawdowns from over-concentration in one sector.
        """
        if not sector or sector == "Unknown":
            return True  # Can't validate without sector data

        open_trades = self.db.get_open_trades(self.user_id)
        sector_exposure = 0.0

        for trade in open_trades:
            trade_sector = trade.get("sector", "")
            if trade_sector == sector:
                trade_value = (trade.get("entry_price", 0) or 0) * (trade.get("quantity", 0) or 0)
                sector_exposure += trade_value

        # Add proposed trade
        new_total = sector_exposure + entry_value
        exposure_pct = new_total / account_value if account_value > 0 else 0

        if exposure_pct > self.config.MAX_SECTOR_EXPOSURE_PCT:
            logger.warning(
                f"SECTOR CONCENTRATION: {sector} exposure would be {exposure_pct*100:.1f}% "
                f"(limit: {self.config.MAX_SECTOR_EXPOSURE_PCT*100:.0f}%) — blocking {ticker}"
            )
            return False

        logger.info(f"Sector check OK: {sector} exposure {exposure_pct*100:.1f}% (adding {ticker})")
        return True

    # ── Phase 6d: CVaR Tail Risk Gate ──────────────────────────

    def check_cvar_limit(
        self,
        candidate_ticker: str,
        entry_value: float,
        broker=None,
        cvar_limit: float | None = None,
    ) -> bool:
        """Return True if adding this position keeps portfolio 5%-CVaR below
        the limit. Requires a broker for historical bar fetch; when absent,
        returns True (same fail-open philosophy as the correlation check).

        Rationale: 25%-per-sector and correlation-aware sizing catch most
        cluster risk, but neither captures the _joint_ tail behavior across
        all holdings. CVaR does, using historical simulation so we don't
        have to assume normality.
        """
        if broker is None:
            return True
        limit = cvar_limit if cvar_limit is not None else getattr(
            self.config, "MAX_PORTFOLIO_CVAR_PCT", 0.05,
        )
        try:
            from analytics.cvar import candidate_would_breach_cvar
            holdings = {
                t["ticker"]: (t.get("entry_price", 0) or 0) * (t.get("quantity", 0) or 0)
                for t in self.db.get_open_trades(self.user_id)
            }
            breached, projected = candidate_would_breach_cvar(
                broker=broker,
                current_holdings=holdings,
                candidate_ticker=candidate_ticker,
                candidate_value=entry_value,
                cvar_limit=limit,
            )
            if breached:
                logger.warning(
                    f"CVAR LIMIT: adding {candidate_ticker} "
                    f"(${entry_value:,.0f}) would push portfolio 5%-CVaR to "
                    f"{projected * 100:.2f}% > {limit * 100:.2f}% limit — blocking"
                )
                return False
            if projected is not None:
                logger.info(
                    f"CVaR check OK: projected 5%-CVaR "
                    f"{projected * 100:.2f}% ≤ {limit * 100:.2f}% "
                    f"(adding {candidate_ticker})"
                )
            return True
        except Exception as e:
            logger.warning(f"CVaR check failed for {candidate_ticker}: {e}")
            return True

    # ── Phase 6c: Overnight Gap Risk ───────────────────────────

    def calculate_gap_risk_multiplier(
        self, current_atr: float, current_price: float, beta: float = 1.0,
        near_earnings: bool = False,
    ) -> float:
        """Calculate a position size multiplier based on overnight gap risk.

        High-gap-risk stocks (high ATR/price ratio, high beta, near earnings)
        get reduced position sizes. Returns multiplier 0.5-1.0.
        """
        if current_price <= 0:
            return 1.0

        atr_pct = (current_atr / current_price) * 100 if current_atr > 0 else 0
        risk_score = 0.0

        # ATR as % of price — high means big daily swings = bigger gaps
        if atr_pct > self.config.GAP_RISK_ATR_THRESHOLD:
            risk_score += 1.0
        elif atr_pct > self.config.GAP_RISK_ATR_THRESHOLD * 0.7:
            risk_score += 0.5

        # High beta stocks gap harder with market moves
        if beta > 2.0:
            risk_score += 1.0
        elif beta > 1.5:
            risk_score += 0.5

        # Near earnings = maximum gap risk
        if near_earnings:
            risk_score += 1.5

        if risk_score >= 2.0:
            mult = self.config.GAP_RISK_POSITION_REDUCTION
            logger.warning(
                f"HIGH GAP RISK (score={risk_score:.1f}): ATR%={atr_pct:.1f}%, "
                f"beta={beta:.1f}, earnings={'yes' if near_earnings else 'no'} — "
                f"reducing position to {mult*100:.0f}%"
            )
            return mult
        elif risk_score >= 1.0:
            mult = 0.75
            logger.info(
                f"Moderate gap risk (score={risk_score:.1f}): "
                f"reducing position to {mult*100:.0f}%"
            )
            return mult

        return 1.0

    # ── Phase 8c: Sector Rotation Awareness ──────────────────────

    _SECTOR_ETF_MAP = {
        "Technology": "XLK",
        "Healthcare": "XLV",
        "Financials": "XLF",
        "Energy": "XLE",
        "Consumer Cyclical": "XLY",
        "Consumer Defensive": "XLP",
        "Industrials": "XLI",
        "Communication Services": "XLC",
        "Real Estate": "XLRE",
        "Utilities": "XLU",
        "Basic Materials": "XLB",
    }

    _sector_trend_cache: dict[str, tuple[bool, datetime]] = {}

    def check_sector_trend(self, sector: str) -> dict:
        """Check if the sector ETF is above its 50-day SMA (in an uptrend).

        Returns {"sector": str, "etf": str, "uptrend": bool, "above_sma50": bool,
                 "daily_change_pct": float}.
        Not a hard block — used as a soft signal for conviction adjustment.
        """
        etf = self._SECTOR_ETF_MAP.get(sector, "")
        default = {"sector": sector, "etf": etf, "uptrend": True, "above_sma50": True, "daily_change_pct": 0.0}

        if not etf:
            return default

        # Cache for 30 minutes
        cached = self._sector_trend_cache.get(etf)
        if cached:
            uptrend, fetched_at = cached
            if (datetime.now() - fetched_at).total_seconds() < 1800:
                return {**default, "uptrend": uptrend, "above_sma50": uptrend}

        try:
            import yfinance as yf
            stock = yf.Ticker(etf)
            hist = stock.history(period="3mo")
            if hist.empty or len(hist) < 50:
                return default

            sma_50 = hist["Close"].tail(50).mean()
            current = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else current
            daily_change = ((current - prev) / prev) * 100

            uptrend = current > sma_50

            self._sector_trend_cache[etf] = (uptrend, datetime.now())

            if not uptrend:
                logger.info(
                    f"SECTOR ROTATION: {sector} ({etf}) BELOW 50-SMA "
                    f"(${current:.2f} < ${sma_50:.2f}) — weak sector"
                )

            return {
                "sector": sector,
                "etf": etf,
                "uptrend": uptrend,
                "above_sma50": uptrend,
                "daily_change_pct": round(daily_change, 2),
            }

        except Exception as e:
            logger.debug(f"Sector trend check failed for {sector}/{etf}: {e}")
            return default

    # ── Phase 5b: Earnings Awareness ─────────────────────────────

    def check_earnings_proximity(self, ticker: str) -> dict:
        """Check if ticker has earnings within EARNINGS_EXIT_DAYS trading days.

        Phase 7b enhancement: also checks hours until earnings.
        If earnings are < 12 hours away (e.g., pre-market next morning when checked
        at 3pm), flags as imminent even if day count shows 1 day.

        Returns {"near_earnings": bool, "days_until": int|None, "hours_until": float|None,
                 "imminent": bool, "action": str}.
        """
        import yfinance as yf

        default_result = {
            "near_earnings": False, "days_until": None,
            "hours_until": None, "imminent": False, "action": "none",
        }

        # Check cache (24h TTL)
        cached = self._earnings_cache.get(ticker)
        if cached:
            cached_date, fetched_at = cached
            if (datetime.now() - fetched_at).total_seconds() < 86400:
                if cached_date:
                    try:
                        earn_dt = datetime.strptime(cached_date[:10], "%Y-%m-%d")
                        days = (earn_dt - datetime.now()).days
                        # Estimate hours: assume pre-market earnings at 7am ET next day
                        # If today is the day before, and it's after 3pm, that's < 16 hours
                        hours = (earn_dt - datetime.now()).total_seconds() / 3600
                        near = 0 <= days <= self.config.EARNINGS_EXIT_DAYS
                        imminent = 0 < hours < 12
                        near = near or imminent
                        action = self.config.EARNINGS_EXIT_MODE if near else "none"
                        return {
                            "near_earnings": near, "days_until": days,
                            "hours_until": round(hours, 1), "imminent": imminent,
                            "action": action,
                        }
                    except Exception:
                        pass
                return default_result

        # Fetch from yfinance
        try:
            stock = yf.Ticker(ticker)
            cal = stock.calendar
            earn_date = None
            if cal is not None:
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed:
                        earn_date = str(ed[0]) if isinstance(ed, list) and ed else str(ed)
                elif hasattr(cal, "iloc") and len(cal) > 0:
                    earn_date = str(cal.iloc[0])

            self._earnings_cache[ticker] = (earn_date, datetime.now())

            if earn_date:
                earn_dt = datetime.strptime(earn_date[:10], "%Y-%m-%d")
                days = (earn_dt - datetime.now()).days
                hours = (earn_dt - datetime.now()).total_seconds() / 3600
                near = 0 <= days <= self.config.EARNINGS_EXIT_DAYS
                imminent = 0 < hours < 12
                near = near or imminent

                if imminent:
                    logger.warning(
                        f"EARNINGS IMMINENT for {ticker}: {hours:.0f} hours away "
                        f"(< 12h threshold) — blocking entry"
                    )

                return {
                    "near_earnings": near,
                    "days_until": days,
                    "hours_until": round(hours, 1),
                    "imminent": imminent,
                    "action": self.config.EARNINGS_EXIT_MODE if near else "none",
                }
        except Exception as e:
            logger.debug(f"Earnings check failed for {ticker}: {e}")

        return default_result

    # ── Original methods (preserved) ──────────────────────────────

    # ── Warmup Gate ──────────────────────────────────────────────

    def check_warmup_complete(self) -> bool:
        """Return True if enough unique tickers have been analyzed to start trading.

        Per-user warmup: each user gets their own survey window. A new user's
        bot won't trade until their own analyses have covered enough tickers.
        """
        min_tickers = self.config.WARMUP_MIN_TICKERS
        if min_tickers <= 0:
            return True  # Warmup disabled

        with self.db._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT ticker) as n FROM analysis_results WHERE user_id = ?",
                (self.user_id,),
            ).fetchone()
        analyzed = row["n"] if row else 0

        if analyzed < min_tickers:
            logger.info(
                f"WARMUP: {analyzed}/{min_tickers} unique tickers analyzed — "
                f"execution blocked until warmup complete"
            )
            return False

        return True

    def check_daily_loss_limit(self, account_value: float) -> bool:
        """Return True if we're still within daily loss limit."""
        today_pnl = self.db.get_today_pnl(self.user_id)
        max_daily_loss = account_value * self.config.MAX_DAILY_LOSS
        return today_pnl["realized_pnl"] > -max_daily_loss

    def check_open_position_count(self, portfolio: str = "main") -> bool:
        """Return True if we can open another position."""
        params = self._get_params(portfolio)
        open_trades = self.db.get_open_trades(self.user_id, portfolio=portfolio)
        return len(open_trades) < params["max_open_positions"]

    def check_duplicate_position(self, ticker: str) -> bool:
        """Return True if we DON'T already have an open position in this ticker."""
        open_trades = self.db.get_open_trades(self.user_id)
        return not any(t["ticker"] == ticker for t in open_trades)

    def is_market_hours(self) -> bool:
        """Check if US market is currently open via Alpaca clock API."""
        return get_market_clock(self._api_key, self._secret_key).is_market_open()

    def validate_trade(
        self,
        ticker: str,
        conviction: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        account_value: float,
        portfolio: str = "main",
        action: str = "BUY",
        proposed_shares: int = 0,
        avg_daily_volume: int = 0,
        spy_change_pct: float = 0.0,
        edges_firing: int = 3,
        spread_pct: float = 0.0,
        vix_level: float = 0.0,
        sector: str = "",
        entry_price: float = 0.0,
        bypass_signal_filters: bool = False,
    ) -> dict:
        """Run all pre-trade safety checks including new risk gates. Returns pass/fail with reasons.

        When ``bypass_signal_filters`` is True (manual trade override), the
        12 signal-quality / state-based checks are auto-passed (including
        the rolling drawdown halt and risk-of-ruin expectancy gates — those
        protect the algo from itself, not the user's deliberate orders).
        The 4 hard account-protection checks always run: daily loss kill
        switch, max-open-position count, no duplicate ticker, market open.
        """
        params = self._get_params(portfolio)
        entry_value = entry_price * proposed_shares if entry_price > 0 else 0
        bypass = bypass_signal_filters
        checks = {
            "warmup_complete": True if bypass else self.check_warmup_complete(),
            "conviction_met": True if bypass else conviction >= params["min_conviction"],
            "risk_within_limit": True if bypass else stop_loss_pct <= (params["max_risk_per_trade"] * 100 * 5),
            "reward_risk_ok": (
                True if bypass
                else (
                    take_profit_pct / stop_loss_pct >= params["min_reward_risk_ratio"] - 0.01
                    if stop_loss_pct > 0
                    else False
                )
            ),
            "daily_loss_ok": self.check_daily_loss_limit(account_value),
            "position_count_ok": self.check_open_position_count(portfolio=portfolio),
            "no_duplicate": self.check_duplicate_position(ticker),
            "market_open": self.is_market_hours(),
            # Phase 1c: Portfolio-level guards — these protect the algo from
            # negative-expectancy drift; a deliberate manual order overrides them.
            "drawdown_ok": True if bypass else self.check_drawdown_halt(account_value),
            "risk_of_ruin_ok": True if bypass else self.check_risk_of_ruin(account_value, portfolio),
            # Phase 1d: Liquidity
            "liquidity_ok": True if bypass else (self.check_liquidity(proposed_shares, avg_daily_volume) if avg_daily_volume > 0 else True),
            # Phase 3: Edge validation
            "edges_ok": True if bypass else edges_firing >= self.config.MIN_EDGES_REQUIRED,
            # Phase 5a: Market circuit breaker (now with VIX)
            "market_health_ok": True if bypass else self.check_market_health(spy_change_pct, action, vix_level=vix_level),
            # Phase 5b: Earnings awareness
            "earnings_ok": True if bypass else (not self.check_earnings_proximity(ticker)["near_earnings"]),
            # Phase 6a: Bid-ask spread validation
            "spread_ok": True if bypass else (self.check_spread(spread_pct, portfolio) if spread_pct > 0 else True),
            # Phase 6b: Sector concentration
            "sector_ok": True if bypass else (self.check_sector_concentration(ticker, sector, account_value, entry_value) if sector else True),
        }

        all_passed = all(checks.values())
        failures = [k for k, v in checks.items() if not v]

        return {
            "approved": all_passed,
            "checks": checks,
            "failures": failures,
            "message": "TRADE APPROVED" if all_passed else f"TRADE BLOCKED: {', '.join(failures)}",
        }

    def is_revenge_trading(self, portfolio: str = "main") -> bool:
        """Check if recent losses suggest emotional/revenge trading."""
        recent = self.db.get_recent_trades(self.user_id, limit=5, portfolio=portfolio)
        if len(recent) < 3:
            return False
        last_3 = recent[:3]
        losses = sum(1 for t in last_3 if (t.get("pnl") or 0) < 0)
        return losses >= 3

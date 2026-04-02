# System State

**Last updated:** 2026-03-20

## Current Status: ✅ v2.0 — Risk-First Framework

### What Exists
- Full scan → research → analyze → execute pipeline
- 3-stage scanner (main + penny stock discovery)
- Rule-based DeepThink analysis with multi-edge validation
- Risk-first execution with 13 pre-trade checks
- Kelly-based position sizing with fixed-risk fallback
- Trailing stops, partial scale-out, time stops
- 5-minute exit monitoring (independent of full cycle)
- Market circuit breaker (SPY-based)
- Earnings proximity awareness (auto-close within 2 days)
- Limit orders for penny stocks, slippage tracking
- Post-trade learning loop with weekly strategy health checks
- Streamlit dashboard with Strategy Health section
- SQLite database with trailing stop and partial exit tracking

### v2.0 Changes (2026-03-20)
- **Phase 1:** Kelly position sizing, volatility adjustment, drawdown halt, risk-of-ruin check, liquidity guard
- **Phase 2:** 5-min exit checks, trailing stops, partial scale-out (1R/2R), time stops (15 days)
- **Phase 3:** Multi-edge validation (Fundamental + Technical + Sentiment), requires 2/3 edges
- **Phase 4:** Limit orders for penny stocks, pending order management, slippage tracking
- **Phase 5:** SPY circuit breaker, earnings auto-exit, post-trade learning, strategy health dashboard

### Config Additions (20 new parameters)
- `KELLY_SAFETY_MULTIPLIER`, `MAX_DRAWDOWN_HALT_PCT`, `VOLATILITY_ATR_MULTIPLIER`
- `EXIT_CHECK_INTERVAL_MINUTES`, `TRAILING_STOP_ACTIVATION_PCT`, `TRAILING_STOP_DISTANCE_PCT`
- `SCALE_OUT_ENABLED`, `SCALE_OUT_LEVELS`, `TIME_STOP_DAYS`
- `MIN_EDGES_REQUIRED`, `PENNY_LIMIT_SLIPPAGE_PCT`, `MAX_SLIPPAGE_PCT`
- `CIRCUIT_BREAKER_SPY_DROP_PCT`, `EARNINGS_EXIT_DAYS`, `EARNINGS_EXIT_MODE`

### Known Issues
- ~~Volatility adjustment uses current ATR vs estimated median (needs historical ATR storage)~~ FIXED — auto-seeds 3mo ATR history from yfinance on first encounter
- ~~VIX/breadth data not yet integrated into sentiment edge (uses news + Reddit as proxy)~~ FIXED — VIX level + sector breadth (11 S&P sector ETFs) now feed into sentiment edge evaluation
- ~~Strategy auto-pause logs warning but doesn't actually halt the portfolio yet~~ FIXED — pauses portfolio and blocks new trades, auto-resumes on recovery

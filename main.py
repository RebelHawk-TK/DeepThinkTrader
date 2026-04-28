"""DeepThinkTrader — Main orchestrator. Runs the research → analysis → execution loop."""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import datetime

import schedule

from agents.deepthink_agent import DeepThinkAgent
from agents.execution_agent import ExecutionAgent
from agents.research_agent import ResearchAgent
from agents.scanner_agent import ScannerAgent
from config import Config
from utils.database import Database
from utils.market_clock import get_market_clock
from utils.notifications import notify_strategy_paused, notify_strategy_resumed, notify_system_event
from utils.state import StateManager

# Configure logging — set LOG_FORMAT=json for structured output, LOG_LEVEL=DEBUG for verbose.
_log_file = os.path.join(os.path.dirname(__file__), "deepthinktrader.log")
from utils.logging_config import configure_logging  # noqa: E402
configure_logging(log_file=_log_file)
logger = logging.getLogger("DeepThinkTrader")


class DeepThinkTrader:
    """Per-user trading context. One instance == one user's cycle.

    Constructed fresh inside the orchestrator's per-user loop so every
    agent (research, analysis, execution, scanner) is bound to the user's
    Alpaca keys. Shared caches (StateManager, scanner watchlist) live on
    the orchestrator, not here.
    """

    def __init__(
        self,
        user_id: int,
        api_key: str,
        secret_key: str,
        state: StateManager,
        dynamic_watchlist: list[str] | None = None,
        last_scan_date: str | None = None,
    ):
        self.config = Config()
        self.db = Database()
        self.state = state
        self.user_id = user_id
        self._api_key = api_key
        self._secret_key = secret_key
        self.research = ResearchAgent(user_id=user_id, api_key=api_key, secret_key=secret_key, db=self.db)
        self.deepthink = DeepThinkAgent(user_id=user_id, db=self.db)
        self.execution = ExecutionAgent(user_id=user_id, api_key=api_key, secret_key=secret_key, db=self.db)
        self.scanner = ScannerAgent(user_id=user_id, api_key=api_key, secret_key=secret_key, db=self.db)
        self.clock = get_market_clock(api_key, secret_key)
        # Startup reconcile: close any DB-OPEN trades missing from Alpaca for
        # this user. Ghosts appear when the bot crashes mid-close.
        self.execution.reconcile_open_trades()
        # Also clean up stale pending limit orders — bot may have submitted
        # them before crashing, then never canceled them on the 30-min stale rule.
        try:
            stale = self.execution.check_pending_orders()
            if stale:
                logger.info(f"Startup pending-order check: {len(stale)} order(s) reconciled")
        except Exception as e:
            logger.error(f"Startup pending-order check failed: {e}")
        self._last_scan_date: str = last_scan_date or state.last_scan_date
        # Cache the dynamic watchlist passed in from the orchestrator so we
        # don't rebuild it per-user (sector lists are global market data).
        if dynamic_watchlist is not None:
            self._dynamic_watchlist = dynamic_watchlist
        self._paused_portfolios: set[str] = state.paused_portfolios
        self._current_regime = None  # populated by _assess_regime on each cycle

    def _assess_regime(self) -> None:
        """Classify market regime and log it. Visible, not enforced — operator
        acts on the recommendation; the bot doesn't silently rewrite its config.
        """
        try:
            from analytics.regime import classify_regime
            from brokers.alpaca import AlpacaBroker
            broker = AlpacaBroker(api_key=self._api_key, secret_key=self._secret_key)
            self._current_regime = classify_regime(broker)
            current = self.config.TRADE_MODE
            mismatch = (
                self._current_regime.recommended_mode != current
                and self._current_regime.label != "unknown"
            )
            tag = "⚠️ " if mismatch else ""
            logger.info(
                f"{tag}Regime: {self._current_regime.describe()} "
                f"(current mode: {current})"
            )
        except Exception as e:
            logger.warning(f"Regime assessment failed: {e}")
            self._current_regime = None

    def _run_scan(self) -> list[str]:
        """Run full-universe scan every cycle. Fast (~60s) thanks to batch API calls."""
        logger.info("Running full-universe scan...")
        try:
            # Rebuild dynamic sector watchlist once per day
            today = datetime.now().strftime("%Y-%m-%d")
            if self._last_scan_date != today:
                self._dynamic_watchlist = self.scanner.build_sector_watchlist()
                self._last_scan_date = today
                self.state.last_scan_date = today

            discovered = self.scanner.scan()
            if discovered:
                logger.info(f"Scanner selected {len(discovered)} tickers: {', '.join(discovered)}")
            else:
                logger.info("Scanner found no candidates this cycle")
            return discovered
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            return []

    def _run_penny_scan(self) -> list[str]:
        """Run penny stock scan ($1-$5) for high-upside candidates."""
        logger.info("Running penny stock scan...")
        try:
            discovered = self.scanner.scan_penny()
            if discovered:
                logger.info(f"Penny scanner selected {len(discovered)} tickers: {', '.join(discovered)}")
            else:
                logger.info("Penny scanner found no candidates this cycle")
            return discovered
        except Exception as e:
            logger.error(f"Penny scanner error: {e}")
            return []

    def run_cycle(self, tickers: list[str] | None = None, portfolio: str = "main") -> list[dict]:
        """Run one full research → analysis → execution cycle for all watchlist tickers."""
        label = portfolio.upper()
        # Check regime at cycle start. Cheap (~1 API call) and a good
        # forcing function for "are conditions sane right now?"
        if portfolio == "main":
            self._assess_regime()

        # Block new trades if portfolio is paused due to strategy degradation
        if portfolio in self._paused_portfolios:
            logger.warning(
                f"[{label}] Portfolio PAUSED due to strategy degradation — "
                f"skipping cycle. Exit monitoring continues. "
                f"Unpause manually or wait for next weekly health check."
            )
            # Still check exits on open positions even when paused
            exits = self.execution.check_exit_conditions()
            if exits:
                for ex in exits:
                    logger.info(f"[{label}] Position closed (paused portfolio): {ex['ticker']} — {ex['reason']}")
            return []

        if portfolio == "penny":
            discovered = self._run_penny_scan()
            base_tickers = list(tickers or discovered)
        else:
            # Run full-universe scan every cycle
            discovered = self._run_scan()

            # Use dynamic sector watchlist if available, fall back to static
            watchlist = getattr(self, "_dynamic_watchlist", None) or self.config.WATCHLIST

            # Scanner-first merge: composite-score-ranked discoveries lead, then
            # watchlist fills remaining slots. This routes top conviction plays
            # to the "high" news budget. Explicit `tickers` override bypasses both.
            if tickers:
                base_tickers = list(tickers)
            else:
                base_tickers = list(discovered) if discovered else []
                for t in watchlist:
                    if t not in base_tickers:
                        base_tickers.append(t)

        tickers = base_tickers
        results = []

        logger.info(f"{'='*60}")
        logger.info(f"[{label}] Starting cycle at {datetime.now().isoformat()}")
        if portfolio != "penny":
            watchlist = getattr(self, "_dynamic_watchlist", None) or self.config.WATCHLIST
            logger.info(f"[{label}] Watchlist: {', '.join(watchlist)}")
        if discovered:
            logger.info(f"[{label}] Scanner found: {', '.join(discovered)}")
        logger.info(f"[{label}] Total tickers this cycle: {len(tickers)}")
        logger.info(f"{'='*60}")

        # First check exit conditions on open positions
        exits = self.execution.check_exit_conditions()
        if exits:
            for ex in exits:
                logger.info(f"Position closed: {ex['ticker']} — {ex['reason']} | P&L: ${ex['pnl']:.2f}")

        for idx, ticker in enumerate(tickers):
            try:
                # Step 1: Research — priority by list position (top 5 burn full budget,
                # next 20 rotate 3 sources, tail uses cheapest source only).
                if idx < 5:
                    news_priority = "high"
                elif idx < 25:
                    news_priority = "medium"
                else:
                    news_priority = "low"

                logger.info(f"\n--- [{label}] Researching {ticker} (news={news_priority}) ---")
                report = self.research.generate_report(ticker, news_priority=news_priority)

                # Step 2: Deep analysis
                logger.info(f"--- [{label}] Analyzing {ticker} ---")
                analysis = self.deepthink.analyze(report, portfolio=portfolio)

                # Step 3: Execute (or hold)
                logger.info(f"--- [{label}] Execution check for {ticker} ---")
                result = self.execution.execute(analysis, portfolio=portfolio)
                results.append(result)

                logger.info(
                    f"[{label}] Result for {ticker}: {result['status']} "
                    f"{'— ' + result.get('message', '') if result['status'] != 'EXECUTED' else ''}"
                )

            except Exception as e:
                logger.error(f"[{label}] Error processing {ticker}: {e}", exc_info=True)
                results.append({"status": "ERROR", "ticker": ticker, "message": str(e)})

        # Summary
        executed = [r for r in results if r["status"] == "EXECUTED"]
        blocked = [r for r in results if r["status"] == "BLOCKED"]
        holds = [r for r in results if r["status"] == "HOLD"]

        logger.info(f"\n{'='*60}")
        logger.info(f"[{label}] Cycle complete: {len(executed)} executed, {len(blocked)} blocked, {len(holds)} hold")
        if executed:
            for e in executed:
                logger.info(f"  [{label}] TRADED: {e['action']} {e['shares']}x {e['ticker']} @ ${e['entry_price']}")
        logger.info(f"{'='*60}\n")

        return results

    def run_single(self, ticker: str) -> dict:
        """Run analysis on a single ticker."""
        results = self.run_cycle([ticker])
        return results[0] if results else {"status": "ERROR", "message": "No result"}

    def _is_market_hours(self) -> bool:
        """Check if US market is currently open via Alpaca clock API."""
        return self.clock.is_market_open()

    def _check_exits_only(self) -> None:
        """Phase 2a: Fast exit check — only price checks on open positions.

        Runs every EXIT_CHECK_INTERVAL_MINUTES. Does NOT run full scan/research/analyze.
        """
        if not self._is_market_hours():
            return
        try:
            open_trades = self.db.get_open_trades(self.user_id)
            if not open_trades:
                return
            tickers = [t["ticker"] for t in open_trades]
            logger.info(f"Exit check: monitoring {len(tickers)} positions ({', '.join(tickers)})")
            exits = self.execution.check_exit_conditions()
            if exits:
                for ex in exits:
                    partial = ex.get("partial", False)
                    if partial:
                        logger.info(
                            f"PARTIAL EXIT: {ex['ticker']} — {ex['reason']} | "
                            f"P&L: ${ex['pnl']:.2f} | Remaining: {ex.get('qty_remaining', '?')}"
                        )
                    else:
                        logger.info(f"EXIT: {ex['ticker']} — {ex['reason']} | P&L: ${ex['pnl']:.2f}")

            # Phase 4b: Check pending limit orders
            pending = self.execution.check_pending_orders()
            for p in pending:
                logger.info(f"Pending order update: {p['ticker']} — {p['action']}")

        except Exception as e:
            logger.error(f"Exit check error: {e}", exc_info=True)

    def _refresh_sa_emails(self) -> None:
        """Refresh Seeking Alpha email cache — runs 24/7 independent of market hours."""
        try:
            data = self.research.obsidian_sa.scan_all()
            # Force cache refresh by clearing it first
            self.research.obsidian_sa._cache = None
            self.research.obsidian_sa._cache_time = None
            data = self.research.obsidian_sa.scan_all()
            tickers = len(data)
            mentions = sum(len(v) for v in data.values())
            logger.info(f"SA email refresh: {tickers} tickers, {mentions} mentions")
        except Exception as e:
            logger.error(f"SA email refresh error: {e}")

    def _guarded_cycle(self) -> None:
        """Only run analysis cycle during market hours."""
        self.clock.log_status()
        if not self._is_market_hours():
            logger.info("Market closed — skipping cycle, will retry at next interval")
            return

        # Phase 5c: Post-trade learning — weekly auto-check (Monday)
        if datetime.now().weekday() == 0:
            self._check_strategy_health()

        # Run main portfolio
        self.run_cycle(portfolio="main")
        # Run penny stock portfolio if enabled
        if self.config.PENNY_ENABLED:
            self.run_cycle(portfolio="penny")

    def _check_strategy_health(self) -> None:
        """Phase 5c: Weekly strategy health check. Auto-pauses degraded portfolios
        for this user. Pauses are stored globally — a degraded strategy for one
        user doesn't disable it for everyone.
        """
        for portfolio in ["main", "penny"]:
            perf = self.db.get_strategy_performance(self.user_id, portfolio, days=30)
            if perf["trade_count"] < 10:
                continue
            logger.info(
                f"Strategy health [{portfolio}]: "
                f"Win rate={perf['win_rate']*100:.0f}%, "
                f"Expectancy=${perf['expectancy']:.2f}, "
                f"Profit factor={perf.get('profit_factor', 0):.2f}, "
                f"WR delta={perf['win_rate_delta']*100:+.0f}%"
            )
            if perf["win_rate_delta"] < -0.15:
                self._paused_portfolios.add(portfolio)
                self.state.pause_portfolio(portfolio)
                notify_strategy_paused(portfolio, perf["win_rate_delta"])
                logger.warning(
                    f"STRATEGY PAUSED [{portfolio}]: Win rate dropped "
                    f"{abs(perf['win_rate_delta'])*100:.0f}% from baseline — "
                    f"new trades halted until next weekly review or manual unpause"
                )
            elif portfolio in self._paused_portfolios:
                # Recovery: unpause if win rate delta has improved
                self._paused_portfolios.discard(portfolio)
                self.state.resume_portfolio(portfolio)
                notify_strategy_resumed(portfolio, perf["win_rate_delta"])
                logger.info(
                    f"STRATEGY RESUMED [{portfolio}]: Win rate delta recovered to "
                    f"{perf['win_rate_delta']*100:+.0f}% — trading re-enabled"
                )

    def start_scheduled(self) -> None:  # pragma: no cover — orchestrator owns this now
        raise NotImplementedError(
            "Per-user DeepThinkTrader no longer owns the scheduler. Use "
            "BotOrchestrator.start_scheduled() instead."
        )

    def _legacy_start_scheduled(self) -> None:
        """Start the scheduled loop — runs every RESEARCH_INTERVAL_MINUTES."""
        interval = self.config.RESEARCH_INTERVAL_MINUTES
        exit_interval = self.config.EXIT_CHECK_INTERVAL_MINUTES
        logger.info(f"DeepThinkTrader starting — cycle every {interval} minutes, exit checks every {exit_interval} minutes")
        logger.info(f"Trade mode: {self.config.TRADE_MODE.upper()}")
        logger.info(f"Max risk/trade: {self.config.MAX_RISK_PER_TRADE*100}% | "
                     f"Daily loss limit: {self.config.MAX_DAILY_LOSS*100}% | "
                     f"Min conviction: {self.config.MIN_CONVICTION}/10 | "
                     f"R:R ratio: {self.config.MIN_REWARD_RISK_RATIO}:1")
        logger.info(f"Max position: {self.config.MAX_POSITION_PCT*100:.0f}% | "
                     f"Max positions: {self.config.MAX_OPEN_POSITIONS} | "
                     f"Scanner top: {self.config.SCANNER_TOP_N}")
        logger.info(f"Risk gates: Kelly={self.config.KELLY_SAFETY_MULTIPLIER}x | "
                     f"Max drawdown halt={self.config.MAX_DRAWDOWN_HALT_PCT*100}% | "
                     f"Min edges={self.config.MIN_EDGES_REQUIRED}/3 | "
                     f"Circuit breaker=SPY {self.config.CIRCUIT_BREAKER_SPY_DROP_PCT}%")
        if self.config.PENNY_ENABLED:
            logger.info(f"Penny portfolio: ENABLED | "
                         f"Price range: ${self.config.PENNY_MIN_PRICE}-${self.config.PENNY_MAX_PRICE} | "
                         f"Min conviction: {self.config.PENNY_MIN_CONVICTION}/10 | "
                         f"Max positions: {self.config.PENNY_MAX_OPEN_POSITIONS} | "
                         f"R:R ratio: {self.config.PENNY_MIN_REWARD_RISK_RATIO}:1")

        # SA email scan runs 24/7 — fetch intelligence even outside market hours
        self._refresh_sa_emails()
        schedule.every(60).minutes.do(self._refresh_sa_emails)
        logger.info("SA email scan: every 60 minutes (24/7)")

        # Run immediately if market is open
        self._guarded_cycle()

        # Schedule full analysis cycle
        schedule.every(interval).minutes.do(self._guarded_cycle)

        # Phase 2a: Schedule fast exit checks every 5 minutes
        schedule.every(exit_interval).minutes.do(self._check_exits_only)

        # Watchdog: force-exit if main loop stalls (20-hour silent hang on 2026-04-15
        # proved we need this — process was alive but schedule.run_pending never returned).
        import threading
        self._last_tick = time.time()
        _WATCHDOG_TIMEOUT_SEC = 1800  # 30 min — full cycle with 20+ tickers + debate can take 15-20min legitimately
        def _watchdog():
            while True:
                time.sleep(60)
                stalled = time.time() - self._last_tick
                if stalled > _WATCHDOG_TIMEOUT_SEC:
                    logger.error(
                        f"WATCHDOG: main loop has not ticked for {stalled:.0f}s "
                        f"(limit {_WATCHDOG_TIMEOUT_SEC}s) — forcing exit for launchd respawn"
                    )
                    os._exit(1)
        threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()
        logger.info(f"Watchdog started (kill threshold: {_WATCHDOG_TIMEOUT_SEC}s stalled)")

        _heartbeat_counter = 0
        while True:
            self._last_tick = time.time()
            schedule.run_pending()

            # Heartbeat: log every ~2min at INFO so freezes are visible in the log
            _heartbeat_counter += 1
            if _heartbeat_counter % 4 == 0:  # Every ~2min (4 × 30s sleep)
                logger.info(f"Heartbeat: alive, {len(schedule.jobs)} jobs scheduled")

            # Sync to market open: run cycle right at 9:30 ET
            mins_to_open = self.clock.minutes_until_open()
            if mins_to_open is not None and 0 < mins_to_open <= 2:
                # Within 2 min of open — wait precisely and fire
                wait_secs = max(5, mins_to_open * 60)
                logger.info(f"Market opens in {mins_to_open:.1f} min — waiting {wait_secs:.0f}s for 9:30 ET...")
                time.sleep(wait_secs)
                self._guarded_cycle()
            elif mins_to_open is not None and 0 < mins_to_open <= 10:
                # Within 10 min of open — poll every 5s to catch the window
                time.sleep(5)
            elif mins_to_open is not None and 0 < mins_to_open <= 30:
                time.sleep(10)
            else:
                time.sleep(30)


class BotOrchestrator:
    """Multi-tenant scheduler. Iterates active users per cycle; each user
    runs their own research/analysis/execution pipeline against their own
    Alpaca paper account.
    """

    def __init__(self):
        self.config = Config()
        self.db = Database()
        self.state = StateManager()
        # Shared dynamic watchlist: the sector-rotation universe is global
        # market data, so we build it once per day and pass it to every
        # user's DeepThinkTrader rather than re-running the scan per user.
        self._dynamic_watchlist: list[str] | None = None
        self._last_scan_date: str = self.state.last_scan_date

    def _pick_service_keys(self) -> tuple[str, str] | None:
        """Return any active user's Alpaca keys for global market-data calls
        (clock, SPY snapshot, calendar). If no user has keys, bot sleeps.
        """
        from utils.secrets_vault import get_alpaca_keys
        for uid in self.db.get_active_user_ids():
            keys = get_alpaca_keys(uid)
            if keys:
                return keys
        return None

    def _guarded_cycle(self) -> None:
        """Run a cycle for every active user. Market-hours check uses the
        first active user's keys (market data is cross-user identical).
        """
        keys = self._pick_service_keys()
        if keys is None:
            logger.info("No active users with Alpaca keys — sleeping this cycle")
            return

        service_clock = get_market_clock(keys[0], keys[1])
        service_clock.log_status()
        if not service_clock.is_market_open():
            logger.info("Market closed — skipping cycle, will retry at next interval")
            return

        from utils.secrets_vault import get_alpaca_keys
        active_users = self.db.get_active_user_ids()
        if not active_users:
            logger.info("No active users this cycle")
            return

        logger.info(f"Cycle starting for {len(active_users)} user(s): {active_users}")

        # Weekly strategy health check runs once per Monday against each user
        run_health = datetime.now().weekday() == 0

        for uid in active_users:
            if not self.db.user_exists(uid):
                logger.warning(
                    f"User {uid}: returned by active_users JOIN but missing "
                    f"from users table — orphan, skipping to avoid FK violation"
                )
                continue

            user_keys = get_alpaca_keys(uid)
            if not user_keys:
                logger.info(f"User {uid}: no keys on file, skipping")
                continue

            try:
                trader = DeepThinkTrader(
                    user_id=uid,
                    api_key=user_keys[0],
                    secret_key=user_keys[1],
                    state=self.state,
                    dynamic_watchlist=self._dynamic_watchlist,
                    last_scan_date=self._last_scan_date,
                )
                if run_health:
                    trader._check_strategy_health()
                trader.run_cycle(portfolio="main")
                if self.config.PENNY_ENABLED:
                    trader.run_cycle(portfolio="penny")
                # Harvest the day's watchlist from the first user so
                # subsequent users reuse it instead of rescanning.
                wl = getattr(trader, "_dynamic_watchlist", None)
                if wl and self._dynamic_watchlist is None:
                    self._dynamic_watchlist = wl
                self._last_scan_date = trader._last_scan_date
            except Exception as e:
                logger.error(f"User {uid} cycle failed: {e}", exc_info=True)

        # Heartbeat: written only on cycle completion so external tools can
        # detect a stalled bot by checking file mtime against expected cadence.
        try:
            heartbeat_path = os.path.join(os.path.dirname(__file__), ".last_cycle.txt")
            with open(heartbeat_path, "w") as f:
                f.write(datetime.now().isoformat())
        except Exception as e:
            logger.debug(f"Heartbeat write failed: {e}")

        # Daily strategy snapshot: idempotent, only writes today's record once.
        try:
            from utils.snapshot_writer import maybe_write_daily_snapshot
            portfolios = ("main", "penny") if self.config.PENNY_ENABLED else ("main",)
            maybe_write_daily_snapshot(self.db, active_users, portfolios=portfolios)
        except Exception as e:
            logger.debug(f"Daily snapshot write failed: {e}")

    def _check_exits_only(self) -> None:
        """Fast per-user exit check — only price checks on open positions."""
        keys = self._pick_service_keys()
        if keys is None:
            return
        if not get_market_clock(keys[0], keys[1]).is_market_open():
            return

        from utils.secrets_vault import get_alpaca_keys
        for uid in self.db.get_active_user_ids():
            if not self.db.user_exists(uid):
                continue  # orphan — logged during main cycle, stay quiet here
            user_keys = get_alpaca_keys(uid)
            if not user_keys:
                continue
            try:
                trader = DeepThinkTrader(
                    user_id=uid,
                    api_key=user_keys[0],
                    secret_key=user_keys[1],
                    state=self.state,
                    dynamic_watchlist=self._dynamic_watchlist,
                    last_scan_date=self._last_scan_date,
                )
                trader._check_exits_only()
            except Exception as e:
                logger.error(f"User {uid} exit check failed: {e}", exc_info=True)

    def _refresh_sa_emails(self) -> None:
        """Shared Seeking Alpha refresh — emails are global intel, not per-user."""
        keys = self._pick_service_keys()
        if keys is None:
            return
        try:
            # Build a throwaway ResearchAgent just to access the SA scraper.
            # Any user's keys work — SA scanning doesn't hit Alpaca.
            first_uid = self.db.get_active_user_ids()[0]
            trader = DeepThinkTrader(
                user_id=first_uid,
                api_key=keys[0],
                secret_key=keys[1],
                state=self.state,
            )
            data = trader.research.obsidian_sa.scan_all()
            trader.research.obsidian_sa._cache = None
            trader.research.obsidian_sa._cache_time = None
            data = trader.research.obsidian_sa.scan_all()
            tickers = len(data)
            mentions = sum(len(v) for v in data.values())
            logger.info(f"SA email refresh: {tickers} tickers, {mentions} mentions")
        except Exception as e:
            logger.error(f"SA email refresh error: {e}")

    def start_scheduled(self) -> None:
        """Scheduled loop — runs every RESEARCH_INTERVAL_MINUTES."""
        interval = self.config.RESEARCH_INTERVAL_MINUTES
        exit_interval = self.config.EXIT_CHECK_INTERVAL_MINUTES
        logger.info(
            f"DeepThinkTrader (multi-tenant) starting — cycle every {interval} "
            f"minutes, exit checks every {exit_interval} minutes"
        )
        logger.info(f"Trade mode: {self.config.TRADE_MODE.upper()}")
        self._refresh_sa_emails()
        schedule.every(60).minutes.do(self._refresh_sa_emails)

        self._guarded_cycle()
        schedule.every(interval).minutes.do(self._guarded_cycle)
        schedule.every(exit_interval).minutes.do(self._check_exits_only)

        import threading
        self._last_tick = time.time()
        _WATCHDOG_TIMEOUT_SEC = 1800

        def _watchdog():
            while True:
                time.sleep(60)
                stalled = time.time() - self._last_tick
                if stalled > _WATCHDOG_TIMEOUT_SEC:
                    logger.error(
                        f"WATCHDOG: main loop has not ticked for {stalled:.0f}s "
                        f"(limit {_WATCHDOG_TIMEOUT_SEC}s) — forcing exit"
                    )
                    os._exit(1)

        threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()
        logger.info(f"Watchdog started (kill threshold: {_WATCHDOG_TIMEOUT_SEC}s stalled)")

        _heartbeat_counter = 0
        while True:
            self._last_tick = time.time()
            schedule.run_pending()
            _heartbeat_counter += 1
            if _heartbeat_counter % 4 == 0:
                logger.info(f"Heartbeat: alive, {len(schedule.jobs)} jobs scheduled")

            keys = self._pick_service_keys()
            mins_to_open = None
            if keys is not None:
                mins_to_open = get_market_clock(keys[0], keys[1]).minutes_until_open()
            if mins_to_open is not None and 0 < mins_to_open <= 2:
                wait_secs = max(5, mins_to_open * 60)
                logger.info(f"Market opens in {mins_to_open:.1f} min — waiting {wait_secs:.0f}s...")
                time.sleep(wait_secs)
                self._guarded_cycle()
            elif mins_to_open is not None and 0 < mins_to_open <= 10:
                time.sleep(5)
            elif mins_to_open is not None and 0 < mins_to_open <= 30:
                time.sleep(10)
            else:
                time.sleep(30)


def main():
    # Validate configuration before doing anything
    errors, warnings = Config.validate()
    for w in warnings:
        logger.warning(f"Config warning: {w}")
    if errors:
        for e in errors:
            logger.error(f"Config error: {e}")
        logger.error("Fix configuration errors above before starting. Exiting.")
        sys.exit(1)
    logger.info("Configuration validated OK")

    orchestrator = BotOrchestrator()

    notify_system_event(f"Started (mode: {Config.TRADE_MODE})")

    def _shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} — saving state and shutting down")
        orchestrator.state.save()
        notify_system_event(f"Shutting down ({sig_name})")
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
    except ValueError:
        # cloud_run_entrypoint.py runs main() on a daemon thread where
        # signal.signal is unavailable. The entrypoint's HTTPServer in the
        # main thread handles SIGTERM already, so skipping here is safe.
        logger.info("signal handlers not registered (running off main thread)")

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "once":
            orchestrator._guarded_cycle()
        elif command in {"ticker", "scan", "penny"}:
            # Per-user dev subcommands. Resolve user from --user-email if
            # given, otherwise fall back to the first active user (dev setup
            # has a single user, so this "just works" without a flag).
            _resolve_user_and_run_cli(orchestrator, command)
        else:
            print("Usage:")
            print("  python main.py                       # Start scheduled loop")
            print("  python main.py once                  # One cycle across all users")
            print("  python main.py ticker NVDA           # Analyze single ticker")
            print("  python main.py scan                  # Run scanner, show results")
            print("  python main.py penny [scan]          # Penny cycle (or scan only)")
            print("  (append --user-email foo@bar.com to target a specific user)")
    else:
        orchestrator.start_scheduled()


def _resolve_user_and_run_cli(orchestrator: "BotOrchestrator", command: str) -> None:
    """Back per-user CLI subcommands with real user context.

    --user-email picks a specific user; without it, we use the first
    active user (fine for single-user dev). Bails with a clear message
    when no active user exists.
    """
    from utils.secrets_vault import get_alpaca_keys, user_id_for_email

    # Parse --user-email out of argv; collect remaining positional args.
    argv = sys.argv[2:]
    user_email: str | None = None
    positional: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--user-email" and i + 1 < len(argv):
            user_email = argv[i + 1]
            i += 2
        else:
            positional.append(argv[i])
            i += 1

    if user_email:
        uid = user_id_for_email(user_email)
        if uid is None:
            print(f"No user row for {user_email}")
            return
    else:
        active = orchestrator.db.get_active_user_ids()
        if not active:
            print("No active users with Alpaca keys — add a user via the dashboard.")
            return
        uid = active[0]

    keys = get_alpaca_keys(uid)
    if keys is None:
        print(f"User {uid} has no Alpaca keys on file.")
        return

    trader = DeepThinkTrader(
        user_id=uid,
        api_key=keys[0],
        secret_key=keys[1],
        state=orchestrator.state,
    )

    if command == "ticker":
        if not positional:
            print("Usage: python main.py ticker SYMBOL")
            return
        trader.run_single(positional[0].upper())
    elif command == "scan":
        discovered = trader.scanner.scan()
        if discovered:
            print(f"Discovered {len(discovered)} trending tickers:")
            for t in discovered:
                print(f"  {t}")
        else:
            print("No trending tickers found (market may be closed)")
    elif command == "penny":
        if positional and positional[0] == "scan":
            discovered = trader.scanner.scan_penny()
            if discovered:
                print(f"Penny scanner found {len(discovered)} candidates:")
                for t in discovered:
                    print(f"  {t}")
            else:
                print("No penny stock candidates found")
        else:
            trader.run_cycle(portfolio="penny")


if __name__ == "__main__":
    main()

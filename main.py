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

# Configure logging with rotation (10MB max, 5 backups)
_log_file = os.path.join(os.path.dirname(__file__), "deepthinktrader.log")
_file_handler = logging.handlers.RotatingFileHandler(
    _log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
# Set restrictive permissions on log file
try:
    os.chmod(_log_file, 0o600)
except OSError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        _file_handler,
    ],
)
logger = logging.getLogger("DeepThinkTrader")


class DeepThinkTrader:
    def __init__(self):
        self.config = Config()
        self.db = Database()
        self.state = StateManager()
        self.research = ResearchAgent(self.db)
        self.deepthink = DeepThinkAgent(self.db)
        logger.info("Using rule-based DeepThink analysis")
        self.execution = ExecutionAgent(self.db)
        self.scanner = ScannerAgent(self.db)
        self.clock = get_market_clock()
        self._last_scan_date: str = self.state.last_scan_date
        self._paused_portfolios: set[str] = self.state.paused_portfolios

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

            # Merge watchlist + discovered (no duplicates)
            base_tickers = list(tickers or watchlist)
            if discovered:
                for t in discovered:
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

        for ticker in tickers:
            try:
                # Step 1: Research
                logger.info(f"\n--- [{label}] Researching {ticker} ---")
                report = self.research.generate_report(ticker)

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
            open_trades = self.db.get_open_trades()
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
        """Phase 5c: Weekly strategy health check. Auto-pauses degraded portfolios."""
        for portfolio in ["main", "penny"]:
            perf = self.db.get_strategy_performance(portfolio, days=30)
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

    def start_scheduled(self) -> None:
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

        while True:
            schedule.run_pending()

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

    trader = DeepThinkTrader()

    notify_system_event(f"Started (mode: {Config.TRADE_MODE})")

    # Graceful shutdown: save state on SIGTERM/SIGINT
    def _shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} — saving state and shutting down")
        trader.state.save()
        notify_system_event(f"Shutting down ({sig_name})")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "once":
            # Run single cycle and exit
            trader.run_cycle()
        elif command == "ticker" and len(sys.argv) > 2:
            # Analyze single ticker
            ticker = sys.argv[2].upper()
            trader.run_single(ticker)
        elif command == "scan":
            # Run scanner only and show results
            discovered = trader.scanner.scan()
            if discovered:
                print(f"Discovered {len(discovered)} trending tickers:")
                for t in discovered:
                    print(f"  {t}")
            else:
                print("No trending tickers found (market may be closed)")
        elif command == "penny":
            # Run penny stock cycle only
            if len(sys.argv) > 2 and sys.argv[2] == "scan":
                discovered = trader.scanner.scan_penny()
                if discovered:
                    print(f"Penny scanner found {len(discovered)} candidates:")
                    for t in discovered:
                        print(f"  {t}")
                else:
                    print("No penny stock candidates found")
            else:
                trader.run_cycle(portfolio="penny")
        else:
            print("Usage:")
            print("  python main.py              # Start scheduled loop")
            print("  python main.py once         # Run one cycle and exit")
            print("  python main.py ticker NVDA  # Analyze single ticker")
            print("  python main.py scan         # Scan for trending stocks")
            print("  python main.py penny        # Run penny stock cycle once")
            print("  python main.py penny scan   # Scan for penny stocks only")
    else:
        # Default: start scheduled loop
        trader.start_scheduled()


if __name__ == "__main__":
    main()

"""DeepThinkTrader — Main orchestrator. Runs the research → analysis → execution loop."""

from __future__ import annotations

import logging
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("deepthinktrader.log"),
    ],
)
logger = logging.getLogger("DeepThinkTrader")


class DeepThinkTrader:
    def __init__(self):
        self.config = Config()
        self.db = Database()
        self.research = ResearchAgent(self.db)
        self.deepthink = DeepThinkAgent(self.db)
        logger.info("Using rule-based DeepThink analysis")
        self.execution = ExecutionAgent(self.db)
        self.scanner = ScannerAgent(self.db)
        self._last_scan_date: str = ""

    def _run_scan(self) -> list[str]:
        """Run full-universe scan every cycle. Fast (~60s) thanks to batch API calls."""
        logger.info("Running full-universe scan...")
        try:
            # Rebuild dynamic sector watchlist once per day
            today = datetime.now().strftime("%Y-%m-%d")
            if self._last_scan_date != today:
                self._dynamic_watchlist = self.scanner.build_sector_watchlist()
                self._last_scan_date = today

            discovered = self.scanner.scan()
            if discovered:
                logger.info(f"Scanner selected {len(discovered)} tickers: {', '.join(discovered)}")
            else:
                logger.info("Scanner found no candidates this cycle")
            return discovered
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            return []

    def run_cycle(self, tickers: list[str] | None = None) -> list[dict]:
        """Run one full research → analysis → execution cycle for all watchlist tickers."""
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
        logger.info(f"Starting cycle at {datetime.now().isoformat()}")
        logger.info(f"Watchlist: {', '.join(watchlist)}")
        if discovered:
            logger.info(f"Scanner additions: {', '.join(discovered)}")
        logger.info(f"Total tickers this cycle: {len(tickers)}")
        logger.info(f"{'='*60}")

        # First check exit conditions on open positions
        exits = self.execution.check_exit_conditions()
        if exits:
            for ex in exits:
                logger.info(f"Position closed: {ex['ticker']} — {ex['reason']} | P&L: ${ex['pnl']:.2f}")

        for ticker in tickers:
            try:
                # Step 1: Research
                logger.info(f"\n--- Researching {ticker} ---")
                report = self.research.generate_report(ticker)

                # Step 2: Deep analysis
                logger.info(f"--- Analyzing {ticker} ---")
                analysis = self.deepthink.analyze(report)

                # Step 3: Execute (or hold)
                logger.info(f"--- Execution check for {ticker} ---")
                result = self.execution.execute(analysis)
                results.append(result)

                logger.info(
                    f"Result for {ticker}: {result['status']} "
                    f"{'— ' + result.get('message', '') if result['status'] != 'EXECUTED' else ''}"
                )

            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}", exc_info=True)
                results.append({"status": "ERROR", "ticker": ticker, "message": str(e)})

        # Summary
        executed = [r for r in results if r["status"] == "EXECUTED"]
        blocked = [r for r in results if r["status"] == "BLOCKED"]
        holds = [r for r in results if r["status"] == "HOLD"]

        logger.info(f"\n{'='*60}")
        logger.info(f"Cycle complete: {len(executed)} executed, {len(blocked)} blocked, {len(holds)} hold")
        if executed:
            for e in executed:
                logger.info(f"  TRADED: {e['action']} {e['shares']}x {e['ticker']} @ ${e['entry_price']}")
        logger.info(f"{'='*60}\n")

        return results

    def run_single(self, ticker: str) -> dict:
        """Run analysis on a single ticker."""
        results = self.run_cycle([ticker])
        return results[0] if results else {"status": "ERROR", "message": "No result"}

    def _is_market_hours(self) -> bool:
        """Check if US market is currently open."""
        now = datetime.now()
        if now.weekday() > 4:
            return False
        market_minutes = now.hour * 60 + now.minute
        return 9 * 60 + 30 <= market_minutes < 16 * 60

    def _guarded_cycle(self) -> None:
        """Only run analysis cycle during market hours."""
        if not self._is_market_hours():
            logger.info("Market closed — skipping cycle, will retry at next interval")
            return
        self.run_cycle()

    def start_scheduled(self) -> None:
        """Start the scheduled loop — runs every RESEARCH_INTERVAL_MINUTES."""
        interval = self.config.RESEARCH_INTERVAL_MINUTES
        logger.info(f"DeepThinkTrader starting — cycle every {interval} minutes")
        logger.info(f"Trade mode: {self.config.TRADE_MODE.upper()}")
        logger.info(f"Max risk/trade: {self.config.MAX_RISK_PER_TRADE*100}% | "
                     f"Daily loss limit: {self.config.MAX_DAILY_LOSS*100}% | "
                     f"Min conviction: {self.config.MIN_CONVICTION}/10 | "
                     f"R:R ratio: {self.config.MIN_REWARD_RISK_RATIO}:1")
        logger.info(f"Max position: {self.config.MAX_POSITION_PCT*100:.0f}% | "
                     f"Max positions: {self.config.MAX_OPEN_POSITIONS} | "
                     f"Scanner top: {self.config.SCANNER_TOP_N}")

        # Run immediately if market is open
        self._guarded_cycle()

        # Then schedule
        schedule.every(interval).minutes.do(self._guarded_cycle)

        while True:
            schedule.run_pending()
            time.sleep(30)


def main():
    trader = DeepThinkTrader()

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
        else:
            print("Usage:")
            print("  python main.py              # Start scheduled loop")
            print("  python main.py once         # Run one cycle and exit")
            print("  python main.py ticker NVDA  # Analyze single ticker")
            print("  python main.py scan         # Scan for trending stocks")
    else:
        # Default: start scheduled loop
        trader.start_scheduled()


if __name__ == "__main__":
    main()

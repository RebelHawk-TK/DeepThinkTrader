"""DeepThinkTrader — Main orchestrator. Runs the research → analysis → execution loop."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime

import schedule

from agents.deepthink_agent import DeepThinkAgent
from agents.ai_deepthink_agent import AIDeepThinkAgent
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
        # Use AI-powered analysis if Anthropic key is set, otherwise rule-based
        if self.config.ANTHROPIC_API_KEY:
            self.deepthink = AIDeepThinkAgent(self.db)
            logger.info("Using AI-powered DeepThink (Claude API)")
        else:
            self.deepthink = DeepThinkAgent(self.db)
            logger.info("Using rule-based DeepThink (no Anthropic key)")
        self.execution = ExecutionAgent(self.db)
        self.scanner = ScannerAgent(self.db)
        self._last_scan_date: str = ""

    def _run_daily_scan(self) -> list[str]:
        """Run the market scanner once per day to discover trending tickers."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_scan_date == today:
            return []

        logger.info("Running daily market scan for trending stocks...")
        try:
            discovered = self.scanner.scan()
            self._last_scan_date = today
            if discovered:
                logger.info(f"Scanner discovered {len(discovered)} tickers: {', '.join(discovered)}")
            else:
                logger.info("Scanner found no new candidates today")
            return discovered
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            self._last_scan_date = today
            return []

    def run_cycle(self, tickers: list[str] | None = None) -> list[dict]:
        """Run one full research → analysis → execution cycle for all watchlist tickers."""
        # Run daily scan to discover trending stocks
        discovered = self._run_daily_scan()

        # Merge watchlist + discovered (no duplicates)
        base_tickers = list(tickers or self.config.WATCHLIST)
        if discovered:
            for t in discovered:
                if t not in base_tickers:
                    base_tickers.append(t)

        tickers = base_tickers
        results = []

        logger.info(f"{'='*60}")
        logger.info(f"Starting cycle at {datetime.now().isoformat()}")
        logger.info(f"Watchlist: {', '.join(self.config.WATCHLIST)}")
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
            # Skip if already analyzed recently (within research interval)
            if self.db.was_recently_analyzed(ticker, minutes=self.config.RESEARCH_INTERVAL_MINUTES - 5):
                logger.info(f"Skipping {ticker} — already analyzed recently")
                continue

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

    def start_scheduled(self) -> None:
        """Start the scheduled loop — runs every RESEARCH_INTERVAL_MINUTES."""
        interval = self.config.RESEARCH_INTERVAL_MINUTES
        logger.info(f"DeepThinkTrader starting — cycle every {interval} minutes")
        logger.info(f"Watchlist: {', '.join(self.config.WATCHLIST)}")
        logger.info(f"Account size: ${self.config.ACCOUNT_SIZE:,.0f}")
        logger.info(f"Max risk/trade: {self.config.MAX_RISK_PER_TRADE*100}%")
        logger.info(f"Min conviction: {self.config.MIN_CONVICTION}/10")

        # Run immediately on startup
        self.run_cycle()

        # Then schedule
        schedule.every(interval).minutes.do(self.run_cycle)

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

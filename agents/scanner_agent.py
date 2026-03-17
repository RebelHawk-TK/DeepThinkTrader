"""Scanner Agent — Discovers trending, high-volume, and top-moving stocks daily.

Sources:
- Alpaca most active / top movers API
- Yahoo Finance trending tickers
- NewsAPI top mentioned tickers

Feeds discovered tickers into the main trading pipeline.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta

import requests as http_requests
import yfinance as yf
from newsapi import NewsApiClient

from config import Config
from utils.database import Database

logger = logging.getLogger(__name__)

# Well-known large-cap tickers to filter against (avoid penny stocks)
VALID_EXCHANGES = {"NYSE", "NASDAQ", "ARCA", "BATS", "AMEX", "IEX"}

# Skip inverse ETFs, leveraged products, and volatility instruments
SKIP_TICKERS = {
    # Leveraged bull/bear
    "SQQQ", "TQQQ", "UVXY", "SPXS", "SPXL", "SOXL", "SOXS",
    "LABU", "LABD", "NUGT", "DUST", "JNUG", "JDST", "TVIX",
    # Inverse ETFs (go up when market goes down — confuses bullish signals)
    "SPDN", "SH", "PSQ", "DOG", "RWM", "SDS", "QID", "SDOW",
    "SRTY", "SARK", "HIBS", "BERZ",
    # 3x leveraged (too volatile for bot)
    "TZA", "TNA", "UPRO", "SPXU", "TECL", "TECS", "FAS", "FAZ",
    "ERX", "ERY", "CURE", "DRIP", "GUSH", "NAIL", "DRV",
    # Volatility products
    "UVIX", "SVIX", "VXX", "VIXY", "SVXY",
    # Leveraged single-stock ETFs
    "TSLL", "TSLG", "NVDL", "NVDS", "AMDL",
}

# Minimum price and volume thresholds
MIN_PRICE = 5.0
MAX_PRICE = 5000.0
MIN_AVG_VOLUME = 200_000


class ScannerAgent:
    def __init__(self, db: Database | None = None):
        self.config = Config()
        self.db = db or Database()
        self._session = http_requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": self.config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": self.config.ALPACA_SECRET_KEY,
        })
        self._data_url = "https://data.alpaca.markets"
        self._trading_url = self.config.ALPACA_BASE_URL

    def _capture_request_id(self, response: http_requests.Response, endpoint: str) -> str | None:
        request_id = response.headers.get("X-Request-ID")
        if request_id:
            self.db.save_request_id(
                request_id=request_id,
                endpoint=endpoint,
                method="GET",
                http_status=response.status_code,
                success=response.ok,
            )
        return request_id

    def scan_most_active(self, top_n: int = 50) -> list[dict]:
        """Get most active stocks by volume from Alpaca screener."""
        endpoint = "/v1beta1/screener/stocks/most-actives"
        try:
            resp = self._session.get(
                f"{self._data_url}{endpoint}",
                params={"by": "volume", "top": top_n},
            )
            self._capture_request_id(resp, endpoint)
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("most_actives", []):
                ticker = item.get("symbol", "")
                if ticker in SKIP_TICKERS:
                    continue
                results.append({
                    "ticker": ticker,
                    "volume": item.get("volume", 0),
                    "trade_count": item.get("trade_count", 0),
                    "source": "alpaca_most_active",
                })
            logger.info(f"Scanner: {len(results)} most active stocks found")
            return results
        except Exception as e:
            logger.error(f"Scanner most-active error: {e}")
            return []

    def scan_top_movers(self, top_n: int = 50) -> list[dict]:
        """Get top gainers and losers from Alpaca screener."""
        results = []
        for direction in ["gainers", "losers"]:
            endpoint = f"/v1beta1/screener/stocks/movers"
            try:
                resp = self._session.get(
                    f"{self._data_url}{endpoint}",
                    params={"top": top_n},
                )
                self._capture_request_id(resp, endpoint)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get(direction, []):
                    ticker = item.get("symbol", "")
                    if ticker in SKIP_TICKERS:
                        continue
                    change = item.get("percent_change", 0)
                    results.append({
                        "ticker": ticker,
                        "change_pct": change,
                        "price": item.get("price", 0),
                        "source": f"alpaca_{direction}",
                    })
            except Exception as e:
                logger.error(f"Scanner {direction} error: {e}")

        logger.info(f"Scanner: {len(results)} top movers found")
        return results

    def scan_news_trending(self, top_n: int = 20) -> list[dict]:
        """Find most-mentioned tickers in today's financial news."""
        try:
            newsapi = NewsApiClient(api_key=self.config.NEWSAPI_KEY)
            from_date = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d")
            response = newsapi.get_everything(
                q="stock OR shares OR trading OR earnings",
                from_param=from_date,
                language="en",
                sort_by="popularity",
                page_size=100,
            )

            # Extract ticker-like symbols from headlines
            ticker_pattern = re.compile(r'\b([A-Z]{2,5})\b')
            common_words = {
                "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
                "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "NEW",
                "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "HIS",
                "HOW", "ITS", "MAY", "SAY", "SHE", "TWO", "USE", "CEO",
                "IPO", "FDA", "SEC", "GDP", "CPI", "ETF", "USA", "NYSE",
                "CEO", "CFO", "COO", "CTO", "WITH", "THIS", "THAT",
                "FROM", "HAVE", "BEEN", "WILL", "MORE", "WHEN", "WHAT",
                "ALSO", "JUST", "OVER", "THAN", "THEM", "SOME", "INTO",
                "YEAR", "MOST", "MUCH", "VERY", "AFTER", "DOWN",
                "ONLY", "BACK", "SAYS", "SAID", "READ", "US", "AI",
            }

            mentions = Counter()
            for article in response.get("articles", []):
                title = article.get("title", "") or ""
                found = ticker_pattern.findall(title)
                for t in found:
                    if t not in common_words and len(t) >= 2:
                        mentions[t] += 1

            results = []
            for ticker, count in mentions.most_common(top_n):
                if count >= 1:  # At least 1 mention
                    results.append({
                        "ticker": ticker,
                        "mention_count": count,
                        "source": "news_trending",
                    })

            logger.info(f"Scanner: {len(results)} news-trending tickers found")
            return results
        except Exception as e:
            logger.error(f"Scanner news error: {e}")
            return []

    def _load_tradeable_assets(self) -> set[str]:
        """Load all tradeable assets from Alpaca in one API call."""
        if hasattr(self, "_tradeable_cache"):
            return self._tradeable_cache

        try:
            resp = self._session.get(
                f"{self._trading_url}/v2/assets",
                params={"status": "active", "asset_class": "us_equity"},
            )
            self._capture_request_id(resp, "/v2/assets")
            resp.raise_for_status()
            assets = resp.json()
            self._tradeable_cache = {
                a["symbol"] for a in assets
                if a.get("tradable") and a.get("exchange") in VALID_EXCHANGES
            }
            logger.info(f"Scanner: loaded {len(self._tradeable_cache)} tradeable assets from Alpaca")
            return self._tradeable_cache
        except Exception as e:
            logger.error(f"Failed to load tradeable assets: {e}")
            self._tradeable_cache = set()
            return self._tradeable_cache

    def validate_ticker(self, ticker: str) -> bool:
        """Check if a ticker is tradeable using cached asset list."""
        tradeable = self._load_tradeable_assets()
        return ticker in tradeable

    def filter_candidates(self, candidates: list[dict]) -> list[str]:
        """Deduplicate, validate, and filter candidates by price/volume."""
        # Deduplicate and score by number of sources
        ticker_scores = Counter()
        for c in candidates:
            ticker_scores[c["ticker"]] += 1

        # Sort by number of sources mentioning them (multi-source = stronger signal)
        ranked = [t for t, _ in ticker_scores.most_common(150)]

        # Remove tickers already in base watchlist (they'll be added separately)
        existing = set(self.config.WATCHLIST)
        ranked = [t for t in ranked if t not in existing and "." not in t]

        # Known-good tickers that don't need validation
        known_good = {c["ticker"] for c in candidates if c.get("source") == "popular_stocks"}

        # Validate and filter
        valid = []
        for ticker in ranked:
            if ticker in SKIP_TICKERS:
                continue

            # Skip snapshot check for known popular stocks — just validate tradeable
            if ticker in known_good:
                if self.validate_ticker(ticker):
                    valid.append(ticker)
                if len(valid) >= 95:
                    break
                continue

            if not self.validate_ticker(ticker):
                continue

            # Quick price/volume check via Alpaca snapshot (scanner-discovered only)
            try:
                resp = self._session.get(
                    f"{self._data_url}/v2/stocks/{ticker}/snapshot",
                    params={"feed": "iex"},
                )
                self._capture_request_id(resp, f"/v2/stocks/{ticker}/snapshot")
                if not resp.ok:
                    continue
                snap = resp.json()
                bar = snap.get("dailyBar") or snap.get("latestBar", {})
                price = bar.get("c", 0)
                volume = bar.get("v", 0)

                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                if volume < MIN_AVG_VOLUME:
                    continue

                valid.append(ticker)
                if len(valid) >= 95:  # Cap at 95 discovered + 5 watchlist = 100
                    break
            except Exception:
                continue

        logger.info(f"Scanner: {len(valid)} validated tickers: {valid}")
        return valid

    def scan_sp500_and_popular(self) -> list[dict]:
        """Add well-known large/mid-cap stocks to ensure broad coverage."""
        # Top 100 most-traded US stocks by typical daily volume
        popular = [
            "AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "BRK.B", "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD",
            "XOM", "CVX", "LLY", "ABBV", "MRK", "PFE", "KO", "PEP", "COST",
            "AVGO", "TMO", "MCD", "CSCO", "ACN", "ABT", "DHR", "TXN", "NEE",
            "AMD", "NFLX", "ADBE", "CRM", "INTC", "QCOM", "AMAT", "INTU",
            "AMGN", "ISRG", "BKNG", "MDLZ", "GILD", "ADI", "REGN", "VRTX",
            "BA", "CAT", "GE", "MMM", "HON", "UPS", "RTX", "LMT", "DE",
            "SBUX", "NKE", "LOW", "TGT", "F", "GM", "RIVN", "LCID",
            "PYPL", "SQ", "SHOP", "COIN", "ROKU", "SNAP", "PINS", "UBER",
            "ABNB", "DKNG", "PLTR", "SOFI", "HOOD", "MARA", "RIOT", "CLSK",
            "DIS", "CMCSA", "T", "VZ", "TMUS",
            "GS", "MS", "C", "BAC", "WFC", "SCHW",
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK",
        ]
        results = []
        for ticker in popular:
            results.append({
                "ticker": ticker,
                "source": "popular_stocks",
            })
        logger.info(f"Scanner: {len(results)} popular/large-cap stocks added")
        return results

    def scan(self) -> list[str]:
        """Run full scan: gather candidates from all sources, filter, return up to 95 tickers."""
        logger.info("Scanner: Starting market scan for up to 100 stocks...")

        # Phase 1: scanner-discovered (trending, movers, news)
        scanner_candidates = []
        scanner_candidates.extend(self.scan_most_active())
        scanner_candidates.extend(self.scan_top_movers())
        scanner_candidates.extend(self.scan_news_trending())

        discovered = self.filter_candidates(scanner_candidates) if scanner_candidates else []
        logger.info(f"Scanner phase 1: {len(discovered)} trending/active stocks")

        # Phase 2: fill remaining slots with popular large-cap stocks
        existing = set(self.config.WATCHLIST) | set(discovered)
        tradeable = self._load_tradeable_assets()
        popular = self.scan_sp500_and_popular()

        for p in popular:
            if len(discovered) >= 95:
                break
            ticker = p["ticker"]
            if ticker not in existing and ticker in tradeable:
                discovered.append(ticker)
                existing.add(ticker)

        logger.info(
            f"Scanner complete: {len(discovered)} total stocks "
            f"(+ {len(self.config.WATCHLIST)} watchlist = {len(discovered) + len(self.config.WATCHLIST)})"
        )
        return discovered

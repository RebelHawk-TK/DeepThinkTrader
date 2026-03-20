"""Scanner Agent — Smart 3-stage funnel for discovering high-quality trade candidates.

Stage 1: Discovery — Alpaca screener (most active, movers) + news trending + popular stocks
Stage 2: Batch Pre-Screen — Multi-symbol snapshots + weekly bars for relative strength,
         weekly trend, volume confirmation. Scores and ranks candidates.
Stage 3: Output top N candidates for deep analysis by ResearchAgent + DeepThinkAgent.

This replaces the old approach of sending 100+ tickers through expensive per-ticker
analysis (~60s each via Twelve Data). Now only ~20 high-quality candidates reach deep analysis.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta

import requests as http_requests
from newsapi import NewsApiClient

from config import Config
from utils.alpaca_data import AlpacaMarketData
from utils.database import Database

logger = logging.getLogger(__name__)

VALID_EXCHANGES = {"NYSE", "NASDAQ", "ARCA", "BATS", "AMEX", "IEX"}

SKIP_TICKERS = {
    # Leveraged bull/bear
    "SQQQ", "TQQQ", "UVXY", "SPXS", "SPXL", "SOXL", "SOXS",
    "LABU", "LABD", "NUGT", "DUST", "JNUG", "JDST", "TVIX",
    # Inverse ETFs
    "SPDN", "SH", "PSQ", "DOG", "RWM", "SDS", "QID", "SDOW",
    "SRTY", "SARK", "HIBS", "BERZ",
    # 3x leveraged
    "TZA", "TNA", "UPRO", "SPXU", "TECL", "TECS", "FAS", "FAZ",
    "ERX", "ERY", "CURE", "DRIP", "GUSH", "NAIL", "DRV",
    # Volatility products
    "UVIX", "SVIX", "VXX", "VIXY", "SVXY",
    # Leveraged single-stock ETFs
    "TSLL", "TSLG", "NVDL", "NVDS", "AMDL", "TSDD",
}

MIN_PRICE = 5.0
MAX_PRICE = 5000.0
MIN_AVG_VOLUME = 200_000

# Popular large/mid-cap stocks for broad coverage
POPULAR_STOCKS = [
    "AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD",
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
]

# Sector representatives — top liquid stocks per sector for dynamic watchlist
SECTOR_POOL = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "AMD", "CRM", "ADBE", "INTC", "QCOM", "NFLX"],
    "Healthcare": ["UNH", "LLY", "ABBV", "MRK", "PFE", "AMGN", "ISRG", "REGN", "VRTX", "GILD"],
    "Financials": ["JPM", "V", "MA", "GS", "MS", "BAC", "WFC", "SCHW", "C", "PYPL"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "USO"],
    "Consumer": ["AMZN", "TSLA", "HD", "MCD", "SBUX", "NKE", "COST", "WMT", "TGT", "LOW"],
    "Industrials": ["CAT", "GE", "HON", "BA", "RTX", "LMT", "DE", "UPS", "UNP", "MMM"],
    "Communication": ["META", "GOOG", "DIS", "CMCSA", "T", "VZ", "TMUS", "SNAP", "PINS", "ROKU"],
}


class ScannerAgent:
    def __init__(self, db: Database | None = None):
        self.config = Config()
        self.db = db or Database()
        self.alpaca_data = AlpacaMarketData(self.db)
        self._session = self.alpaca_data._session
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

    # ── Stage 1: Discovery ──────────────────────────────────────────

    def _discover_most_active(self, top_n: int = 50) -> list[dict]:
        endpoint = "/v1beta1/screener/stocks/most-actives"
        try:
            resp = self._session.get(
                f"{self._data_url}{endpoint}",
                params={"by": "volume", "top": top_n},
            )
            self._capture_request_id(resp, endpoint)
            resp.raise_for_status()
            results = []
            for item in resp.json().get("most_actives", []):
                ticker = item.get("symbol", "")
                if ticker and ticker not in SKIP_TICKERS:
                    results.append({"ticker": ticker, "source": "most_active"})
            logger.info(f"Scanner: {len(results)} most active stocks")
            return results
        except Exception as e:
            logger.error(f"Scanner most-active error: {e}")
            return []

    def _discover_top_movers(self, top_n: int = 50) -> list[dict]:
        results = []
        endpoint = "/v1beta1/screener/stocks/movers"
        try:
            resp = self._session.get(
                f"{self._data_url}{endpoint}", params={"top": top_n},
            )
            self._capture_request_id(resp, endpoint)
            resp.raise_for_status()
            data = resp.json()
            for direction in ("gainers", "losers"):
                for item in data.get(direction, []):
                    ticker = item.get("symbol", "")
                    if ticker and ticker not in SKIP_TICKERS:
                        results.append({"ticker": ticker, "source": f"movers_{direction}"})
        except Exception as e:
            logger.error(f"Scanner movers error: {e}")
        logger.info(f"Scanner: {len(results)} top movers")
        return results

    def _discover_news_trending(self, top_n: int = 20) -> list[dict]:
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
            ticker_pattern = re.compile(r'\b([A-Z]{2,5})\b')
            common_words = {
                "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
                "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "NEW",
                "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "HIS",
                "HOW", "ITS", "MAY", "SAY", "SHE", "TWO", "USE", "CEO",
                "IPO", "FDA", "SEC", "GDP", "CPI", "ETF", "USA", "NYSE",
                "CFO", "COO", "CTO", "WITH", "THIS", "THAT",
                "FROM", "HAVE", "BEEN", "WILL", "MORE", "WHEN", "WHAT",
                "ALSO", "JUST", "OVER", "THAN", "THEM", "SOME", "INTO",
                "YEAR", "MOST", "MUCH", "VERY", "AFTER", "DOWN",
                "ONLY", "BACK", "SAYS", "SAID", "READ", "US", "AI",
            }
            mentions = Counter()
            for article in response.get("articles", []):
                title = article.get("title", "") or ""
                for t in ticker_pattern.findall(title):
                    if t not in common_words:
                        mentions[t] += 1
            results = [
                {"ticker": t, "source": "news_trending"}
                for t, count in mentions.most_common(top_n) if count >= 2
            ]
            logger.info(f"Scanner: {len(results)} news-trending tickers")
            return results
        except Exception as e:
            logger.error(f"Scanner news error: {e}")
            return []

    # ── Stage 2: Batch Pre-Screen ───────────────────────────────────

    def _batch_prescreen(
        self,
        tickers: list[str],
        source_counts: dict[str, int],
    ) -> list[dict]:
        """Score and rank candidates using batch Alpaca data.

        Returns list of dicts sorted by composite score (highest first).
        """
        # Always include SPY as benchmark
        all_symbols = list(set(tickers + ["SPY"]))

        # Batch fetch: snapshots (1 API call) + weekly bars (1-2 API calls)
        snapshots = self.alpaca_data.get_multi_snapshots(all_symbols)
        weekly_bars = self.alpaca_data.get_multi_bars(all_symbols, "1Week", days=90)

        spy_snap = snapshots.get("SPY", {})
        spy_weekly = weekly_bars.get("SPY", [])
        spy_4w_return = self._calc_return(spy_weekly, weeks=4)

        scored = []
        for ticker in tickers:
            snap = snapshots.get(ticker)
            if not snap:
                continue

            price = snap.get("price", 0)
            volume = snap.get("volume", 0)
            daily_change = snap.get("daily_change_pct", 0)

            # Basic filters
            if price < MIN_PRICE or price > MAX_PRICE:
                continue
            if volume < MIN_AVG_VOLUME:
                continue

            # Relative strength vs SPY (4-week return comparison)
            ticker_weekly = weekly_bars.get(ticker, [])
            ticker_4w_return = self._calc_return(ticker_weekly, weeks=4)
            rel_strength = ticker_4w_return - spy_4w_return

            if rel_strength < self.config.SCANNER_MIN_REL_STRENGTH:
                continue

            # Weekly trend: last close above 10-week SMA
            weekly_uptrend = self._check_weekly_trend(ticker_weekly, sma_period=10)

            # Volume confirmation: today's volume vs previous day
            prev_volume = snap.get("prev_volume", 0)
            vol_ratio = volume / prev_volume if prev_volume > 0 else 1.0

            # Composite score (0-100)
            score = 0.0

            # Relative strength: 0-30 pts (0 at -5%, 30 at +10%)
            score += max(0, min(30, (rel_strength + 5) * 2))

            # Weekly uptrend: 0 or 20 pts
            if weekly_uptrend:
                score += 20

            # Volume ratio: 0-20 pts (1.0x = 10, 2.0x = 20, capped)
            score += max(0, min(20, vol_ratio * 10))

            # Multi-source discovery bonus: 0-15 pts
            sources = source_counts.get(ticker, 1)
            score += min(15, sources * 5)

            # Daily momentum: 0-15 pts
            if daily_change > 0:
                score += min(15, daily_change * 3)

            scored.append({
                "ticker": ticker,
                "score": round(score, 1),
                "rel_strength": round(rel_strength, 2),
                "weekly_uptrend": weekly_uptrend,
                "vol_ratio": round(vol_ratio, 2),
                "daily_change": daily_change,
                "price": price,
                "sources": sources,
            })

        # Sort by composite score
        scored.sort(key=lambda x: x["score"], reverse=True)

        if scored:
            top5 = ", ".join(f"{s['ticker']}({s['score']})" for s in scored[:5])
            logger.info(f"Pre-screen: {len(scored)} passed filters | Top 5: {top5}")

        return scored

    def _calc_return(self, bars: list[dict], weeks: int = 4) -> float:
        """Calculate percentage return over the last N weeks from weekly bars."""
        if len(bars) < weeks + 1:
            return 0.0
        recent_close = bars[-1].get("c", 0)
        past_close = bars[-(weeks + 1)].get("c", 0)
        if past_close <= 0:
            return 0.0
        return round(((recent_close - past_close) / past_close) * 100, 2)

    def _check_weekly_trend(self, bars: list[dict], sma_period: int = 10) -> bool:
        """Check if latest weekly close is above N-week SMA (uptrend)."""
        if len(bars) < sma_period:
            return False
        closes = [b.get("c", 0) for b in bars[-sma_period:]]
        sma = sum(closes) / len(closes)
        return closes[-1] > sma

    # ── Dynamic Sector Watchlist ───────────────────────────────────

    def build_sector_watchlist(self) -> list[str]:
        """Pick the strongest ticker from each sector using batch snapshots.

        Returns one ticker per sector (7 total) — the best daily performer
        in each sector that is in a weekly uptrend.
        """
        # Flatten all sector pool tickers
        all_tickers = []
        for tickers in SECTOR_POOL.values():
            all_tickers.extend(tickers)
        all_tickers = list(set(all_tickers))

        # Batch fetch snapshots + weekly bars (2 API calls)
        snapshots = self.alpaca_data.get_multi_snapshots(all_tickers + ["SPY"])
        weekly_bars = self.alpaca_data.get_multi_bars(all_tickers + ["SPY"], "1Week", days=90)

        spy_4w = self._calc_return(weekly_bars.get("SPY", []), weeks=4)

        watchlist = []
        for sector, pool in SECTOR_POOL.items():
            best_ticker = None
            best_score = -999

            for ticker in pool:
                snap = snapshots.get(ticker)
                if not snap or snap.get("price", 0) <= 0:
                    continue

                wb = weekly_bars.get(ticker, [])
                uptrend = self._check_weekly_trend(wb, sma_period=10)
                rel_strength = self._calc_return(wb, weeks=4) - spy_4w
                daily_change = snap.get("daily_change_pct", 0)

                # Score: relative strength + daily momentum + uptrend bonus
                score = rel_strength + daily_change + (10 if uptrend else 0)

                if score > best_score:
                    best_score = score
                    best_ticker = ticker

            if best_ticker:
                watchlist.append(best_ticker)
                logger.info(f"Sector watchlist [{sector}]: {best_ticker} (score={best_score:.1f})")

        logger.info(f"Dynamic watchlist: {', '.join(watchlist)} ({len(watchlist)} sectors)")
        return watchlist

    # ── Stage 3: Orchestration ──────────────────────────────────────

    def _load_tradeable_assets(self) -> set[str]:
        """Load all tradeable US equity symbols from Alpaca."""
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
                and "." not in a["symbol"]
                and a["symbol"] not in SKIP_TICKERS
            }
            logger.info(f"Scanner: {len(self._tradeable_cache)} tradeable assets loaded")
            return self._tradeable_cache
        except Exception as e:
            logger.error(f"Failed to load tradeable assets: {e}")
            self._tradeable_cache = set()
            return self._tradeable_cache

    def scan(self) -> list[str]:
        """Full-universe scan: snapshot ALL tradeable stocks → batch pre-screen → top N.

        Stage 1: Load entire Alpaca universe (~12K symbols)
        Stage 2: Batch snapshot all of them (filters by price/volume to ~5K)
        Stage 3: Score with relative strength, weekly trend, volume → top N
        """
        logger.info("Scanner: Starting full-universe scan...")

        # Stage 1: Get all tradeable symbols + discovery source bonuses
        tradeable = self._load_tradeable_assets()
        all_symbols = list(tradeable)

        # Also run discovery scanners for source-count bonuses
        discovery_candidates = []
        discovery_candidates.extend(self._discover_most_active())
        discovery_candidates.extend(self._discover_top_movers())
        discovery_candidates.extend(self._discover_news_trending())

        source_counts: dict[str, int] = Counter()
        for c in discovery_candidates:
            source_counts[c["ticker"]] += 1
        # Popular stocks get a bonus too
        for t in POPULAR_STOCKS:
            source_counts[t] += 1

        logger.info(
            f"Stage 1: {len(all_symbols)} tradeable symbols | "
            f"{len(discovery_candidates)} discovery signals"
        )

        # Stage 2: Batch snapshot entire universe (price/volume filter)
        logger.info("Stage 2: Fetching snapshots for full universe...")
        snapshots = self.alpaca_data.get_multi_snapshots(all_symbols + ["SPY"])

        # Quick filter: price and volume thresholds
        passed_filter: list[str] = []
        for sym in all_symbols:
            snap = snapshots.get(sym)
            if not snap:
                continue
            price = snap.get("price", 0)
            volume = snap.get("volume", 0)
            if MIN_PRICE <= price <= MAX_PRICE and volume >= MIN_AVG_VOLUME:
                passed_filter.append(sym)

        logger.info(f"Stage 2: {len(passed_filter)} passed price/volume filter")

        # Stage 3: Weekly bars for filtered set + full scoring
        logger.info("Stage 3: Fetching weekly bars and scoring...")
        weekly_bars = self.alpaca_data.get_multi_bars(
            passed_filter + ["SPY"], "1Week", days=90,
        )

        spy_4w = self._calc_return(weekly_bars.get("SPY", []), weeks=4)

        scored = []
        for ticker in passed_filter:
            snap = snapshots.get(ticker, {})
            price = snap.get("price", 0)
            volume = snap.get("volume", 0)
            daily_change = snap.get("daily_change_pct", 0)

            wb = weekly_bars.get(ticker, [])
            ticker_4w_return = self._calc_return(wb, weeks=4)
            rel_strength = ticker_4w_return - spy_4w

            if rel_strength < self.config.SCANNER_MIN_REL_STRENGTH:
                continue

            weekly_uptrend = self._check_weekly_trend(wb, sma_period=10)

            prev_volume = snap.get("prev_volume", 0)
            vol_ratio = volume / prev_volume if prev_volume > 0 else 1.0

            # Composite score (0-100)
            score = 0.0
            score += max(0, min(30, (rel_strength + 5) * 2))
            if weekly_uptrend:
                score += 20
            score += max(0, min(20, vol_ratio * 10))
            sources = source_counts.get(ticker, 0)
            score += min(15, sources * 5)
            if daily_change > 0:
                score += min(15, daily_change * 3)

            scored.append({
                "ticker": ticker,
                "score": round(score, 1),
                "rel_strength": round(rel_strength, 2),
                "weekly_uptrend": weekly_uptrend,
                "vol_ratio": round(vol_ratio, 2),
                "daily_change": daily_change,
                "price": price,
                "sources": sources,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        if scored:
            top5 = ", ".join(f"{s['ticker']}({s['score']})" for s in scored[:5])
            logger.info(f"Stage 3: {len(scored)} scored | Top 5: {top5}")

        top_n = self.config.SCANNER_TOP_N
        result = [r["ticker"] for r in scored[:top_n]]

        logger.info(
            f"Scanner complete: {len(all_symbols)} universe → "
            f"{len(passed_filter)} liquid → {len(scored)} scored → "
            f"{len(result)} selected"
        )
        return result

    def scan_penny(self) -> list[str]:
        """Scan for penny stocks ($1-$5) with high volume and upside potential.

        Uses the same 3-stage funnel as the main scanner but with:
        - Price filter: $1–$5 (instead of $5–$5,000)
        - Higher volume threshold: 500K+ avg volume (liquidity matters more)
        - Bonus scoring for high daily % movers (penny stocks move big)
        """
        logger.info("Penny Scanner: Starting sub-$5 scan...")

        penny_min = self.config.PENNY_MIN_PRICE
        penny_max = self.config.PENNY_MAX_PRICE
        penny_min_vol = self.config.PENNY_MIN_AVG_VOLUME
        penny_top_n = self.config.PENNY_SCANNER_TOP_N

        # Stage 1: Load tradeable universe
        tradeable = self._load_tradeable_assets()
        all_symbols = list(tradeable)

        # Discovery bonuses (reuse same discovery sources)
        discovery_candidates = []
        discovery_candidates.extend(self._discover_most_active())
        discovery_candidates.extend(self._discover_top_movers())

        source_counts: dict[str, int] = Counter()
        for c in discovery_candidates:
            source_counts[c["ticker"]] += 1

        logger.info(f"Penny Stage 1: {len(all_symbols)} tradeable symbols")

        # Stage 2: Batch snapshot — penny price filter
        snapshots = self.alpaca_data.get_multi_snapshots(all_symbols + ["SPY"])

        passed_filter: list[str] = []
        for sym in all_symbols:
            snap = snapshots.get(sym)
            if not snap:
                continue
            price = snap.get("price", 0)
            volume = snap.get("volume", 0)
            if penny_min <= price <= penny_max and volume >= penny_min_vol:
                passed_filter.append(sym)

        logger.info(f"Penny Stage 2: {len(passed_filter)} passed $1-$5 / volume filter")

        if not passed_filter:
            logger.info("Penny Scanner: No candidates passed filters")
            return []

        # Stage 3: Score — penny stocks prioritize momentum and volume spikes
        weekly_bars = self.alpaca_data.get_multi_bars(
            passed_filter + ["SPY"], "1Week", days=90,
        )
        spy_4w = self._calc_return(weekly_bars.get("SPY", []), weeks=4)

        scored = []
        for ticker in passed_filter:
            snap = snapshots.get(ticker, {})
            price = snap.get("price", 0)
            volume = snap.get("volume", 0)
            daily_change = snap.get("daily_change_pct", 0)

            wb = weekly_bars.get(ticker, [])
            ticker_4w_return = self._calc_return(wb, weeks=4)
            rel_strength = ticker_4w_return - spy_4w

            # Penny stocks: skip rel strength filter (they're volatile)

            weekly_uptrend = self._check_weekly_trend(wb, sma_period=10)

            prev_volume = snap.get("prev_volume", 0)
            vol_ratio = volume / prev_volume if prev_volume > 0 else 1.0

            # Penny scoring: heavier weight on volume spike + daily momentum
            score = 0.0

            # Relative strength: 0-20 pts (less weight than main)
            score += max(0, min(20, (rel_strength + 10) * 1))

            # Weekly uptrend: 0 or 15 pts
            if weekly_uptrend:
                score += 15

            # Volume spike: 0-30 pts (key signal for penny stocks)
            score += max(0, min(30, vol_ratio * 10))

            # Multi-source discovery bonus: 0-10 pts
            sources = source_counts.get(ticker, 0)
            score += min(10, sources * 5)

            # Daily momentum: 0-25 pts (penny stocks reward big movers)
            if daily_change > 0:
                score += min(25, daily_change * 2.5)

            scored.append({
                "ticker": ticker,
                "score": round(score, 1),
                "rel_strength": round(rel_strength, 2),
                "weekly_uptrend": weekly_uptrend,
                "vol_ratio": round(vol_ratio, 2),
                "daily_change": daily_change,
                "price": price,
                "sources": sources,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        if scored:
            top5 = ", ".join(f"{s['ticker']}(${s['price']:.2f}, {s['score']})" for s in scored[:5])
            logger.info(f"Penny Stage 3: {len(scored)} scored | Top 5: {top5}")

        result = [r["ticker"] for r in scored[:penny_top_n]]

        logger.info(
            f"Penny Scanner complete: {len(all_symbols)} universe → "
            f"{len(passed_filter)} penny-priced → {len(scored)} scored → "
            f"{len(result)} selected"
        )
        return result

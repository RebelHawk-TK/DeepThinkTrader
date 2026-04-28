"""News aggregator — parallel fetching, deduplication, caching, budget-aware routing."""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from .alphavantage_client import AlphaVantageClient
from .fmp_client import FMPClient
from .marketaux_client import MarketauxClient
from .news_models import NewsArticle, NewsSource
from .rate_limiter import RateLimiter
from .stocknewsapi_client import StockNewsAPIClient
from .tickertick_client import TickerTickClient

logger = logging.getLogger(__name__)

# Sources ordered cheapest-first for rotation
_ROTATION_ORDER = [
    NewsSource.TICKER_TICK,
    NewsSource.FMP,
    NewsSource.MARKETAUX,
    NewsSource.STOCK_NEWS_API,
    NewsSource.ALPHA_VANTAGE,
]

DEDUP_SIMILARITY_THRESHOLD = 0.85


class NewsAggregator:
    def __init__(self, config: dict[str, Any]):
        self.clients: dict[NewsSource, Any] = {}
        self.cache_ttl = timedelta(minutes=config.get("NEWS_CACHE_TTL_MINUTES", 30))
        self._cache: dict[str, dict] = {}
        self._rotation_index = 0

        # Initialize only enabled clients with valid keys
        if config.get("TICKER_TICK_ENABLED"):
            self.clients[NewsSource.TICKER_TICK] = TickerTickClient()

        if config.get("FMP_ENABLED") and config.get("FMP_API_KEY"):
            self.clients[NewsSource.FMP] = FMPClient(config["FMP_API_KEY"])

        if config.get("MARKETAUX_ENABLED") and config.get("MARKETAUX_API_KEY"):
            self.clients[NewsSource.MARKETAUX] = MarketauxClient(config["MARKETAUX_API_KEY"])

        if config.get("STOCK_NEWS_API_ENABLED") and config.get("STOCK_NEWS_API_KEY"):
            self.clients[NewsSource.STOCK_NEWS_API] = StockNewsAPIClient(config["STOCK_NEWS_API_KEY"])

        if config.get("ALPHA_VANTAGE_ENABLED") and config.get("ALPHA_VANTAGE_API_KEY"):
            self.clients[NewsSource.ALPHA_VANTAGE] = AlphaVantageClient(config["ALPHA_VANTAGE_API_KEY"])

        logger.info("NewsAggregator initialized with %d sources: %s",
                     len(self.clients), [s.value for s in self.clients])

    def _select_sources(self, priority: str) -> list[NewsSource]:
        """Select sources based on ticker priority to stay within budget.

        very_high = all enabled sources incl. Marketaux (top 3 tickers)
        high      = all sources EXCEPT Marketaux (tickers 4-5)
        medium    = rotate through 3 non-Marketaux sources (tickers 6-25)
        low       = TickerTick only (tail)

        Marketaux is gated tighter than other sources because its free-tier
        cap is 100 calls/day; top-3 × ~26 cycles = 78/day stays under cap.
        """
        available = [s for s in _ROTATION_ORDER if s in self.clients]
        if not available:
            return []

        if priority == "very_high":
            return available

        # Marketaux free tier = 100 req/day. Strip Marketaux from anything
        # below very_high so we stay under the daily cap.
        available = [s for s in available if s != NewsSource.MARKETAUX]
        if not available:
            return []

        if priority == "high":
            return available

        if priority == "low":
            if NewsSource.TICKER_TICK in self.clients:
                return [NewsSource.TICKER_TICK]
            return available[:1]

        # medium — rotate through 3 sources
        count = min(3, len(available))
        selected = []
        for i in range(count):
            idx = (self._rotation_index + i) % len(available)
            selected.append(available[idx])
        self._rotation_index = (self._rotation_index + 1) % len(available)
        return selected

    def fetch_news(self, ticker: str, priority: str = "medium", limit: int = 15) -> list[NewsArticle]:
        """Fetch and aggregate news from multiple sources for a ticker.

        Args:
            ticker: Stock symbol (e.g. "AAPL")
            priority: "high", "medium", or "low" — controls how many APIs are queried
            limit: Max articles per source
        """
        ticker = ticker.upper()

        # Check cache
        cached = self._cache.get(ticker)
        if cached and cached["expires_at"] > datetime.utcnow():
            logger.debug("Cache hit for %s (%d articles)", ticker, len(cached["articles"]))
            return cached["articles"]

        sources = self._select_sources(priority)
        if not sources:
            return []

        # Parallel fetch from selected sources (with timeout to prevent hangs)
        all_articles: list[NewsArticle] = []
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            futures = {
                executor.submit(self.clients[source].fetch_news, ticker, limit): source
                for source in sources
            }
            try:
                for future in as_completed(futures, timeout=20):
                    source = futures[future]
                    try:
                        articles = future.result(timeout=2)
                        all_articles.extend(articles)
                        logger.debug("%s returned %d articles for %s", source.value, len(articles), ticker)
                    except TimeoutError:
                        logger.warning("Result retrieval timed out for %s/%s", source.value, ticker)
                    except Exception as e:
                        logger.error("Fetch failed for %s/%s: %s", source.value, ticker, e)
            except TimeoutError:
                logger.warning("News aggregation timed out for %s after 20s — using partial results", ticker)

        # Deduplicate
        deduped = self._deduplicate(all_articles)

        # Sort by published date (newest first)
        deduped.sort(key=lambda a: a.published_at, reverse=True)

        # Cache results
        self._cache[ticker] = {
            "articles": deduped,
            "expires_at": datetime.utcnow() + self.cache_ttl,
        }

        logger.info("Aggregated %d articles for %s from %d sources (before dedup: %d)",
                     len(deduped), ticker, len(sources), len(all_articles))
        return deduped

    def _deduplicate(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Remove duplicate articles by URL match then headline similarity."""
        seen_urls: set[str] = set()
        seen_headlines: list[str] = []
        unique: list[NewsArticle] = []

        for article in articles:
            # Exact URL match
            if article.url in seen_urls:
                continue

            # Headline similarity check
            is_dup = False
            for existing in seen_headlines:
                ratio = SequenceMatcher(None, article.headline.lower(), existing).ratio()
                if ratio >= DEDUP_SIMILARITY_THRESHOLD:
                    is_dup = True
                    break

            if is_dup:
                continue

            seen_urls.add(article.url)
            seen_headlines.append(article.headline.lower())
            unique.append(article)

        return unique

    def compute_sentiment(self, articles: list[NewsArticle]) -> float:
        """Compute relevance-weighted average sentiment from a list of articles.

        Returns a score between -1.0 and 1.0. Returns 0.0 if no articles.
        """
        if not articles:
            return 0.0

        weighted_sum = 0.0
        total_weight = 0.0
        for a in articles:
            weight = a.relevance_score if a.relevance_score else 1.0
            weighted_sum += a.sentiment_score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        return max(-1.0, min(1.0, weighted_sum / total_weight))

    def get_budget_status(self) -> dict[str, dict]:
        """Return remaining API budget for each source."""
        status = {}
        for source, client in self.clients.items():
            if hasattr(client, "limiter"):
                status[source.value] = client.limiter.budget_status()
        return status

    def clear_cache(self):
        self._cache.clear()

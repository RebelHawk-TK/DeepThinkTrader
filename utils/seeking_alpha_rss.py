"""Seeking Alpha RSS Feed Reader — Pulls articles, news, and ticker intelligence from SA feeds.

Available feeds:
- Main feed (feed.xml): All new articles across the platform
- Ticker feeds (api/sa/combined/{TICKER}.xml): Articles + news for a specific stock
- Tag feeds (tag/{tag}.xml): Themed content (wall-st-breakfast, dividends, etc.)

Extracts tickers from <category> tags, scores sentiment on titles, and categorizes content.
"""

from __future__ import annotations

import logging
import re
import defusedxml.ElementTree as ET  # XXE-safe drop-in replacement for xml.etree
from datetime import datetime, timedelta

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import Config

logger = logging.getLogger(__name__)

# Feeds to poll
_MAIN_FEED = "https://seekingalpha.com/feed.xml"
_TICKER_FEED = "https://seekingalpha.com/api/sa/combined/{ticker}.xml"
_TAG_FEEDS = {
    "wall_st_breakfast": "https://seekingalpha.com/tag/wall-st-breakfast.xml",
    "dividends": "https://seekingalpha.com/tag/dividend-ideas.xml",
    "etf": "https://seekingalpha.com/tag/etf-portfolio-strategy.xml",
}

_SKIP_TICKERS = {
    "US", "UK", "EU", "GDP", "CPI", "PMI", "FED", "SEC", "IPO", "CEO",
    "ETF", "NYSE", "USD", "EUR", "GBP", "JPY", "AI", "EV", "IT", "TV",
}

# Category keywords for classification
_CATEGORY_KEYWORDS = {
    "earnings": ["earnings", "eps", "revenue", "quarter", "guidance", "beat", "miss", "report"],
    "analyst": ["upgrade", "downgrade", "target", "rating", "analyst", "overweight", "underweight"],
    "dividend": ["dividend", "yield", "payout", "distribution", "income"],
    "insider": ["insider", "buyback", "repurchase", "ceo buy", "director"],
    "momentum": ["breakout", "rally", "surge", "momentum", "bull", "all-time high", "new high"],
    "risk": ["risk", "bear", "crash", "decline", "warning", "overvalued", "bubble", "drop"],
    "merger": ["acquisition", "merger", "takeover", "buyout", "deal"],
    "sector": ["sector", "rotation", "industry", "market cap"],
}


class SeekingAlphaRSS:
    """Fetches and parses Seeking Alpha RSS feeds for ticker intelligence."""

    def __init__(self):
        self.config = Config()
        self.vader = SentimentIntensityAnalyzer()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "DeepThinkTrader/3.0 RSS Reader",
        })
        # Cache: feed_url -> (items, fetched_at)
        self._cache: dict[str, tuple[list[dict], datetime]] = {}
        self._cache_ttl = 1800  # 30 minutes

    def _fetch_feed(self, url: str) -> list[dict]:
        """Fetch and parse an RSS feed. Returns list of item dicts."""
        # Check cache
        cached = self._cache.get(url)
        if cached:
            items, fetched_at = cached
            if (datetime.now() - fetched_at).total_seconds() < self._cache_ttl:
                return items

        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

            items = []
            # Handle both RSS 2.0 (<channel><item>) and Atom (<entry>)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                guid = (item.findtext("guid") or "").strip()

                # Extract tickers from <category> tags
                tickers = []
                categories_raw = []
                for cat in item.findall("category"):
                    text = (cat.text or "").strip()
                    cat_type = cat.get("type", "")
                    if cat_type == "symbol" or (text.isupper() and 1 < len(text) <= 5):
                        if text not in _SKIP_TICKERS and not text.startswith("$"):
                            tickers.append(text)
                    else:
                        categories_raw.append(text)

                # Also extract tickers from title using (TICKER) pattern
                for match in re.finditer(r"\(([A-Z]{1,5})\)", title):
                    t = match.group(1)
                    if t not in _SKIP_TICKERS and t not in tickers:
                        tickers.append(t)

                # Parse date
                parsed_date = self._parse_date(pub_date)

                # Sentiment on title
                sentiment = self.vader.polarity_scores(title)

                # Classify content
                content_categories = self._classify_title(title)

                items.append({
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "parsed_date": parsed_date,
                    "tickers": tickers,
                    "categories_raw": categories_raw,
                    "categories": content_categories,
                    "sentiment_compound": round(sentiment["compound"], 3),
                    "guid": guid,
                })

            self._cache[url] = (items, datetime.now())
            logger.info(f"SA RSS: fetched {len(items)} items from {url.split('/')[-1]}")
            return items

        except Exception as e:
            logger.error(f"SA RSS fetch failed for {url}: {e}")
            return []

    def _parse_date(self, date_str: str) -> datetime | None:
        """Parse RSS pubDate format."""
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _classify_title(self, title: str) -> list[str]:
        """Classify article by title keywords."""
        lower = title.lower()
        cats = []
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                cats.append(category)
        if not cats:
            cats.append("analysis")
        return cats

    # ── Public API ─────────────────────────────────────────────

    def fetch_main_feed(self) -> list[dict]:
        """Fetch the main SA article feed."""
        return self._fetch_feed(_MAIN_FEED)

    def fetch_ticker_feed(self, ticker: str) -> list[dict]:
        """Fetch SA articles + news for a specific ticker."""
        url = _TICKER_FEED.format(ticker=ticker.upper())
        return self._fetch_feed(url)

    def fetch_tag_feeds(self) -> list[dict]:
        """Fetch all configured tag feeds (breakfast, dividends, ETF)."""
        all_items = []
        for tag_name, url in _TAG_FEEDS.items():
            items = self._fetch_feed(url)
            for item in items:
                item["feed_tag"] = tag_name
            all_items.extend(items)
        return all_items

    def scan_all_feeds(self, max_age_hours: int = 48) -> dict[str, list[dict]]:
        """Scan main + tag feeds and group articles by ticker.

        Returns dict mapping ticker -> list of article records.
        """
        cutoff = datetime.now().astimezone() - timedelta(hours=max_age_hours)

        all_items = self.fetch_main_feed() + self.fetch_tag_feeds()

        # Filter by age
        recent = []
        for item in all_items:
            pd = item.get("parsed_date")
            if pd and pd > cutoff:
                recent.append(item)
            elif not pd:
                recent.append(item)  # include if we can't parse date

        # Group by ticker
        by_ticker: dict[str, list[dict]] = {}
        for item in recent:
            for ticker in item["tickers"]:
                if ticker not in by_ticker:
                    by_ticker[ticker] = []
                by_ticker[ticker].append(item)

        logger.info(
            f"SA RSS scan: {len(recent)} recent articles, "
            f"{len(by_ticker)} tickers mentioned"
        )
        return by_ticker

    def get_ticker_intel(self, ticker: str, include_dedicated: bool = True) -> dict:
        """Get comprehensive SA intelligence for a specific ticker.

        Combines data from main/tag feeds + optional ticker-specific feed.

        Returns:
            {ticker, article_count, avg_sentiment, categories, articles: [...],
             bullish_count, bearish_count, neutral_count}
        """
        # Get from broad scan
        all_data = self.scan_all_feeds()
        articles = list(all_data.get(ticker.upper(), []))

        # Optionally fetch the ticker-specific feed
        if include_dedicated:
            dedicated = self.fetch_ticker_feed(ticker)
            # Deduplicate by guid
            existing_guids = {a["guid"] for a in articles}
            for item in dedicated:
                if item["guid"] not in existing_guids:
                    articles.append(item)

        if not articles:
            return {
                "ticker": ticker,
                "source": "seeking_alpha_rss",
                "article_count": 0,
                "avg_sentiment": 0.0,
                "categories": [],
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "articles": [],
            }

        sentiments = [a["sentiment_compound"] for a in articles]
        avg_sentiment = round(sum(sentiments) / len(sentiments), 3)

        bullish = sum(1 for s in sentiments if s > 0.15)
        bearish = sum(1 for s in sentiments if s < -0.15)
        neutral = len(sentiments) - bullish - bearish

        all_categories = set()
        for a in articles:
            all_categories.update(a["categories"])

        # Sort by date (newest first)
        articles.sort(key=lambda x: x.get("pub_date", ""), reverse=True)

        return {
            "ticker": ticker,
            "source": "seeking_alpha_rss",
            "article_count": len(articles),
            "avg_sentiment": avg_sentiment,
            "categories": sorted(all_categories),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "articles": [
                {
                    "title": a["title"],
                    "sentiment": a["sentiment_compound"],
                    "categories": a["categories"],
                    "date": a["pub_date"],
                    "link": a["link"],
                }
                for a in articles[:10]  # top 10 most recent
            ],
        }

    def get_trending_tickers(self, min_mentions: int = 2) -> list[dict]:
        """Get tickers trending across SA feeds, ranked by mention count + sentiment.

        Returns list of {ticker, mentions, avg_sentiment, categories}.
        """
        by_ticker = self.scan_all_feeds()

        trending = []
        for ticker, articles in by_ticker.items():
            if len(articles) < min_mentions:
                continue
            sents = [a["sentiment_compound"] for a in articles]
            cats = set()
            for a in articles:
                cats.update(a["categories"])
            trending.append({
                "ticker": ticker,
                "mentions": len(articles),
                "avg_sentiment": round(sum(sents) / len(sents), 3),
                "categories": sorted(cats),
            })

        trending.sort(key=lambda x: (x["mentions"], x["avg_sentiment"]), reverse=True)
        return trending

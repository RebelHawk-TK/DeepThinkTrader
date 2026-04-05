"""marketaux client — https://marketaux.com
Free tier: 100 requests/day. Auth: query param api_token=KEY.
Provides entity-level sentiment scores.
"""

import logging
from datetime import datetime

import requests

from .news_models import NewsArticle, NewsSource
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.marketaux.com/v1/news/all"


class MarketauxClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.limiter = RateLimiter.daily(max_calls=100, name="marketaux")

    def _extract_ticker_sentiment(self, entities: list, ticker: str) -> tuple[float, float | None]:
        """Extract sentiment and relevance for a specific ticker from the entities array."""
        ticker_upper = ticker.upper()
        for entity in entities:
            symbol = (entity.get("symbol") or "").upper()
            if symbol == ticker_upper:
                score = entity.get("sentiment_score", 0.0)
                relevance = entity.get("match_score")
                return float(score), float(relevance) if relevance else None
        # Ticker not found in entities — use 0.0
        return 0.0, None

    def fetch_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]:
        if not self.api_key:
            return []
        if not self.limiter.can_make_call():
            logger.warning("marketaux rate limit reached")
            return []

        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "symbols": ticker.upper(),
                    "filter_entities": "true",
                    "limit": min(limit, 50),
                    "api_token": self.api_key,
                },
                timeout=10,
            )
            self.limiter.record_call()
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("marketaux error for %s: %s", ticker, e)
            return []

        articles = []
        for item in data.get("data", []):
            try:
                entities = item.get("entities", [])
                score, relevance = self._extract_ticker_sentiment(entities, ticker)
                label = "Bullish" if score > 0 else "Bearish" if score < 0 else "Neutral"

                published = datetime.fromisoformat(
                    item["published_at"].replace("Z", "+00:00")
                )

                articles.append(
                    NewsArticle(
                        headline=item.get("title", ""),
                        ticker=ticker.upper(),
                        source_api=NewsSource.MARKETAUX,
                        url=item.get("url", ""),
                        published_at=published,
                        sentiment_score=score,
                        sentiment_label=label,
                        source_name=item.get("source"),
                        summary=item.get("description"),
                        image_url=item.get("image_url"),
                        relevance_score=relevance,
                        raw_data=item,
                    )
                )
            except Exception as e:
                logger.debug("marketaux parse error: %s", e)
                continue

        return articles

"""StockNewsAPI client — https://stocknewsapi.com
Free tier: 100 calls/month. Auth: query param token=KEY.
"""

import logging
from datetime import datetime

import requests

from .news_models import NewsArticle, NewsSource
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://stocknewsapi.com/api/v1"

SENTIMENT_MAP = {
    "positive": 0.6,
    "negative": -0.6,
    "neutral": 0.0,
}


class StockNewsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.limiter = RateLimiter.monthly(max_calls=100, name="StockNewsAPI")

    def fetch_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]:
        if not self.api_key:
            return []
        if not self.limiter.can_make_call():
            logger.warning("StockNewsAPI rate limit reached")
            return []

        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "tickers": ticker.upper(),
                    "items": min(limit, 50),
                    "token": self.api_key,
                },
                timeout=10,
            )
            self.limiter.record_call()
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("StockNewsAPI error for %s: %s", ticker, e)
            return []

        articles = []
        for item in data.get("data", []):
            try:
                sentiment_tag = (item.get("sentiment") or "neutral").lower()
                score = SENTIMENT_MAP.get(sentiment_tag, 0.0)

                published = datetime.strptime(
                    item["date"], "%a, %d %b %Y %H:%M:%S %z"
                )

                articles.append(
                    NewsArticle(
                        headline=item.get("title", ""),
                        ticker=ticker.upper(),
                        source_api=NewsSource.STOCK_NEWS_API,
                        url=item.get("news_url", ""),
                        published_at=published,
                        sentiment_score=score,
                        sentiment_label=sentiment_tag.capitalize(),
                        source_name=item.get("source_name"),
                        summary=item.get("text"),
                        image_url=item.get("image_url"),
                        raw_data=item,
                    )
                )
            except Exception as e:
                logger.debug("StockNewsAPI parse error: %s", e)
                continue

        return articles

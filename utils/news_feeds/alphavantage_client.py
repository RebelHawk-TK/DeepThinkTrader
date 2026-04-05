"""Alpha Vantage NEWS_SENTIMENT client — https://alphavantage.co
Free tier: 25 requests/day, 5 requests/min. Auth: query param apikey=KEY.
Provides detailed sentiment scores (-1 to 1) and labels.
"""

import logging
from datetime import datetime

import requests

from .news_models import NewsArticle, NewsSource
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.limiter = RateLimiter.daily(
            max_calls=25, per_minute_limit=5, name="AlphaVantage"
        )

    def _extract_ticker_sentiment(self, ticker_sentiments: list, ticker: str) -> tuple[float, float | None]:
        ticker_upper = ticker.upper()
        for ts in ticker_sentiments:
            if ts.get("ticker", "").upper() == ticker_upper:
                score = float(ts.get("ticker_sentiment_score", 0.0))
                relevance = float(ts.get("relevance_score", 0.0))
                return score, relevance
        return 0.0, None

    def fetch_news(self, ticker: str, limit: int = 10) -> list[NewsArticle]:
        if not self.api_key:
            return []
        if not self.limiter.can_make_call():
            logger.warning("AlphaVantage rate limit reached")
            return []

        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker.upper(),
                    "limit": min(limit, 50),
                    "apikey": self.api_key,
                },
                timeout=15,
            )
            self.limiter.record_call()
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("AlphaVantage error for %s: %s", ticker, e)
            return []

        if "Information" in data:
            logger.warning("AlphaVantage limit message: %s", data["Information"])
            return []

        articles = []
        for item in data.get("feed", []):
            try:
                overall_score = float(item.get("overall_sentiment_score", 0.0))
                overall_label = item.get("overall_sentiment_label", "Neutral")

                ticker_sentiments = item.get("ticker_sentiment", [])
                ticker_score, relevance = self._extract_ticker_sentiment(
                    ticker_sentiments, ticker
                )
                # Prefer ticker-specific score when available
                score = ticker_score if relevance else overall_score

                ts_str = item.get("time_published", "")
                published = datetime.strptime(ts_str[:15], "%Y%m%dT%H%M%S")

                articles.append(
                    NewsArticle(
                        headline=item.get("title", ""),
                        ticker=ticker.upper(),
                        source_api=NewsSource.ALPHA_VANTAGE,
                        url=item.get("url", ""),
                        published_at=published,
                        sentiment_score=score,
                        sentiment_label=overall_label,
                        source_name=item.get("source"),
                        summary=item.get("summary"),
                        image_url=item.get("banner_image"),
                        relevance_score=relevance,
                        raw_data=item,
                    )
                )
            except Exception as e:
                logger.debug("AlphaVantage parse error: %s", e)
                continue

        return articles

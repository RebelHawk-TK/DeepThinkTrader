"""Financial Modeling Prep client — https://financialmodelingprep.com
Free tier: 250 requests/day. Auth: query param apikey=KEY.
No native sentiment on stock_news endpoint — computes via VADER.
"""

import logging
from datetime import datetime

import requests

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    _vader = SentimentIntensityAnalyzer()
except ImportError:
    _vader = None

from .news_models import NewsArticle, NewsSource
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/api/v3/stock_news"


def _vader_score(text: str) -> float:
    if _vader is None:
        return 0.0
    return _vader.polarity_scores(text)["compound"]


class FMPClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.limiter = RateLimiter.daily(max_calls=250, name="FMP")

    def fetch_news(self, ticker: str, limit: int = 15) -> list[NewsArticle]:
        if not self.api_key:
            return []
        if not self.limiter.can_make_call():
            logger.warning("FMP rate limit reached")
            return []

        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "tickers": ticker.upper(),
                    "limit": min(limit, 50),
                    "apikey": self.api_key,
                },
                timeout=10,
            )
            self.limiter.record_call()
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("FMP error for %s: %s", ticker, e)
            return []

        if not isinstance(data, list):
            return []

        articles = []
        for item in data:
            try:
                title = item.get("title", "")
                text = item.get("text", "")
                combined = f"{title}. {text}" if text else title
                score = _vader_score(combined)
                label = "Bullish" if score >= 0.15 else "Bearish" if score <= -0.15 else "Neutral"

                published = datetime.strptime(
                    item["publishedDate"], "%Y-%m-%d %H:%M:%S"
                )

                articles.append(
                    NewsArticle(
                        headline=title,
                        ticker=ticker.upper(),
                        source_api=NewsSource.FMP,
                        url=item.get("url", ""),
                        published_at=published,
                        sentiment_score=score,
                        sentiment_label=label,
                        source_name=item.get("site"),
                        summary=text[:500] if text else None,
                        image_url=item.get("image"),
                        raw_data=item,
                    )
                )
            except Exception as e:
                logger.debug("FMP parse error: %s", e)
                continue

        return articles

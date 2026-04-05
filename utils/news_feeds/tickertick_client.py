"""TickerTick client — https://api.tickertick.com
Free tier: 10 requests/min, no auth required.
No native sentiment — computes via VADER.
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

BASE_URL = "https://api.tickertick.com/feed"


def _vader_score(text: str) -> float:
    if _vader is None:
        return 0.0
    scores = _vader.polarity_scores(text)
    return scores["compound"]  # -1.0 to 1.0


class TickerTickClient:
    def __init__(self):
        self.limiter = RateLimiter(
            max_calls=10, period_seconds=60, name="TickerTick"
        )

    def fetch_news(self, ticker: str, limit: int = 20) -> list[NewsArticle]:
        if not self.limiter.can_make_call():
            logger.warning("TickerTick rate limit reached")
            return []

        query = f"(and T:curated tt:{ticker.lower()})"
        try:
            resp = requests.get(
                BASE_URL,
                params={"q": query, "n": min(limit, 50)},
                timeout=10,
            )
            self.limiter.record_call()
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("TickerTick error for %s: %s", ticker, e)
            return []

        articles = []
        for item in data.get("stories", []):
            try:
                title = item.get("title", "")
                score = _vader_score(title)
                label = "Bullish" if score >= 0.15 else "Bearish" if score <= -0.15 else "Neutral"

                ts_ms = item.get("time", 0)
                published = datetime.utcfromtimestamp(ts_ms / 1000)

                articles.append(
                    NewsArticle(
                        headline=title,
                        ticker=ticker.upper(),
                        source_api=NewsSource.TICKER_TICK,
                        url=item.get("url", ""),
                        published_at=published,
                        sentiment_score=score,
                        sentiment_label=label,
                        source_name=item.get("source"),
                        raw_data=item,
                    )
                )
            except Exception as e:
                logger.debug("TickerTick parse error: %s", e)
                continue

        return articles

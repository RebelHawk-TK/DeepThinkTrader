"""Unified data model for news articles across all API sources."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class NewsSource(Enum):
    STOCK_NEWS_API = "stocknewsapi"
    TICKER_TICK = "tickertick"
    FMP = "fmp"
    MARKETAUX = "marketaux"
    ALPHA_VANTAGE = "alphavantage"


@dataclass
class NewsArticle:
    headline: str
    ticker: str
    source_api: NewsSource
    url: str
    published_at: datetime
    sentiment_score: float  # -1.0 (bearish) to 1.0 (bullish)

    sentiment_label: Optional[str] = None  # "Bullish" / "Bearish" / "Neutral"
    source_name: Optional[str] = None  # "Bloomberg", "Reuters", etc.
    summary: Optional[str] = None
    image_url: Optional[str] = None
    relevance_score: Optional[float] = None  # 0.0 to 1.0
    raw_data: Optional[dict[str, Any]] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        # Normalize published_at to UTC-aware. Some clients return naive
        # datetimes (strptime, utcfromtimestamp); Marketaux returns aware.
        # Mixing them blows up sorts in NewsAggregator.
        if self.published_at.tzinfo is None:
            self.published_at = self.published_at.replace(tzinfo=timezone.utc)
        if self.fetched_at.tzinfo is None:
            self.fetched_at = self.fetched_at.replace(tzinfo=timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "ticker": self.ticker,
            "source_api": self.source_api.value,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
            "source_name": self.source_name,
            "summary": self.summary,
            "image_url": self.image_url,
            "relevance_score": self.relevance_score,
            "fetched_at": self.fetched_at.isoformat(),
        }

    @property
    def is_bullish(self) -> bool:
        return self.sentiment_score >= 0.15

    @property
    def is_bearish(self) -> bool:
        return self.sentiment_score <= -0.15

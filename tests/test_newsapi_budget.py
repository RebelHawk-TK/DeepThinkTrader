"""NewsAPI budgeting tests — verifies we call the quota'd API only when the
free aggregator didn't turn up enough coverage."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.research_agent import ResearchAgent


def _make_agent() -> ResearchAgent:
    """Bypass __init__ (which opens PRAW/NewsAPI clients) — we only need to
    exercise generate_report's branching logic."""
    a = ResearchAgent.__new__(ResearchAgent)
    a.config = MagicMock(SUBREDDITS=[], MIN_CATALYST_SCORE=0.0)
    a.db = MagicMock()
    a.db.save_research = MagicMock()
    a.rate_limiter = MagicMock()
    a.rate_limiter.can_call_newsapi = MagicMock(return_value=True)
    a.newsapi = MagicMock()
    a.vader = MagicMock()
    a.reddit = None
    a.alpaca_data = MagicMock()
    a.alpaca_data.get_technicals = MagicMock(return_value={"error": "none"})
    a.yahoo_fundamentals = MagicMock()
    a.yahoo_fundamentals.get_fundamentals = MagicMock(return_value={})
    a.obsidian_sa = MagicMock()
    a.obsidian_sa.get_ticker_intel = MagicMock(return_value={})
    a.sa_rss = MagicMock()
    a.sa_rss.get_ticker_intel = MagicMock(return_value={"article_count": 0})
    a.options_monitor = MagicMock()
    a.options_monitor.get_signals = MagicMock(return_value={})
    a.twelve_data = None
    a._report_cache = {}
    a.news_aggregator = MagicMock()
    return a


def test_newsapi_skipped_when_aggregator_has_coverage(monkeypatch):
    agent = _make_agent()
    # Aggregator returns 5 articles — above the 3-article threshold.
    agent.news_aggregator.fetch_news = MagicMock(return_value=[
        {"title": f"headline {i}", "sentiment": 0.1} for i in range(5)
    ])
    agent.news_aggregator.compute_sentiment = MagicMock(return_value=0.2)

    # Make the rest of the pipeline return cheap stubs.
    agent.fetch_reddit_sentiment = MagicMock(
        return_value={"post_count": 0, "overall_sentiment": 0.0, "top_posts": [], "themes": []},
    )
    agent.fetch_technicals = MagicMock(return_value={"error": "stub"})
    agent._fetch_market_regime = MagicMock(return_value={})
    agent.fetch_news = MagicMock(return_value=[])

    agent.generate_report("NVDA")
    # Must NOT have called NewsAPI.
    agent.fetch_news.assert_not_called()


def test_newsapi_called_when_aggregator_is_thin(monkeypatch):
    agent = _make_agent()
    # Aggregator returned 1 article — below the threshold.
    agent.news_aggregator.fetch_news = MagicMock(return_value=[
        {"title": "lone headline", "sentiment": 0.1},
    ])
    agent.news_aggregator.compute_sentiment = MagicMock(return_value=0.1)

    agent.fetch_reddit_sentiment = MagicMock(
        return_value={"post_count": 0, "overall_sentiment": 0.0, "top_posts": [], "themes": []},
    )
    agent.fetch_technicals = MagicMock(return_value={"error": "stub"})
    agent._fetch_market_regime = MagicMock(return_value={})
    agent.fetch_news = MagicMock(return_value=[])

    agent.generate_report("OBSCURE")
    # NewsAPI IS called since aggregator didn't cover.
    agent.fetch_news.assert_called_once_with("OBSCURE")


def test_newsapi_called_when_aggregator_unavailable(monkeypatch):
    agent = _make_agent()
    agent.news_aggregator = None  # no aggregator configured

    agent.fetch_reddit_sentiment = MagicMock(
        return_value={"post_count": 0, "overall_sentiment": 0.0, "top_posts": [], "themes": []},
    )
    agent.fetch_technicals = MagicMock(return_value={"error": "stub"})
    agent._fetch_market_regime = MagicMock(return_value={})
    agent.fetch_news = MagicMock(return_value=[])

    agent.generate_report("NVDA")
    # With no aggregator, aggregated_articles stays empty (0 < 3) → NewsAPI is called.
    agent.fetch_news.assert_called_once_with("NVDA")


def test_cache_ttl_is_four_hours():
    # Simple class-attr guard — document the intended TTL in a test so a
    # future "oh let me just bump it down again" change gets flagged.
    assert ResearchAgent._REPORT_CACHE_TTL_SECONDS == 4 * 3600
    assert ResearchAgent._NEWSAPI_COVERAGE_THRESHOLD == 3


def test_cache_hit_skips_all_news_fetching():
    from datetime import datetime
    agent = _make_agent()
    agent._report_cache["NVDA"] = {
        "report": {"ticker": "NVDA", "cached": True},
        "time": datetime.now(),
        "price": 100.0,
    }
    agent.news_aggregator.fetch_news = MagicMock()
    agent.fetch_news = MagicMock()
    # Patch yfinance so the cache price-move check returns a small delta.
    with patch("yfinance.Ticker") as tk:
        tk.return_value.fast_info.get.return_value = 100.5  # 0.5% move < 2%
        out = agent.generate_report("NVDA")
    assert out == {"ticker": "NVDA", "cached": True}
    agent.fetch_news.assert_not_called()
    agent.news_aggregator.fetch_news.assert_not_called()

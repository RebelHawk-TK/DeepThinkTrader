"""Research Agent — Gathers news, Reddit sentiment, and technical data for a ticker.

Uses Alpaca Market Data API as primary source (with X-Request-ID capture),
falling back to yfinance if Alpaca data is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import praw
import yfinance as yf
from newsapi import NewsApiClient
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import Config
from utils.alpaca_data import AlpacaMarketData
from utils.database import Database
from utils.news_feeds import NewsAggregator
from utils.options_flow import OptionsFlowMonitor
from utils.rate_limiter import RateLimiter
from utils.seeking_alpha_rss import SeekingAlphaRSS
from utils.twelve_data import TwelveData
from utils.yahoo_fundamentals import YahooFundamentals

logger = logging.getLogger(__name__)


class ResearchAgent:
    def __init__(
        self,
        user_id: int,
        api_key: str,
        secret_key: str,
        db: Database | None = None,
    ):
        """Per-user research agent. Research reports written here inherit
        user_id so each user's historical research is isolated.
        """
        self.config = Config()
        self.db = db or Database()
        self.user_id = user_id
        self.rate_limiter = RateLimiter()
        self.alpaca_data = AlpacaMarketData(api_key=api_key, secret_key=secret_key, db=self.db)
        self.twelve_data = None  # Disabled — rate limits block 15min cycles. yfinance covers technicals.
        self.yahoo_fundamentals = YahooFundamentals()
        self.sa_rss = SeekingAlphaRSS()

        # Seeking Alpha email source: Gmail API (default) or vault file scan (legacy)
        if self.config.SA_SOURCE == "gmail" and self.config.SABRINA_API_KEY:
            from utils.gmail_seeking_alpha import GmailSeekingAlpha
            self.obsidian_sa = GmailSeekingAlpha()
            logger.info(f"SA emails: Gmail mode (label:{self.config.SA_GMAIL_LABEL}, account:{self.config.SA_EMAIL_ACCOUNT})")
        else:
            from utils.obsidian_seeking_alpha import ObsidianSeekingAlpha
            self.obsidian_sa = ObsidianSeekingAlpha(
                vault_path=self.config.OBSIDIAN_VAULT_PATH,
                max_age_days=self.config.OBSIDIAN_SA_MAX_AGE_DAYS,
            )
            logger.info("SA emails: Vault scan mode (legacy)")

        self.newsapi = NewsApiClient(api_key=self.config.NEWSAPI_KEY)
        self.vader = SentimentIntensityAnalyzer()

        # Multi-source news aggregator (5 additional APIs)
        try:
            self.news_aggregator = NewsAggregator(Config.get_news_config())
        except Exception as e:
            logger.warning(f"NewsAggregator init failed: {e}")
            self.news_aggregator = None

        # Options flow monitor (yfinance, free)
        self.options_monitor = OptionsFlowMonitor(cache_ttl_minutes=15)

        # Research report cache — avoids redundant API calls on 15min cycles
        self._report_cache: dict[str, dict] = {}

        # Reddit is optional — skip if credentials not configured
        if self.config.REDDIT_CLIENT_ID and self.config.REDDIT_CLIENT_ID != "your_reddit_client_id":
            self.reddit = praw.Reddit(
                client_id=self.config.REDDIT_CLIENT_ID,
                client_secret=self.config.REDDIT_CLIENT_SECRET,
                user_agent=self.config.REDDIT_USER_AGENT,
                timeout=10,
            )
            logger.info("Reddit (PRAW) initialized")
        else:
            self.reddit = None
            logger.debug("Reddit credentials not set — skipping sentiment analysis")

    def fetch_news(self, ticker: str, hours: int = 24) -> list[dict]:
        """Fetch recent news articles for a ticker from NewsAPI."""
        if not self.rate_limiter.can_call_newsapi():
            return []
        try:
            self.rate_limiter.record_newsapi_call()
            from_date = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d")
            response = self.newsapi.get_everything(
                q=ticker,
                from_param=from_date,
                language="en",
                sort_by="relevancy",
                page_size=5,
            )
            articles = []
            for article in response.get("articles", [])[:10]:
                title = article.get("title", "")
                description = article.get("description", "")
                text = f"{title}. {description}"
                sentiment = self.vader.polarity_scores(text)
                impact = round(sentiment["compound"] * 10, 1)  # Scale -10 to +10
                articles.append({
                    "title": title,
                    "source": article.get("source", {}).get("name", "Unknown"),
                    "published_at": article.get("publishedAt", ""),
                    "description": description,
                    "url": article.get("url", ""),
                    "impact_score": impact,
                })
            return articles
        except Exception as e:
            logger.error(f"NewsAPI error for {ticker}: {e}")
            return []

    def fetch_reddit_sentiment(self, ticker: str, hours: int = 6) -> dict:
        """Scrape Reddit for mentions and sentiment of a ticker."""
        if self.reddit is None:
            return {
                "ticker": ticker,
                "post_count": 0,
                "overall_sentiment": 0.0,
                "top_posts": [],
                "themes": ["Reddit not configured"],
            }

        posts = []
        overall_scores = []

        for sub_name in self.config.SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=50):
                    title_lower = post.title.lower()
                    ticker_lower = ticker.lower()
                    # Check if ticker is mentioned in title or selftext
                    if ticker_lower in title_lower or f"${ticker_lower}" in title_lower:
                        sentiment = self.vader.polarity_scores(post.title)
                        score = sentiment["compound"]
                        overall_scores.append(score)
                        posts.append({
                            "subreddit": sub_name,
                            "title": post.title,
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "sentiment": round(score, 3),
                            "url": f"https://reddit.com{post.permalink}",
                        })

                        # Also check top comments — skip viral posts where loading
                        # the comment tree can stall PRAW for 30s+ (e.g. WSB DDs).
                        if post.num_comments <= 200:
                            try:
                                post.comments.replace_more(limit=0)
                                for comment in post.comments[:5]:
                                    body = comment.body[:500]
                                    if ticker_lower in body.lower():
                                        c_sentiment = self.vader.polarity_scores(body)
                                        overall_scores.append(c_sentiment["compound"])
                            except Exception as ce:
                                logger.warning(
                                    f"Skipping comments for r/{sub_name} post "
                                    f"'{post.title[:40]}...': {ce}"
                                )
            except Exception as e:
                logger.error(f"Reddit error for r/{sub_name}: {e}")

        avg_sentiment = round(sum(overall_scores) / len(overall_scores), 3) if overall_scores else 0.0

        # Identify key themes
        themes = []
        all_text = " ".join(p["title"].lower() for p in posts)
        theme_keywords = {
            "short squeeze": "short squeeze talk",
            "fomo": "retail FOMO",
            "moon": "moonshot hype",
            "earnings": "earnings play",
            "overvalued": "overvaluation concern",
            "undervalued": "undervaluation thesis",
            "dip": "buy the dip sentiment",
            "bear": "bearish sentiment",
            "bull": "bullish sentiment",
        }
        for keyword, theme in theme_keywords.items():
            if keyword in all_text:
                themes.append(theme)

        return {
            "ticker": ticker,
            "post_count": len(posts),
            "overall_sentiment": avg_sentiment,
            "top_posts": posts[:20],
            "themes": themes if themes else ["low Reddit activity"],
        }

    def _fetch_intraday_trend(self, ticker: str) -> dict:
        """Fetch 1-hour bars for the past 5 trading days and classify trend.

        Returns {"available": bool, "trend": "bullish"|"bearish"|"neutral",
                 "above_sma_1h": bool, "rsi_1h": float, "n_bars": int}.

        Used by DeepThinkAgent as a confirmation modifier — if 1h trend
        agrees with the daily catalyst direction, conviction nudges up;
        if they disagree, conviction is docked. Failures default to
        neutral (no effect on decisions).
        """
        try:
            bars = self.alpaca_data.get_bars(ticker, timeframe="1Hour", days=7)
            if bars.empty or len(bars) < 10:
                return {"available": False, "trend": "neutral",
                        "above_sma_1h": False, "rsi_1h": 50.0, "n_bars": len(bars)}
            closes = bars["close"]
            sma = closes.tail(10).mean()
            current = float(closes.iloc[-1])
            above_sma = current > float(sma)
            # Simple RSI(14) on 1h bars
            delta = closes.diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi_1h = float((100 - (100 / (1 + rs))).iloc[-1]) if not rs.empty else 50.0
            # Trend: above sma + rsi > 55 = bullish; below sma + rsi < 45 = bearish
            if above_sma and rsi_1h > 55:
                trend = "bullish"
            elif (not above_sma) and rsi_1h < 45:
                trend = "bearish"
            else:
                trend = "neutral"
            return {"available": True, "trend": trend, "above_sma_1h": above_sma,
                    "rsi_1h": round(rsi_1h, 1), "n_bars": len(bars)}
        except Exception as e:
            logger.debug(f"Intraday fetch failed for {ticker}: {e}")
            return {"available": False, "trend": "neutral",
                    "above_sma_1h": False, "rsi_1h": 50.0, "n_bars": 0}

    def fetch_technicals(self, ticker: str) -> dict:
        """Fetch technicals via Alpaca Market Data API (primary), yfinance (fallback).

        Alpaca calls capture X-Request-ID for every request.
        """
        # Primary: Alpaca Market Data
        result = self.alpaca_data.get_technicals(ticker)
        if "error" not in result:
            logger.info(f"Technicals for {ticker} sourced from Alpaca")
            return result

        # Fallback: yfinance
        logger.warning(f"Alpaca data unavailable for {ticker}, falling back to yfinance")
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo")

            if hist.empty:
                return {"ticker": ticker, "error": "No data available", "source": "yfinance"}

            current = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else current

            sma_10 = round(hist["Close"].tail(10).mean(), 2)
            sma_20 = round(hist["Close"].tail(20).mean(), 2)

            avg_volume = int(hist["Volume"].mean())
            current_volume = int(current["Volume"])

            delta = hist["Close"].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 1) if not rsi.empty else 50.0

            return {
                "ticker": ticker,
                "source": "yfinance",
                "current_price": round(current["Close"], 2),
                "previous_close": round(prev["Close"], 2),
                "daily_change_pct": round(
                    ((current["Close"] - prev["Close"]) / prev["Close"]) * 100, 2
                ),
                "current_volume": current_volume,
                "avg_volume": avg_volume,
                "volume_ratio": round(current_volume / avg_volume, 2) if avg_volume > 0 else 0,
                "sma_10": sma_10,
                "sma_20": sma_20,
                "rsi_14": current_rsi,
                "above_sma_10": current["Close"] > sma_10,
                "above_sma_20": current["Close"] > sma_20,
                "high_52w": round(hist["Close"].max(), 2),
                "low_52w": round(hist["Close"].min(), 2),
            }
        except Exception as e:
            logger.error(f"yfinance error for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e), "source": "yfinance"}

    @staticmethod
    def _fetch_market_regime() -> dict:
        """Fetch VIX level and market breadth (advance/decline ratio) for regime detection."""
        try:
            import yfinance as yf

            result = {}

            # VIX level
            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="5d")
            if not vix_hist.empty:
                result["vix"] = round(float(vix_hist["Close"].iloc[-1]), 2)
                if len(vix_hist) >= 2:
                    result["vix_prev"] = round(float(vix_hist["Close"].iloc[-2]), 2)
                    result["vix_change"] = round(result["vix"] - result["vix_prev"], 2)

            # Market breadth via advance/decline proxy
            # Use S&P 500 component ETFs as breadth indicator
            breadth_tickers = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
            advancing = 0
            total = 0
            for sym in breadth_tickers:
                try:
                    h = yf.Ticker(sym).history(period="2d")
                    if len(h) >= 2:
                        total += 1
                        if h["Close"].iloc[-1] > h["Close"].iloc[-2]:
                            advancing += 1
                except Exception:
                    continue

            if total > 0:
                result["breadth_ratio"] = round(advancing / total, 2)
                result["sectors_advancing"] = advancing
                result["sectors_total"] = total

            logger.info(
                f"Market regime: VIX={result.get('vix', '?')}, "
                f"Breadth={result.get('breadth_ratio', '?')} "
                f"({result.get('sectors_advancing', 0)}/{result.get('sectors_total', 0)} sectors up)"
            )
            return result
        except Exception as e:
            logger.warning(f"Market regime fetch failed: {e}")
            return {}

    # Cache: 4h base TTL, but price movement >2% invalidates. 15min was too
    # tight for free-tier NewsAPI — burned the 100/day quota in ~5 cycles.
    # 4h + price-move guard still catches breaking news while letting the
    # same ticker avoid re-burning the quota all afternoon.
    _REPORT_CACHE_TTL_SECONDS = 4 * 3600
    # If the 5-source aggregator returned at least this many articles, we
    # have enough news coverage and skip the free-tier NewsAPI call.
    _NEWSAPI_COVERAGE_THRESHOLD = 3

    def generate_report(self, ticker: str, news_priority: str = "medium") -> dict:
        """Generate a full research report combining all sources.

        news_priority: "high"/"medium"/"low" — routes aggregator to more/fewer sources
        to respect API budgets. Top-conviction tickers should get "high".
        """
        cached = self._report_cache.get(ticker)
        if cached:
            age_secs = (datetime.now() - cached["time"]).total_seconds()
            if age_secs < self._REPORT_CACHE_TTL_SECONDS:
                try:
                    import yfinance as _yf
                    snap_price = _yf.Ticker(ticker).fast_info.get("lastPrice", 0)
                    if snap_price and cached["price"] > 0:
                        price_change = abs(snap_price - cached["price"]) / cached["price"]
                        if price_change < 0.02:
                            logger.info(
                                f"Cache hit for {ticker} "
                                f"(age={age_secs / 60:.0f}min, move={price_change:.1%})"
                            )
                            return cached["report"]
                except Exception:
                    pass

        logger.info(f"Generating research report for {ticker}...")

        # Aggregator first — 5 free news sources. Only fall back to NewsAPI
        # (100/day quota) when aggregator coverage is thin.
        aggregated_articles = []
        agg_sentiment = 0.0
        if self.news_aggregator:
            try:
                aggregated_articles = self.news_aggregator.fetch_news(ticker, priority=news_priority)
                agg_sentiment = self.news_aggregator.compute_sentiment(aggregated_articles)
                logger.info(
                    f"Aggregated news for {ticker}: {len(aggregated_articles)} articles, "
                    f"sentiment={agg_sentiment:+.3f}"
                )
            except Exception as e:
                logger.error(f"NewsAggregator error for {ticker}: {e}")

        if len(aggregated_articles) >= self._NEWSAPI_COVERAGE_THRESHOLD:
            news = []
            logger.info(
                f"NewsAPI skipped for {ticker} "
                f"({len(aggregated_articles)} articles already from aggregator — saving quota)"
            )
        else:
            news = self.fetch_news(ticker)

        reddit = self.fetch_reddit_sentiment(ticker)
        technicals = self.fetch_technicals(ticker)
        intraday = self._fetch_intraday_trend(ticker)

        # Fetch advanced technicals from Twelve Data
        advanced_technicals = {}
        if self.twelve_data:
            try:
                advanced_technicals = self.twelve_data.get_full_technicals(ticker)
            except Exception as e:
                logger.error(f"Twelve Data error for {ticker}: {e}")

        # Fetch Yahoo Finance fundamentals
        fundamentals = {}
        try:
            fundamentals = self.yahoo_fundamentals.get_fundamentals(ticker)
        except Exception as e:
            logger.error(f"Yahoo fundamentals error for {ticker}: {e}")

        # Fetch Seeking Alpha intelligence from Obsidian emails
        sa_intel = {}
        try:
            sa_intel = self.obsidian_sa.get_ticker_intel(ticker)
        except Exception as e:
            logger.error(f"Obsidian SA error for {ticker}: {e}")

        # Fetch Seeking Alpha RSS feed data (articles + news)
        sa_rss_intel = {}
        try:
            sa_rss_intel = self.sa_rss.get_ticker_intel(ticker)
            if sa_rss_intel.get("article_count", 0) > 0:
                logger.info(
                    f"SA RSS for {ticker}: {sa_rss_intel['article_count']} articles, "
                    f"sentiment={sa_rss_intel['avg_sentiment']:+.3f}, "
                    f"bull/bear={sa_rss_intel['bullish_count']}/{sa_rss_intel['bearish_count']}"
                )
        except Exception as e:
            logger.error(f"SA RSS error for {ticker}: {e}")

        # Merge Obsidian + RSS SA intel — RSS takes priority for sentiment (more data)
        if sa_rss_intel.get("article_count", 0) > 0:
            # Combine: use RSS sentiment if available (more articles = better signal)
            rss_sent = sa_rss_intel.get("avg_sentiment", 0)
            obs_sent = sa_intel.get("avg_sentiment", 0)
            if sa_intel.get("mentioned") and abs(obs_sent) > 0:
                # Weighted average: RSS 70%, Obsidian 30% (RSS has more data)
                combined_sa_sent = rss_sent * 0.7 + obs_sent * 0.3
            else:
                combined_sa_sent = rss_sent
            sa_intel = {
                **sa_intel,
                "mentioned": True,
                "avg_sentiment": round(combined_sa_sent, 3),
                "categories": sorted(set(
                    sa_intel.get("categories", []) + sa_rss_intel.get("categories", [])
                )),
                "mention_count": (
                    sa_intel.get("mention_count", 0) + sa_rss_intel.get("article_count", 0)
                ),
                "rss_articles": sa_rss_intel.get("articles", [])[:5],
                "rss_bullish": sa_rss_intel.get("bullish_count", 0),
                "rss_bearish": sa_rss_intel.get("bearish_count", 0),
            }

        # Fetch options flow (unusual activity detection)
        options_flow = {}
        try:
            options_flow = self.options_monitor.scan_unusual_activity(ticker)
        except Exception as e:
            logger.error(f"Options flow error for {ticker}: {e}")

        # Calculate combined scores
        newsapi_impact = (
            round(sum(a["impact_score"] for a in news) / len(news), 1) if news else 0
        )
        # Blend NewsAPI score with aggregated multi-source sentiment
        # newsapi_impact is -10..+10, agg_sentiment is -1..+1; normalize both to -1..+1
        if news and aggregated_articles:
            # Both available: weighted blend (NewsAPI 40%, aggregated 60%)
            news_impact = round((newsapi_impact / 10) * 0.4 + agg_sentiment * 0.6, 3) * 10
        elif aggregated_articles:
            news_impact = round(agg_sentiment * 10, 1)
        else:
            news_impact = newsapi_impact
        reddit_score = reddit["overall_sentiment"]

        # Combined catalyst score: news 30%, reddit 20%, basic technicals 20%, advanced 30%
        tech_score = 0
        if "error" not in technicals:
            if technicals.get("rsi_14", 50) < 30:
                tech_score = 0.5
            elif technicals.get("rsi_14", 50) > 70:
                tech_score = -0.5
            if technicals.get("above_sma_10"):
                tech_score += 0.3
            if technicals.get("volume_ratio", 1) > 1.5:
                tech_score += 0.2

        # Advanced technicals score from Twelve Data
        adv_score = 0
        if advanced_technicals:
            macd = advanced_technicals.get("macd", {})
            if macd.get("crossover") == "bullish":
                adv_score += 0.4
            elif macd.get("crossover") == "bearish":
                adv_score -= 0.4
            elif macd.get("trend") == "bullish":
                adv_score += 0.15
            elif macd.get("trend") == "bearish":
                adv_score -= 0.15

            ema = advanced_technicals.get("ema", {})
            if ema.get("crossover") == "bullish":
                adv_score += 0.3
            elif ema.get("crossover") == "bearish":
                adv_score -= 0.3

            stoch = advanced_technicals.get("stoch", {})
            if stoch.get("zone") == "oversold" and stoch.get("crossover") == "bullish":
                adv_score += 0.3
            elif stoch.get("zone") == "overbought" and stoch.get("crossover") == "bearish":
                adv_score -= 0.3

            adx = advanced_technicals.get("adx", {})
            if adx.get("trend_strength") in ("strong", "very_strong"):
                # Amplify existing signal when trend is strong
                adv_score *= 1.3

        # Seeking Alpha sentiment score (scaled to -1..+1 range)
        sa_score = 0.0
        has_sa = sa_intel.get("mentioned", False)
        if has_sa:
            sa_score = sa_intel["avg_sentiment"]
            # Boost if SA categorizes as earnings/insider/analyst (higher signal)
            sa_cats = sa_intel.get("categories", [])
            if any(c in sa_cats for c in ["insider_activity", "analyst", "earnings"]):
                sa_score *= 1.3
            sa_score = max(-1.0, min(1.0, sa_score))

        # Options flow score (-1..+1)
        opt_score = options_flow.get("signal_strength", 0.0) if options_flow else 0.0
        has_options = bool(options_flow and options_flow.get("unusual_strikes", 0) > 0)

        # Dynamically reweight when data sources are unavailable
        has_news = len(news) > 0 or len(aggregated_articles) > 0
        has_reddit = self.reddit is not None and reddit["post_count"] > 0
        has_adv = bool(advanced_technicals)

        # Base weights: news 20%, reddit 10%, options 15%, tech 20%, advanced 20%, SA 15%
        if has_news and has_reddit:
            w_news, w_reddit, w_opt, w_tech, w_adv, w_sa = 0.20, 0.10, 0.15, 0.20, 0.20, 0.15
        elif has_news:
            w_news, w_reddit, w_opt, w_tech, w_adv, w_sa = 0.25, 0.0, 0.15, 0.20, 0.20, 0.20
        elif has_reddit:
            w_news, w_reddit, w_opt, w_tech, w_adv, w_sa = 0.0, 0.15, 0.15, 0.25, 0.25, 0.20
        else:
            w_news, w_reddit, w_opt, w_tech, w_adv, w_sa = 0.0, 0.0, 0.20, 0.30, 0.30, 0.20

        if not has_options:
            # Redistribute options weight to news and tech
            w_news += w_opt * 0.5
            w_tech += w_opt * 0.5
            w_opt = 0.0

        if not has_adv:
            w_tech += w_adv
            w_adv = 0.0

        if not has_sa:
            w_news += w_sa * 0.5
            w_tech += w_sa * 0.5
            w_sa = 0.0

        combined = round(
            (news_impact / 10 * w_news)
            + (reddit_score * w_reddit)
            + (opt_score * w_opt)
            + (tech_score * w_tech)
            + (adv_score * w_adv)
            + (sa_score * w_sa),
            3,
        )

        # Identify risks and opportunities
        risks = []
        opportunities = []

        if news_impact < -3:
            risks.append("Strongly negative news sentiment")
        if reddit_score < -0.3:
            risks.append("Negative Reddit sentiment — potential retail selloff")
        if technicals.get("rsi_14", 50) > 70:
            risks.append("RSI overbought — potential pullback")
        if technicals.get("volume_ratio", 1) < 0.5:
            risks.append("Low volume — weak conviction in current move")

        # Advanced technical risks/opportunities
        if advanced_technicals:
            macd = advanced_technicals.get("macd", {})
            if macd.get("crossover") == "bearish":
                risks.append("MACD bearish crossover — momentum shifting down")
            elif macd.get("crossover") == "bullish":
                opportunities.append("MACD bullish crossover — momentum shifting up")

            bbands = advanced_technicals.get("bbands", {})
            current_price = technicals.get("current_price", 0)
            if bbands and current_price:
                if current_price > bbands.get("upper", float("inf")):
                    risks.append(f"Price above Bollinger upper band — overextended")
                elif current_price < bbands.get("lower", 0):
                    opportunities.append(f"Price below Bollinger lower band — potential snap-back")
                if bbands.get("bandwidth_pct", 10) < 5:
                    opportunities.append("Bollinger squeeze — breakout imminent")

            stoch = advanced_technicals.get("stoch", {})
            if stoch.get("zone") == "overbought":
                risks.append(f"Stochastic overbought ({stoch.get('k', 0):.0f})")
            elif stoch.get("zone") == "oversold":
                opportunities.append(f"Stochastic oversold ({stoch.get('k', 0):.0f}) — bounce setup")

            ema = advanced_technicals.get("ema", {})
            if ema.get("crossover") == "bullish":
                opportunities.append("EMA 9/21 bullish crossover — short-term uptrend")
            elif ema.get("crossover") == "bearish":
                risks.append("EMA 9/21 bearish crossover — short-term downtrend")

            adx = advanced_technicals.get("adx", {})
            if adx.get("trend_strength") == "weak":
                risks.append("ADX weak — no clear trend, range-bound market")

        if news_impact > 3:
            opportunities.append("Strong positive news catalyst")
        if reddit_score > 0.3:
            opportunities.append("Positive Reddit buzz — potential retail inflow")
        if technicals.get("rsi_14", 50) < 30:
            opportunities.append("RSI oversold — potential bounce")
        if technicals.get("above_sma_10") and technicals.get("above_sma_20"):
            opportunities.append("Price above key moving averages — uptrend intact")

        # Seeking Alpha email intelligence
        if has_sa:
            sa_cats = sa_intel.get("categories", [])
            sa_sent = sa_intel.get("avg_sentiment", 0)
            if "insider_activity" in sa_cats:
                if sa_sent > 0:
                    opportunities.append("SA: Insider buying activity noted")
                else:
                    risks.append("SA: Insider selling activity noted")
            if "earnings" in sa_cats:
                risks.append("SA: Earnings event highlighted — elevated volatility expected")
            if "momentum" in sa_cats and sa_sent > 0:
                opportunities.append("SA: Positive momentum flagged by Seeking Alpha")
            if "risk" in sa_cats:
                risks.append("SA: Risk factors highlighted in Seeking Alpha coverage")
            if "analyst" in sa_cats:
                if sa_sent > 0:
                    opportunities.append("SA: Favorable analyst coverage")
                else:
                    risks.append("SA: Negative analyst coverage")
            if "dividend" in sa_cats:
                opportunities.append("SA: Dividend/yield play highlighted")
            if sa_sent > 0.3 and "general_mention" not in sa_cats:
                opportunities.append(f"SA: Strong positive sentiment ({sa_sent:.2f})")
            elif sa_sent < -0.3:
                risks.append(f"SA: Negative sentiment in coverage ({sa_sent:.2f})")

        # Fundamental risks/opportunities from Yahoo Finance
        if fundamentals:
            earnings = fundamentals.get("earnings", {})
            if earnings.get("imminent"):
                risks.append(f"Earnings in {earnings.get('days_until', '?')} days — high event risk")

            analyst = fundamentals.get("analyst", {})
            upside = analyst.get("upside_pct")
            if upside is not None:
                if upside > 20:
                    opportunities.append(f"Analyst target implies {upside}% upside")
                elif upside < -10:
                    risks.append(f"Analyst target implies {abs(upside)}% downside")

            if analyst.get("recommendation") in ("strong_buy", "buy"):
                opportunities.append(f"Analyst consensus: {analyst['recommendation']}")
            elif analyst.get("recommendation") in ("sell", "strong_sell"):
                risks.append(f"Analyst consensus: {analyst['recommendation']}")

            insider = fundamentals.get("insider", {})
            if insider.get("signal") == "net_buying":
                opportunities.append("Insider net buying — management bullish")
            elif insider.get("signal") == "net_selling":
                risks.append("Insider net selling — management cashing out")

            fins = fundamentals.get("financials", {})
            pe = fins.get("pe_ratio")
            if pe and pe > 50:
                risks.append(f"High P/E ratio ({pe:.0f}) — expensive valuation")
            elif pe and pe < 15 and pe > 0:
                opportunities.append(f"Low P/E ratio ({pe:.0f}) — value opportunity")

            rev_growth = fins.get("revenue_growth")
            if rev_growth and rev_growth > 0.2:
                opportunities.append(f"Strong revenue growth ({rev_growth*100:.0f}%)")
            elif rev_growth and rev_growth < -0.05:
                risks.append(f"Revenue declining ({rev_growth*100:.0f}%)")

        # Market regime data: VIX + advance/decline breadth
        market_regime = self._fetch_market_regime()
        if market_regime:
            vix = market_regime.get("vix", 0)
            if vix >= 30:
                risks.append(f"VIX at {vix:.1f} — extreme fear regime")
            elif vix >= 25:
                risks.append(f"VIX elevated at {vix:.1f} — heightened volatility")
            elif vix < 15:
                opportunities.append(f"VIX low at {vix:.1f} — calm market conditions")

            breadth = market_regime.get("breadth_ratio", 0)
            if breadth > 0.6:
                opportunities.append(f"Broad market participation ({breadth:.0%} advancing)")
            elif breadth < 0.4:
                risks.append(f"Narrow breadth ({breadth:.0%} advancing) — weak participation")

        # Options flow risks/opportunities
        if options_flow:
            if options_flow.get("bullish_flow"):
                pc = options_flow.get("put_call_ratio", 1.0)
                prem = options_flow.get("total_unusual_premium", 0)
                opportunities.append(f"Bullish options flow (P/C={pc:.2f}, unusual premium ${prem:,.0f})")
            elif options_flow.get("bearish_flow"):
                pc = options_flow.get("put_call_ratio", 1.0)
                prem = options_flow.get("total_unusual_premium", 0)
                risks.append(f"Bearish options flow (P/C={pc:.2f}, unusual premium ${prem:,.0f})")

        # Pad to at least 3 each
        while len(risks) < 3:
            risks.append("No additional risk factors identified")
        while len(opportunities) < 3:
            opportunities.append("No additional opportunity factors identified")

        report = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "news_impact_score": news_impact,
            "reddit_sentiment_score": reddit_score,
            "combined_catalyst_score": combined,
            "news_articles": news[:5],
            "aggregated_news": {
                "article_count": len(aggregated_articles),
                "sentiment": round(agg_sentiment, 3),
                "sources_used": list({a.source_api.value for a in aggregated_articles}),
                "top_headlines": [a.headline for a in aggregated_articles[:5]],
                "budget": self.news_aggregator.get_budget_status() if self.news_aggregator else {},
            },
            "reddit_data": reddit,
            "technicals": technicals,
            "intraday": intraday,
            "advanced_technicals": advanced_technicals,
            "fundamentals": fundamentals,
            "seeking_alpha": sa_intel,
            "options_flow": options_flow,
            "market_regime": market_regime,
            "risks": risks[:7],
            "opportunities": opportunities[:7],
        }

        # Save to database
        self.db.save_research(self.user_id, ticker, report)
        logger.info(f"Research report saved for {ticker} (catalyst: {combined})")

        # Cache report for 15min cycle reuse
        current_price = technicals.get("current_price", 0)
        self._report_cache[ticker] = {
            "report": report,
            "time": datetime.now(),
            "price": current_price,
        }

        return report

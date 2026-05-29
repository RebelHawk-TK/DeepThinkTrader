"""Weekend / pre-market news sweep — rule-scored news polling for Mon-open prep.

Runs Sat 09:00, Sun 17:00, and weekday 08:30 ET. Pulls news for open positions +
WATCHLIST, scores via existing aggregator sentiment (no LLM), writes a digest, and
stashes JSON state that the next live cycle reads on Monday open.

Read-only: never opens trades, never calls Claude.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from utils.news_feeds.news_aggregator import NewsAggregator
from utils.news_feeds.news_models import NewsArticle

logger = logging.getLogger(__name__)


@dataclass
class TickerScore:
    ticker: str
    news_impact: float  # -10 .. +10, weighted sentiment × 10
    sentiment_avg: float  # -1 .. +1
    source_count: int
    article_count: int
    top_headlines: list[str] = field(default_factory=list)
    alert_tier: str = "LOW"  # HIGH | MED | LOW

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "news_impact": round(self.news_impact, 2),
            "sentiment_avg": round(self.sentiment_avg, 3),
            "source_count": self.source_count,
            "article_count": self.article_count,
            "top_headlines": self.top_headlines,
            "alert_tier": self.alert_tier,
        }


class WeekendBrief:
    """Orchestrates the weekend/pre-market sweep for a single user."""

    def __init__(self, db, config, news_aggregator: NewsAggregator | None = None):
        self.db = db
        self.config = config
        # Build a fresh aggregator if the caller doesn't pass one — keeps the
        # weekend sweep isolated from the per-user ResearchAgent lifecycle.
        self.news = news_aggregator or NewsAggregator(config.get_news_config())

    # ── ticker collection ────────────────────────────────────────

    def collect_tickers(self, user_id: int) -> list[str]:
        """Open positions for this user + static WATCHLIST, deduped, uppercased."""
        seen: set[str] = set()
        ordered: list[str] = []

        for trade in self.db.get_open_trades(user_id):
            t = (trade.get("ticker") or "").upper().strip()
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)

        for t in self.config.WATCHLIST:
            t = (t or "").upper().strip()
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)

        return ordered

    # ── scoring ──────────────────────────────────────────────────

    def score_ticker(self, ticker: str) -> TickerScore:
        """Fetch news at medium priority (skips Marketaux) and rule-score it."""
        try:
            articles: list[NewsArticle] = self.news.fetch_news(ticker, priority="medium", limit=15)
        except Exception as e:
            logger.warning(f"weekend sweep: fetch_news failed for {ticker}: {e}")
            articles = []

        if not articles:
            return TickerScore(ticker=ticker, news_impact=0.0, sentiment_avg=0.0,
                               source_count=0, article_count=0)

        sentiment_avg = self.news.compute_sentiment(articles)
        news_impact = sentiment_avg * 10.0
        source_count = len({a.source_api for a in articles})

        # Pick the headlines that move sentiment most — top by |sentiment_score|,
        # falling back to most recent if nothing scored. Keep 3 max.
        scored = sorted(articles, key=lambda a: abs(a.sentiment_score), reverse=True)
        top = [a.headline for a in scored[:3] if a.headline]

        score = TickerScore(
            ticker=ticker,
            news_impact=news_impact,
            sentiment_avg=sentiment_avg,
            source_count=source_count,
            article_count=len(articles),
            top_headlines=top,
        )
        score.alert_tier = self._classify(score)
        return score

    def _classify(self, s: TickerScore) -> str:
        high_thresh = self.config.WEEKEND_HIGH_ALERT_THRESHOLD
        min_sources = self.config.WEEKEND_HIGH_ALERT_MIN_SOURCES
        if abs(s.news_impact) >= high_thresh and s.source_count >= min_sources:
            return "HIGH"
        if abs(s.news_impact) >= 5.0:
            return "MED"
        return "LOW"

    # ── sweep orchestration ──────────────────────────────────────

    def sweep(self, user_id: int, label: str) -> dict:
        """Run the full sweep for one user. Returns a result dict ready for digest write.

        label: short tag for the run — "weekend_sat", "weekend_sun", "premarket".
        """
        tickers = self.collect_tickers(user_id)
        if not tickers:
            logger.info(f"weekend sweep [{label}] user={user_id}: no tickers")
            return {"label": label, "user_id": user_id, "generated_at": _now_iso(),
                    "tickers": [], "summary": {"high": 0, "med": 0, "low": 0}}

        logger.info(f"weekend sweep [{label}] user={user_id}: scoring {len(tickers)} tickers — "
                    f"{', '.join(tickers)}")

        scores: list[TickerScore] = []
        for t in tickers:
            try:
                scores.append(self.score_ticker(t))
            except Exception as e:
                logger.error(f"weekend sweep: score_ticker({t}) failed: {e}", exc_info=True)

        # Sort: HIGH first, then by absolute impact descending.
        tier_rank = {"HIGH": 0, "MED": 1, "LOW": 2}
        scores.sort(key=lambda s: (tier_rank[s.alert_tier], -abs(s.news_impact)))

        summary = {
            "high": sum(1 for s in scores if s.alert_tier == "HIGH"),
            "med": sum(1 for s in scores if s.alert_tier == "MED"),
            "low": sum(1 for s in scores if s.alert_tier == "LOW"),
        }
        result = {
            "label": label,
            "user_id": user_id,
            "generated_at": _now_iso(),
            "tickers": [s.to_dict() for s in scores],
            "summary": summary,
        }
        logger.info(f"weekend sweep [{label}] complete: {summary['high']} HIGH, "
                    f"{summary['med']} MED, {summary['low']} LOW")
        return result

    # ── outputs ──────────────────────────────────────────────────

    def write_digest(self, result: dict) -> tuple[Path, Path | None]:
        """Write markdown digest to repo digests/ dir + copy into vault.

        Returns (repo_path, vault_path_or_None). Vault path may be None if the
        vault directory isn't reachable — sweep keeps running.
        """
        label = result.get("label", "sweep")
        date_tag = datetime.now().strftime("%Y-%m-%d")
        filename = f"{label}_{date_tag}.md"

        repo_dir = Path(self.config.WEEKEND_BRIEF_DIR)
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo_path = repo_dir / filename
        repo_path.write_text(self._render_markdown(result), encoding="utf-8")

        vault_path: Path | None = None
        try:
            vault_dir = Path(self.config.WEEKEND_VAULT_BRIEF_DIR)
            vault_dir.mkdir(parents=True, exist_ok=True)
            vault_path = vault_dir / filename
            shutil.copy2(repo_path, vault_path)
        except Exception as e:
            logger.warning(f"weekend sweep: vault copy failed ({e}) — repo digest still written")

        return repo_path, vault_path

    def _render_markdown(self, result: dict) -> str:
        label = result["label"]
        generated = result["generated_at"]
        summary = result["summary"]
        tickers = result["tickers"]

        lines = [
            f"# Weekend Brief — {label} ({generated})",
            "",
            f"**Summary:** {summary['high']} HIGH, {summary['med']} MED, {summary['low']} LOW",
            "",
        ]

        if not tickers:
            lines.append("_No tickers scored._")
            return "\n".join(lines) + "\n"

        # HIGH section
        highs = [t for t in tickers if t["alert_tier"] == "HIGH"]
        if highs:
            lines.append("## HIGH alerts")
            lines.append("")
            for t in highs:
                lines.append(f"### {t['ticker']}  (impact {t['news_impact']:+.1f}, "
                             f"{t['source_count']} sources, {t['article_count']} articles)")
                for h in t["top_headlines"]:
                    lines.append(f"- {h}")
                lines.append("")

        # MED section
        meds = [t for t in tickers if t["alert_tier"] == "MED"]
        if meds:
            lines.append("## MED")
            lines.append("")
            for t in meds:
                top = t["top_headlines"][0] if t["top_headlines"] else "(no headlines)"
                lines.append(f"- **{t['ticker']}** (impact {t['news_impact']:+.1f}, "
                             f"{t['source_count']} sources): {top}")
            lines.append("")

        # LOW table
        lows = [t for t in tickers if t["alert_tier"] == "LOW"]
        if lows:
            lines.append("## LOW")
            lines.append("")
            lines.append("| Ticker | Impact | Sources | Articles |")
            lines.append("|---|---|---|---|")
            for t in lows:
                lines.append(f"| {t['ticker']} | {t['news_impact']:+.1f} | "
                             f"{t['source_count']} | {t['article_count']} |")
            lines.append("")

        return "\n".join(lines) + "\n"

    def write_state(self, result: dict) -> Path:
        """Persist most-recent sweep result for Monday cycle hydration."""
        data_dir = Path(os.path.dirname(__file__)).parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "last_weekend_brief.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return path

    def maybe_alert_slack(self, result: dict) -> None:
        """Fire Slack notification per HIGH-tier ticker if WEEKEND_SLACK_DM=true."""
        if not self.config.WEEKEND_SLACK_DM:
            return
        from utils.notifications import notify_weekend_high_alert
        for t in result["tickers"]:
            if t["alert_tier"] != "HIGH":
                continue
            try:
                notify_weekend_high_alert(t["ticker"], t["news_impact"], t["top_headlines"])
            except Exception as e:
                logger.warning(f"weekend sweep: Slack alert failed for {t['ticker']}: {e}")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

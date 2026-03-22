"""Obsidian Seeking Alpha Reader — Parses SA newsletter emails from an Obsidian vault.

Scans for Seeking Alpha email notes, extracts ticker mentions with surrounding context,
and scores sentiment to feed into the research pipeline.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta

import yaml
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

# Regex: ticker in parentheses — handles both `(GME)` and `(GME (url))` SA format
_TICKER_RE = re.compile(r"\(([A-Z]{1,5})(?:\s|\))")
_SKIP_WORDS = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
    "WAS", "ONE", "OUR", "OUT", "DAY", "HAD", "HAS", "HIS", "HOW", "ITS",
    "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "HIM",
    "LET", "SAY", "SHE", "TOO", "USE", "CEO", "CFO", "IPO", "GDP", "PMI",
    "ETF", "SEC", "FED", "AI", "US", "UK", "EU", "Q1", "Q2", "Q3", "Q4",
    "AM", "PM", "VS", "COM", "EST", "PST", "LLC", "INC", "NYSE", "NASDAQ",
}


class ObsidianSeekingAlpha:
    """Reads Seeking Alpha emails from an Obsidian vault and extracts ticker intelligence."""

    def __init__(self, vault_path: str | None = None, max_age_days: int = 7):
        self.vault_path = vault_path or os.getenv(
            "OBSIDIAN_VAULT_PATH",
            os.path.expanduser("~/Documents/RHVault/RHVault"),
        )
        self.max_age_days = max_age_days
        self.vader = SentimentIntensityAnalyzer()
        self._cache: dict[str, list[dict]] | None = None
        self._cache_time: datetime | None = None

    def _find_sa_files(self) -> list[str]:
        """Find all Seeking Alpha email files in the vault."""
        email_dir = os.path.join(self.vault_path, "Email")
        if not os.path.isdir(email_dir):
            logger.warning(f"Obsidian Email directory not found: {email_dir}")
            return []

        sa_files = []
        cutoff = datetime.now() - timedelta(days=self.max_age_days)
        real_email_dir = os.path.realpath(email_dir)

        for root, _, files in os.walk(email_dir):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(root, fname)
                # Security: prevent path traversal outside the vault
                if not os.path.realpath(fpath).startswith(real_email_dir):
                    logger.warning(f"Path traversal blocked: {fpath}")
                    continue
                try:
                    front = self._read_frontmatter(fpath)
                    if not front:
                        continue
                    sender = front.get("from", "")
                    if "seekingalpha.com" not in sender.lower():
                        continue
                    date_str = front.get("date", "")
                    if date_str:
                        file_date = self._parse_date(date_str)
                        if file_date and file_date < cutoff:
                            continue
                    sa_files.append(fpath)
                except Exception as e:
                    logger.debug(f"Skipping {fpath}: {e}")

        logger.info(f"Found {len(sa_files)} Seeking Alpha emails in Obsidian (last {self.max_age_days} days)")
        return sa_files

    def _read_frontmatter(self, filepath: str) -> dict | None:
        """Read YAML frontmatter from a markdown file."""
        # Security: reject files larger than 1MB to prevent memory exhaustion
        if os.path.getsize(filepath) > 1_000_000:
            logger.warning(f"File too large, skipping: {filepath}")
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read(2000)  # frontmatter is at the top
        if not content.startswith("---"):
            return None
        end = content.find("---", 3)
        if end == -1:
            return None
        try:
            return yaml.safe_load(content[3:end])
        except yaml.YAMLError:
            return None

    def _parse_date(self, date_str: str) -> datetime | None:
        """Parse date from frontmatter (ISO format with timezone)."""
        if isinstance(date_str, datetime):
            return date_str
        try:
            # Handle ISO format: 2026-03-22T07:04:02-0400
            clean = str(date_str).replace("T", " ")
            # Strip timezone offset for parsing
            clean = re.sub(r"[+-]\d{4}$", "", clean).strip()
            return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                return datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                return None

    def _read_file_body(self, filepath: str) -> str:
        """Read the markdown body (after frontmatter)."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                return content[end + 3:]
        return content

    def _extract_ticker_mentions(self, body: str) -> dict[str, list[str]]:
        """Extract tickers and their surrounding context sentences."""
        # Strip URLs to avoid false matches from URL garbage
        clean = re.sub(r"https?://\S+", "", body)
        # Collapse whitespace
        clean = re.sub(r"\s+", " ", clean)

        ticker_contexts: dict[str, list[str]] = {}

        for match in _TICKER_RE.finditer(clean):
            ticker = match.group(1)
            if ticker in _SKIP_WORDS or len(ticker) < 2:
                continue

            # Get ~200 chars of context around the mention
            start = max(0, match.start() - 150)
            end = min(len(clean), match.end() + 150)
            context = clean[start:end].strip()

            if ticker not in ticker_contexts:
                ticker_contexts[ticker] = []
            ticker_contexts[ticker].append(context)

        return ticker_contexts

    def _classify_mention(self, contexts: list[str]) -> dict:
        """Classify a ticker mention: sentiment, categories, and key phrases."""
        all_text = " ".join(contexts)
        sentiment = self.vader.polarity_scores(all_text)

        categories = []
        lower = all_text.lower()

        if any(w in lower for w in ["earnings", "revenue", "profit", "eps", "guidance"]):
            categories.append("earnings")
        if any(w in lower for w in ["insider", "purchase", "buy", "bought", "director"]):
            categories.append("insider_activity")
        if any(w in lower for w in ["analyst", "target", "upgrade", "downgrade", "rating"]):
            categories.append("analyst")
        if any(w in lower for w in ["short interest", "short squeeze", "options"]):
            categories.append("options_flow")
        if any(w in lower for w in ["dividend", "yield", "payout"]):
            categories.append("dividend")
        if any(w in lower for w in ["momentum", "breakout", "rally", "surge", "jump"]):
            categories.append("momentum")
        if any(w in lower for w in ["risk", "drop", "decline", "fall", "crash", "warning"]):
            categories.append("risk")
        if any(w in lower for w in ["watch", "spotlight", "focus", "track"]):
            categories.append("watchlist")

        if not categories:
            categories.append("general_mention")

        return {
            "sentiment_compound": round(sentiment["compound"], 3),
            "sentiment_pos": round(sentiment["pos"], 3),
            "sentiment_neg": round(sentiment["neg"], 3),
            "categories": categories,
            "mention_count": len(contexts),
        }

    def scan_all(self) -> dict[str, list[dict]]:
        """Scan all recent SA emails and return ticker intelligence.

        Returns:
            Dict mapping ticker -> list of mention records, each with:
              - source_file, subject, date, sentiment, categories, contexts
        """
        # Cache for 30 minutes to avoid re-scanning on every ticker
        if (
            self._cache is not None
            and self._cache_time
            and (datetime.now() - self._cache_time).seconds < 1800
        ):
            return self._cache

        results: dict[str, list[dict]] = {}
        sa_files = self._find_sa_files()

        for fpath in sa_files:
            try:
                front = self._read_frontmatter(fpath)
                body = self._read_file_body(fpath)
                ticker_contexts = self._extract_ticker_mentions(body)

                subject = front.get("subject", os.path.basename(fpath)) if front else os.path.basename(fpath)
                date = str(front.get("date", "")) if front else ""

                for ticker, contexts in ticker_contexts.items():
                    classification = self._classify_mention(contexts)
                    record = {
                        "source": "seeking_alpha_email",
                        "source_file": os.path.basename(fpath),
                        "subject": subject,
                        "date": date,
                        "contexts": contexts[:3],  # keep top 3 context snippets
                        **classification,
                    }
                    if ticker not in results:
                        results[ticker] = []
                    results[ticker].append(record)

            except Exception as e:
                logger.error(f"Error processing SA email {fpath}: {e}")

        total_tickers = len(results)
        total_mentions = sum(len(v) for v in results.values())
        logger.info(f"Seeking Alpha scan: {total_tickers} tickers, {total_mentions} mentions from {len(sa_files)} emails")

        self._cache = results
        self._cache_time = datetime.now()
        return results

    def get_ticker_intel(self, ticker: str) -> dict:
        """Get Seeking Alpha intelligence for a specific ticker.

        Returns a summary dict with:
          - mentioned: bool
          - mention_count: total mentions across all emails
          - avg_sentiment: average compound sentiment
          - categories: all categories seen
          - contexts: top context snippets
          - emails: list of email subjects mentioning this ticker
        """
        all_data = self.scan_all()
        mentions = all_data.get(ticker.upper(), [])

        if not mentions:
            return {
                "ticker": ticker,
                "mentioned": False,
                "mention_count": 0,
                "avg_sentiment": 0.0,
                "categories": [],
                "contexts": [],
                "emails": [],
            }

        sentiments = [m["sentiment_compound"] for m in mentions]
        avg_sentiment = round(sum(sentiments) / len(sentiments), 3)

        all_categories = set()
        all_contexts = []
        emails = []
        for m in mentions:
            all_categories.update(m["categories"])
            all_contexts.extend(m["contexts"])
            emails.append({"subject": m["subject"], "date": m["date"]})

        return {
            "ticker": ticker,
            "mentioned": True,
            "mention_count": sum(m["mention_count"] for m in mentions),
            "avg_sentiment": avg_sentiment,
            "categories": sorted(all_categories),
            "contexts": all_contexts[:5],  # top 5 snippets
            "emails": emails,
        }

    def get_mentioned_tickers(self) -> list[str]:
        """Return all tickers mentioned in recent SA emails."""
        all_data = self.scan_all()
        return sorted(all_data.keys())

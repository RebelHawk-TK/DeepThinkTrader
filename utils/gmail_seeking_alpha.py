"""Gmail Seeking Alpha Reader — Fetches SA emails via Sabrina API and extracts ticker intelligence.

Replaces the vault-based ObsidianSeekingAlpha with direct Gmail access.
Searches for emails with a specific label (default: "SA") in a specific account
(default: tom@brigitteandtom.com).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import requests as http_requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import Config

logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"\(([A-Z]{1,5})(?:\s|\))")
_SKIP_WORDS = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
    "WAS", "ONE", "OUR", "OUT", "DAY", "HAD", "HAS", "HIS", "HOW", "ITS",
    "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "HIM",
    "LET", "SAY", "SHE", "TOO", "USE", "CEO", "CFO", "IPO", "GDP", "PMI",
    "ETF", "SEC", "FED", "AI", "US", "UK", "EU", "Q1", "Q2", "Q3", "Q4",
    "AM", "PM", "VS", "COM", "EST", "PST", "LLC", "INC", "NYSE", "NASDAQ",
}


class GmailSeekingAlpha:
    """Fetches Seeking Alpha emails from Gmail via Sabrina API."""

    def __init__(self):
        self.config = Config()
        self.vader = SentimentIntensityAnalyzer()
        self._cache: dict[str, list[dict]] | None = None
        self._cache_time: datetime | None = None
        self._api_url = self.config.SABRINA_API_URL.rstrip("/")
        self._api_key = self.config.SABRINA_API_KEY
        self._account = self.config.SA_EMAIL_ACCOUNT
        self._label = self.config.SA_GMAIL_LABEL
        self._max_age_days = self.config.OBSIDIAN_SA_MAX_AGE_DAYS

    def _search_emails(self) -> list[dict]:
        """Search Gmail for SA-labeled emails via Sabrina API."""
        after_date = (datetime.now() - timedelta(days=self._max_age_days)).strftime("%Y/%m/%d")
        query = f"label:{self._label} after:{after_date}"

        try:
            resp = http_requests.post(
                f"{self._api_url}/api/gmail/search",
                json={
                    "query": query,
                    "account_email": self._account,
                    "max_results": 50,
                    "include_body": True,
                    "body_max_chars": 5000,
                },
                headers={"X-API-Key": self._api_key},
                timeout=30,
            )
            if resp.ok:
                data = resp.json()
                messages = data.get("messages", data.get("results", []))
                logger.info(f"Gmail SA search: {len(messages)} emails with label:{self._label} (last {self._max_age_days}d)")
                return messages
            else:
                logger.error(f"Gmail SA search failed: HTTP {resp.status_code}")
                return []
        except Exception as e:
            logger.error(f"Gmail SA search error: {e}")
            return []

    def _get_message_body(self, message_id: str) -> str:
        """Fetch full message body if not included in search results."""
        try:
            resp = http_requests.get(
                f"{self._api_url}/api/gmail/message/{message_id}",
                params={"account_email": self._account},
                headers={"X-API-Key": self._api_key},
                timeout=15,
            )
            if resp.ok:
                data = resp.json()
                return data.get("body", data.get("body_preview", ""))
            return ""
        except Exception as e:
            logger.debug(f"Failed to fetch message {message_id}: {e}")
            return ""

    def _extract_ticker_mentions(self, body: str) -> dict[str, list[str]]:
        """Extract tickers and their surrounding context sentences."""
        clean = re.sub(r"https?://\S+", "", body)
        clean = re.sub(r"\s+", " ", clean)

        ticker_contexts: dict[str, list[str]] = {}

        for match in _TICKER_RE.finditer(clean):
            ticker = match.group(1)
            if ticker in _SKIP_WORDS or len(ticker) < 2:
                continue
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
        """Scan SA-labeled Gmail messages and return ticker intelligence."""
        # Cache for 30 minutes
        if (
            self._cache is not None
            and self._cache_time
            and (datetime.now() - self._cache_time).seconds < 1800
        ):
            return self._cache

        results: dict[str, list[dict]] = {}
        messages = self._search_emails()

        for msg in messages:
            try:
                msg_id = msg.get("id", msg.get("message_id", ""))
                subject = msg.get("subject", "")
                date = msg.get("date", msg.get("received", ""))
                body = msg.get("body_preview", msg.get("body", ""))

                # If body is too short, fetch the full message
                if len(body) < 200 and msg_id:
                    body = self._get_message_body(msg_id)

                if not body:
                    continue

                ticker_contexts = self._extract_ticker_mentions(body)

                for ticker, contexts in ticker_contexts.items():
                    classification = self._classify_mention(contexts)
                    record = {
                        "source": "gmail_seeking_alpha",
                        "source_id": msg_id,
                        "subject": subject,
                        "date": date,
                        "contexts": contexts[:3],
                        **classification,
                    }
                    if ticker not in results:
                        results[ticker] = []
                    results[ticker].append(record)

            except Exception as e:
                logger.error(f"Error processing SA email: {e}")

        total_tickers = len(results)
        total_mentions = sum(len(v) for v in results.values())
        logger.info(
            f"Gmail SA scan: {total_tickers} tickers, {total_mentions} mentions "
            f"from {len(messages)} emails (label:{self._label}, account:{self._account})"
        )

        self._cache = results
        self._cache_time = datetime.now()
        return results

    def get_ticker_intel(self, ticker: str) -> dict:
        """Get Seeking Alpha intelligence for a specific ticker."""
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
            "contexts": all_contexts[:5],
            "emails": emails,
        }

    def get_mentioned_tickers(self) -> list[str]:
        """Return all tickers mentioned in recent SA emails."""
        all_data = self.scan_all()
        return sorted(all_data.keys())

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Alpaca
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # NewsAPI
    NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")

    # Reddit
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "DeepThinkTrader/1.0")

    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # RapidAPI
    RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")

    # Trading parameters
    ACCOUNT_SIZE: float = float(os.getenv("ACCOUNT_SIZE", "50000"))
    WATCHLIST: list[str] = os.getenv("WATCHLIST", "NVDA,TSLA,AAPL,AMD,SPY").split(",")
    MAX_RISK_PER_TRADE: float = float(os.getenv("MAX_RISK_PER_TRADE", "0.02"))
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "0.05"))
    MIN_CONVICTION: float = float(os.getenv("MIN_CONVICTION", "8"))
    RESEARCH_INTERVAL_MINUTES: int = int(os.getenv("RESEARCH_INTERVAL_MINUTES", "60"))
    MIN_REWARD_RISK_RATIO: float = float(os.getenv("MIN_REWARD_RISK_RATIO", "2.0"))

    # Database
    DB_PATH: str = os.path.join(os.path.dirname(__file__), "trades.db")

    # Subreddits to scan
    SUBREDDITS: list[str] = ["wallstreetbets", "stocks", "investing"]

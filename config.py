from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# Load secrets from Keychain (preferred) with .env fallback
_secrets: dict = {}
try:
    from keychain_config import load_secrets
    _secrets = load_secrets() or {}
except Exception:
    pass


def _secret(keychain_key: str, env_var: str, default: str = "") -> str:
    """Read secret from Keychain first, then .env, then default."""
    return _secrets.get(keychain_key, "") or os.getenv(env_var, default)


# ── Trade Mode Presets ──────────────────────────────────────────
# Each mode defines: risk per trade, daily loss limit, min conviction,
# min R:R ratio, max position % of account, max open positions, scanner top N

TRADE_MODES = {
    "safe": {
        "MAX_RISK_PER_TRADE": 0.01,       # 1% risk per trade
        "MAX_DAILY_LOSS": 0.03,            # 3% daily loss limit
        "MIN_CONVICTION": 9.0,             # Only highest-conviction trades
        "MIN_REWARD_RISK_RATIO": 3.0,      # Need 3:1 reward:risk
        "MAX_POSITION_PCT": 0.05,          # 5% of account per position
        "MAX_OPEN_POSITIONS": 5,           # Max 5 positions (25% max exposure)
        "SCANNER_TOP_N": 10,               # Fewer, higher-quality candidates
    },
    "normal": {
        "MAX_RISK_PER_TRADE": 0.02,        # 2% risk per trade
        "MAX_DAILY_LOSS": 0.05,            # 5% daily loss limit
        "MIN_CONVICTION": 7.5,             # Moderate conviction threshold
        "MIN_REWARD_RISK_RATIO": 2.0,      # 2:1 reward:risk
        "MAX_POSITION_PCT": 0.10,          # 10% of account per position
        "MAX_OPEN_POSITIONS": 10,          # Max 10 positions
        "SCANNER_TOP_N": 20,               # Standard scan depth
    },
    "aggressive": {
        "MAX_RISK_PER_TRADE": 0.03,        # 3% risk per trade
        "MAX_DAILY_LOSS": 0.08,            # 8% daily loss limit
        "MIN_CONVICTION": 6.0,             # Lower bar — more trades
        "MIN_REWARD_RISK_RATIO": 1.5,      # 1.5:1 reward:risk
        "MAX_POSITION_PCT": 0.15,          # 15% of account per position
        "MAX_OPEN_POSITIONS": 15,          # Max 15 positions
        "SCANNER_TOP_N": 30,               # Cast wider net
    },
}


class Config:
    # Trade mode: safe, normal, aggressive (set via TRADE_MODE env var or .env)
    TRADE_MODE: str = os.getenv("TRADE_MODE", "normal").lower()

    # Load mode preset, fall back to normal if invalid
    _mode = TRADE_MODES.get(TRADE_MODE, TRADE_MODES["normal"])

    # Alpaca
    ALPACA_API_KEY: str = _secret("alpaca_api_key", "ALPACA_API_KEY")
    ALPACA_SECRET_KEY: str = _secret("alpaca_secret_key", "ALPACA_SECRET_KEY")
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # NewsAPI
    NEWSAPI_KEY: str = _secret("newsapi_key", "NEWSAPI_KEY")

    # Reddit
    REDDIT_CLIENT_ID: str = _secret("reddit_client_id", "REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str = _secret("reddit_client_secret", "REDDIT_CLIENT_SECRET")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "DeepThinkTrader/1.0")

    # Anthropic
    ANTHROPIC_API_KEY: str = _secret("anthropic_api_key", "ANTHROPIC_API_KEY")

    # RapidAPI
    RAPIDAPI_KEY: str = _secret("rapidapi_key", "RAPIDAPI_KEY")

    # Trading parameters (mode-driven, with env var override)
    ACCOUNT_SIZE: float = float(os.getenv("ACCOUNT_SIZE", "50000"))
    WATCHLIST: list[str] = os.getenv("WATCHLIST", "NVDA,TSLA,AAPL,AMD,SPY").split(",")
    MAX_RISK_PER_TRADE: float = float(os.getenv(
        "MAX_RISK_PER_TRADE", str(_mode["MAX_RISK_PER_TRADE"])))
    MAX_DAILY_LOSS: float = float(os.getenv(
        "MAX_DAILY_LOSS", str(_mode["MAX_DAILY_LOSS"])))
    MIN_CONVICTION: float = float(os.getenv(
        "MIN_CONVICTION", str(_mode["MIN_CONVICTION"])))
    RESEARCH_INTERVAL_MINUTES: int = int(os.getenv("RESEARCH_INTERVAL_MINUTES", "60"))
    MIN_REWARD_RISK_RATIO: float = float(os.getenv(
        "MIN_REWARD_RISK_RATIO", str(_mode["MIN_REWARD_RISK_RATIO"])))
    MAX_POSITION_PCT: float = float(os.getenv(
        "MAX_POSITION_PCT", str(_mode["MAX_POSITION_PCT"])))
    MAX_OPEN_POSITIONS: int = int(os.getenv(
        "MAX_OPEN_POSITIONS", str(_mode["MAX_OPEN_POSITIONS"])))

    # Scanner
    SCANNER_TOP_N: int = int(os.getenv(
        "SCANNER_TOP_N", str(_mode["SCANNER_TOP_N"])))
    SCANNER_MIN_REL_STRENGTH: float = float(os.getenv("SCANNER_MIN_REL_STRENGTH", "-5.0"))

    # Database
    DB_PATH: str = os.path.join(os.path.dirname(__file__), "trades.db")

    # Subreddits to scan
    SUBREDDITS: list[str] = ["wallstreetbets", "stocks", "investing"]

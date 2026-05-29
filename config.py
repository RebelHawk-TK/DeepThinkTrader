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

    # Penny stock portfolio: enabled by default, runs alongside main portfolio
    PENNY_ENABLED: bool = os.getenv("PENNY_ENABLED", "true").lower() == "true"

    # Load mode preset, fall back to normal if invalid
    _mode = TRADE_MODES.get(TRADE_MODE, TRADE_MODES["normal"])

    # Alpaca — credentials are per-user (stored encrypted in user_secrets).
    # ALPACA_API_KEY / ALPACA_SECRET_KEY moved out of Config entirely; the bot
    # loads each user's keys via utils.secrets_vault.get_alpaca_keys(user_id).
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # NewsAPI
    NEWSAPI_KEY: str = _secret("newsapi_key", "NEWSAPI_KEY")

    # Reddit
    REDDIT_CLIENT_ID: str = _secret("reddit_client_id", "REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str = _secret("reddit_client_secret", "REDDIT_CLIENT_SECRET")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "DeepThinkTrader/1.0")

    # Anthropic (Claude AI analysis layer)
    ANTHROPIC_API_KEY: str = _secret("anthropic_api_key", "ANTHROPIC_API_KEY")
    CLAUDE_ANALYSIS_ENABLED: bool = os.getenv("CLAUDE_ANALYSIS_ENABLED", "true").lower() == "true"
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Bull/Bear debate
    DEBATE_ENABLED: bool = os.getenv("DEBATE_ENABLED", "true").lower() == "true"
    DEBATE_ROUNDS: int = int(os.getenv("DEBATE_ROUNDS", "2"))

    # RapidAPI
    RAPIDAPI_KEY: str = _secret("rapidapi_key", "RAPIDAPI_KEY")

    # ── Additional News APIs ─────────────────────────────────────
    STOCK_NEWS_API_ENABLED: bool = os.getenv("STOCK_NEWS_API_ENABLED", "true").lower() == "true"
    STOCK_NEWS_API_KEY: str = _secret("stocknewsapi_key", "STOCK_NEWS_API_KEY")
    TICKER_TICK_ENABLED: bool = os.getenv("TICKER_TICK_ENABLED", "true").lower() == "true"
    FMP_ENABLED: bool = os.getenv("FMP_ENABLED", "false").lower() == "true"  # free tier no longer includes news
    FMP_API_KEY: str = _secret("fmp_api_key", "FMP_API_KEY")
    MARKETAUX_ENABLED: bool = os.getenv("MARKETAUX_ENABLED", "false").lower() == "true"  # 401 — email never verified
    MARKETAUX_API_KEY: str = _secret("marketaux_api_key", "MARKETAUX_API_KEY")
    ALPHA_VANTAGE_ENABLED: bool = os.getenv("ALPHA_VANTAGE_ENABLED", "true").lower() == "true"
    ALPHA_VANTAGE_API_KEY: str = _secret("alphavantage_api_key", "ALPHA_VANTAGE_API_KEY")
    NEWS_CACHE_TTL_MINUTES: int = int(os.getenv("NEWS_CACHE_TTL_MINUTES", "30"))

    @classmethod
    def get_news_config(cls) -> dict:
        """Return dict of news-related config for NewsAggregator initialization."""
        return {
            "STOCK_NEWS_API_ENABLED": cls.STOCK_NEWS_API_ENABLED,
            "STOCK_NEWS_API_KEY": cls.STOCK_NEWS_API_KEY,
            "TICKER_TICK_ENABLED": cls.TICKER_TICK_ENABLED,
            "FMP_ENABLED": cls.FMP_ENABLED,
            "FMP_API_KEY": cls.FMP_API_KEY,
            "MARKETAUX_ENABLED": cls.MARKETAUX_ENABLED,
            "MARKETAUX_API_KEY": cls.MARKETAUX_API_KEY,
            "ALPHA_VANTAGE_ENABLED": cls.ALPHA_VANTAGE_ENABLED,
            "ALPHA_VANTAGE_API_KEY": cls.ALPHA_VANTAGE_API_KEY,
            "NEWS_CACHE_TTL_MINUTES": cls.NEWS_CACHE_TTL_MINUTES,
        }

    # Trading parameters (mode-driven, with env var override)
    ACCOUNT_SIZE: float = float(os.getenv("ACCOUNT_SIZE", "50000"))
    WATCHLIST: list[str] = os.getenv("WATCHLIST", "NVDA,TSLA,AAPL,AMD,SPY").split(",")
    MAX_RISK_PER_TRADE: float = float(os.getenv(
        "MAX_RISK_PER_TRADE", str(_mode["MAX_RISK_PER_TRADE"])))
    MAX_DAILY_LOSS: float = float(os.getenv(
        "MAX_DAILY_LOSS", str(_mode["MAX_DAILY_LOSS"])))
    MIN_CONVICTION: float = float(os.getenv(
        "MIN_CONVICTION", str(_mode["MIN_CONVICTION"])))
    RESEARCH_INTERVAL_MINUTES: int = int(os.getenv("RESEARCH_INTERVAL_MINUTES", "30"))
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
    SCANNER_MIN_RVOL: float = float(os.getenv("SCANNER_MIN_RVOL", "1.5"))
    SCANNER_MIN_SOURCES: int = int(os.getenv("SCANNER_MIN_SOURCES", "1"))

    # ── Penny Stock Portfolio Parameters ──────────────────────────
    PENNY_MAX_RISK_PER_TRADE: float = float(os.getenv("PENNY_MAX_RISK_PER_TRADE", "0.03"))
    PENNY_MAX_DAILY_LOSS: float = float(os.getenv("PENNY_MAX_DAILY_LOSS", "0.08"))
    PENNY_MIN_CONVICTION: float = float(os.getenv("PENNY_MIN_CONVICTION", "6.0"))
    PENNY_MIN_REWARD_RISK_RATIO: float = float(os.getenv("PENNY_MIN_REWARD_RISK_RATIO", "1.5"))
    PENNY_MAX_POSITION_PCT: float = float(os.getenv("PENNY_MAX_POSITION_PCT", "0.02"))
    PENNY_MAX_OPEN_POSITIONS: int = int(os.getenv("PENNY_MAX_OPEN_POSITIONS", "5"))
    PENNY_SCANNER_TOP_N: int = int(os.getenv("PENNY_SCANNER_TOP_N", "15"))
    PENNY_MIN_PRICE: float = float(os.getenv("PENNY_MIN_PRICE", "1.0"))
    PENNY_MAX_PRICE: float = float(os.getenv("PENNY_MAX_PRICE", "5.0"))
    PENNY_MIN_AVG_VOLUME: int = int(os.getenv("PENNY_MIN_AVG_VOLUME", "100000"))
    PENNY_SUBREDDITS: list[str] = ["pennystocks", "wallstreetbets", "stocks"]

    # ── Phase 1: Risk-First Gate ──────────────────────────────────
    RISK_PCT_PER_TRADE: float = float(os.getenv("RISK_PCT_PER_TRADE", "0.01"))
    MAX_DRAWDOWN_HALT_PCT: float = float(os.getenv("MAX_DRAWDOWN_HALT_PCT", "0.08"))
    VOLATILITY_ATR_MULTIPLIER: float = float(os.getenv("VOLATILITY_ATR_MULTIPLIER", "3.0"))
    MIN_ADV_RATIO: int = int(os.getenv("MIN_ADV_RATIO", "5"))
    KELLY_SAFETY_MULTIPLIER: float = float(os.getenv("KELLY_SAFETY_MULTIPLIER", "0.5"))
    MAX_RISK_OF_RUIN_PCT: float = float(os.getenv("MAX_RISK_OF_RUIN_PCT", "0.01"))
    # Safety gates re-enabled 2026-05-29 (P0). Default ON. Set to "false" to
    # restore the prior bypass that allowed trades during a losing streak.
    RISK_OF_RUIN_ENABLED: bool = os.getenv("RISK_OF_RUIN_ENABLED", "true").lower() == "true"
    REVENGE_GUARD_ENABLED: bool = os.getenv("REVENGE_GUARD_ENABLED", "true").lower() == "true"

    # ── Phase 2: Exit Improvements ────────────────────────────────
    EXIT_CHECK_INTERVAL_MINUTES: int = int(os.getenv("EXIT_CHECK_INTERVAL_MINUTES", "5"))
    TRAILING_STOP_ACTIVATION_PCT: float = float(os.getenv("TRAILING_STOP_ACTIVATION_PCT", "2.0"))
    TRAILING_STOP_DISTANCE_PCT: float = float(os.getenv("TRAILING_STOP_DISTANCE_PCT", "1.5"))
    PENNY_TRAILING_STOP_DISTANCE_PCT: float = float(os.getenv("PENNY_TRAILING_STOP_DISTANCE_PCT", "3.0"))
    SCALE_OUT_ENABLED: bool = os.getenv("SCALE_OUT_ENABLED", "true").lower() == "true"
    SCALE_OUT_LEVELS: list[float] = [float(x) for x in os.getenv("SCALE_OUT_LEVELS", "1.0,2.0").split(",")]
    TIME_STOP_DAYS: int = int(os.getenv("TIME_STOP_DAYS", "15"))

    # ── Phase 3: Edge Validation ──────────────────────────────────
    MIN_EDGES_REQUIRED: int = int(os.getenv("MIN_EDGES_REQUIRED", "2"))
    # P1 (2026-05-29 edge recalibration): require the fundamental edge on long
    # entries. Backtest of real entries: fundamental-backed combos were
    # profitable (PF 1.87); technical-without-fundamental was toxic (T+S: 11%
    # win, PF 0.10). Default on. Set REQUIRE_FUNDAMENTAL_EDGE=false to revert.
    REQUIRE_FUNDAMENTAL_EDGE: bool = os.getenv("REQUIRE_FUNDAMENTAL_EDGE", "true").lower() == "true"

    # ── Warmup: analyze N unique tickers before first trade ─────
    WARMUP_MIN_TICKERS: int = int(os.getenv("WARMUP_MIN_TICKERS", "100"))

    # ── Phase 4: Smart Orders ─────────────────────────────────────
    PENNY_LIMIT_SLIPPAGE_PCT: float = float(os.getenv("PENNY_LIMIT_SLIPPAGE_PCT", "0.5"))
    MAX_SLIPPAGE_PCT: float = float(os.getenv("MAX_SLIPPAGE_PCT", "0.3"))

    # ── Phase 5: Market Awareness + Learning ──────────────────────
    CIRCUIT_BREAKER_SPY_DROP_PCT: float = float(os.getenv("CIRCUIT_BREAKER_SPY_DROP_PCT", "-2.0"))
    CIRCUIT_BREAKER_VIX_THRESHOLD: float = float(os.getenv("CIRCUIT_BREAKER_VIX_THRESHOLD", "30.0"))

    # ── Phase 6: Execution Quality ──────────────────────────────
    MAX_SPREAD_PCT: float = float(os.getenv("MAX_SPREAD_PCT", "1.0"))
    PENNY_MAX_SPREAD_PCT: float = float(os.getenv("PENNY_MAX_SPREAD_PCT", "2.0"))
    MAX_SECTOR_EXPOSURE_PCT: float = float(os.getenv("MAX_SECTOR_EXPOSURE_PCT", "0.25"))
    GAP_RISK_ATR_THRESHOLD: float = float(os.getenv("GAP_RISK_ATR_THRESHOLD", "5.0"))
    GAP_RISK_POSITION_REDUCTION: float = float(os.getenv("GAP_RISK_POSITION_REDUCTION", "0.5"))
    EARNINGS_EXIT_DAYS: int = int(os.getenv("EARNINGS_EXIT_DAYS", "2"))
    EARNINGS_EXIT_MODE: str = os.getenv("EARNINGS_EXIT_MODE", "close")

    # Obsidian Vault (Seeking Alpha emails — legacy, replaced by Gmail mode)
    OBSIDIAN_VAULT_PATH: str = os.getenv(
        "OBSIDIAN_VAULT_PATH",
        os.path.expanduser("~/Documents/TKSabrinaIncVault"),
    )
    OBSIDIAN_SA_MAX_AGE_DAYS: int = int(os.getenv("OBSIDIAN_SA_MAX_AGE_DAYS", "7"))

    # ── Seeking Alpha via Gmail ───────────────────────────────────
    SA_EMAIL_ACCOUNT: str = os.getenv("SA_EMAIL_ACCOUNT", "tom@brigitteandtom.com")
    SA_GMAIL_LABEL: str = os.getenv("SA_GMAIL_LABEL", "SA")
    SA_SOURCE: str = os.getenv("SA_SOURCE", "gmail")  # "gmail" or "vault"
    SABRINA_API_URL: str = os.getenv("SABRINA_API_URL", "https://api.sabrinainc.ai")
    SABRINA_API_KEY: str = _secret("sabrina_api_key", "TOM_API_KEY")

    # Baseline date — dashboard ignores Alpaca portfolio history before this date
    BASELINE_DATE: str = os.getenv("BASELINE_DATE", "2026-03-24")

    # Database — env override for containers (DB_PATH=/data/trades.db)
    DB_PATH: str = os.getenv("DB_PATH") or os.path.join(os.path.dirname(__file__), "trades.db")

    # Subreddits to scan
    SUBREDDITS: list[str] = ["wallstreetbets", "stocks", "investing"]

    # ── Notifications ─────────────────────────────────────────────
    NOTIFICATIONS_ENABLED: bool = os.getenv("NOTIFICATIONS_ENABLED", "false").lower() == "true"
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

    # ── Weekend / Pre-market News Sweep ───────────────────────────
    # Rule-scored news polling at Sat 09:00, Sun 17:00, weekday 08:30 ET. No LLM.
    # Output: digest in WEEKEND_BRIEF_DIR (and copied to vault), JSON state for Mon hydration,
    # optional Slack notification on HIGH-tier alerts via existing webhook.
    WEEKEND_SWEEP_ENABLED: bool = os.getenv("WEEKEND_SWEEP_ENABLED", "true").lower() == "true"
    WEEKEND_BRIEF_DIR: str = os.getenv(
        "WEEKEND_BRIEF_DIR",
        os.path.join(os.path.dirname(__file__), "digests"),
    )
    WEEKEND_VAULT_BRIEF_DIR: str = os.getenv(
        "WEEKEND_VAULT_BRIEF_DIR",
        os.path.expanduser("~/Documents/TKSabrinaIncVault/02-Projects/StockTrader/digests"),
    )
    WEEKEND_HIGH_ALERT_THRESHOLD: float = float(os.getenv("WEEKEND_HIGH_ALERT_THRESHOLD", "7.0"))
    WEEKEND_HIGH_ALERT_MIN_SOURCES: int = int(os.getenv("WEEKEND_HIGH_ALERT_MIN_SOURCES", "3"))
    WEEKEND_SLACK_DM: bool = os.getenv("WEEKEND_SLACK_DM", "true").lower() == "true"

    # ── Rate Limiting ─────────────────────────────────────────────
    NEWSAPI_DAILY_LIMIT: int = int(os.getenv("NEWSAPI_DAILY_LIMIT", "100"))

    @classmethod
    def validate(cls) -> tuple[list[str], list[str]]:
        """Validate configuration. Returns (fatal_errors, warnings)."""
        errors: list[str] = []
        warnings: list[str] = []

        # Alpaca creds are per-user (user_secrets table); nothing global to
        # validate here. The orchestrator checks for "any active user with
        # keys" and sleeps the cycle if none exist.
        if not cls.NEWSAPI_KEY:
            warnings.append("NEWSAPI_KEY not set — news research will fail")

        # Trade mode
        if cls.TRADE_MODE not in TRADE_MODES:
            errors.append(f"TRADE_MODE '{cls.TRADE_MODE}' invalid — must be one of: {', '.join(TRADE_MODES)}")

        # Paper trading safety
        if "paper" not in cls.ALPACA_BASE_URL.lower():
            warnings.append(
                f"ALPACA_BASE_URL does not contain 'paper' ({cls.ALPACA_BASE_URL}) "
                "— are you sure you want LIVE trading?"
            )

        # Numeric ranges
        range_checks = [
            ("MAX_RISK_PER_TRADE", cls.MAX_RISK_PER_TRADE, 0, 1.0),
            ("MAX_DAILY_LOSS", cls.MAX_DAILY_LOSS, 0, 1.0),
            ("MIN_CONVICTION", cls.MIN_CONVICTION, 0, 10),
            ("MIN_REWARD_RISK_RATIO", cls.MIN_REWARD_RISK_RATIO, 0, 100),
            ("MAX_POSITION_PCT", cls.MAX_POSITION_PCT, 0, 1.0),
            ("MAX_DRAWDOWN_HALT_PCT", cls.MAX_DRAWDOWN_HALT_PCT, 0, 1.0),
            ("KELLY_SAFETY_MULTIPLIER", cls.KELLY_SAFETY_MULTIPLIER, 0, 1.0),
            ("MAX_RISK_OF_RUIN_PCT", cls.MAX_RISK_OF_RUIN_PCT, 0, 1.0),
            ("MIN_EDGES_REQUIRED", cls.MIN_EDGES_REQUIRED, 1, 3),
            ("MAX_SECTOR_EXPOSURE_PCT", cls.MAX_SECTOR_EXPOSURE_PCT, 0, 1.0),
        ]
        for name, value, low, high in range_checks:
            if not (low <= value <= high):
                errors.append(f"{name}={value} out of range [{low}, {high}]")

        # Positive integers
        if cls.MAX_OPEN_POSITIONS < 1:
            errors.append(f"MAX_OPEN_POSITIONS must be >= 1 (got {cls.MAX_OPEN_POSITIONS})")
        if cls.RESEARCH_INTERVAL_MINUTES < 1:
            errors.append(f"RESEARCH_INTERVAL_MINUTES must be >= 1 (got {cls.RESEARCH_INTERVAL_MINUTES})")
        if cls.EXIT_CHECK_INTERVAL_MINUTES < 1:
            errors.append(f"EXIT_CHECK_INTERVAL_MINUTES must be >= 1 (got {cls.EXIT_CHECK_INTERVAL_MINUTES})")

        # Optional warnings
        if cls.NOTIFICATIONS_ENABLED and not cls.SLACK_WEBHOOK_URL:
            warnings.append("NOTIFICATIONS_ENABLED=true but SLACK_WEBHOOK_URL is empty")

        return errors, warnings


# Phase 2.1: Override the 11 tunable attrs from utils.tunable_params at import
# time. Values in tunable_params.json win over env-var defaults. Picked up on
# next restart — live reload is Phase 3 work.
_TUNABLE_OVERRIDES = (
    ("KELLY_SAFETY_MULTIPLIER", "kelly_safety_multiplier"),
    ("MAX_RISK_PER_TRADE", "max_risk_per_trade"),
    ("MAX_DAILY_LOSS", "max_daily_loss"),
    ("MIN_CONVICTION", "min_conviction"),
    ("MIN_REWARD_RISK_RATIO", "min_reward_risk_ratio"),
    ("MAX_POSITION_PCT", "max_position_pct"),
    ("MAX_OPEN_POSITIONS", "max_open_positions"),
    ("MAX_SECTOR_EXPOSURE_PCT", "max_sector_exposure_pct"),
    ("MAX_DRAWDOWN_HALT_PCT", "max_drawdown_halt_pct"),
    ("TRAILING_STOP_ACTIVATION_PCT", "trailing_stop_activation_pct"),
    ("TRAILING_STOP_DISTANCE_PCT", "trailing_stop_distance_pct"),
)
try:
    from utils.tunable_params import get_tunable_params as _get_tp
    _tp_values = _get_tp().get_all()
    for _attr, _key in _TUNABLE_OVERRIDES:
        if _key in _tp_values:
            _v = _tp_values[_key]
            # MAX_OPEN_POSITIONS is int in the existing config; coerce.
            setattr(Config, _attr, int(_v) if _attr == "MAX_OPEN_POSITIONS" else float(_v))
except Exception:
    # If the registry isn't available (corrupt JSON, missing module), keep
    # the env-var defaults. Bot stays functional.
    pass

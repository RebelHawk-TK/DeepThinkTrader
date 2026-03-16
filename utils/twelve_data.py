"""Twelve Data API client via RapidAPI — advanced technical indicators.

Provides MACD, Bollinger Bands, EMA, Stochastic, ADX, and ATR
to supplement Alpaca's basic price/volume data.
"""

from __future__ import annotations

import logging
import time

import requests as http_requests

from config import Config

logger = logging.getLogger(__name__)

TWELVE_DATA_HOST = "twelve-data1.p.rapidapi.com"
TWELVE_DATA_URL = f"https://{TWELVE_DATA_HOST}"


class TwelveData:
    def __init__(self):
        self.config = Config()
        self._session = http_requests.Session()
        self._session.headers.update({
            "X-RapidAPI-Key": self.config.RAPIDAPI_KEY,
            "X-RapidAPI-Host": TWELVE_DATA_HOST,
        })

    def _get(self, endpoint: str, params: dict) -> dict | None:
        """Make a rate-limited GET request to Twelve Data API (max 8/min)."""
        # Skip all calls if we've detected subscription issue (403)
        if getattr(self, "_disabled", False):
            return None

        time.sleep(8)
        try:
            resp = self._session.get(
                f"{TWELVE_DATA_URL}/{endpoint}", params=params, timeout=10
            )
            if resp.status_code == 403:
                logger.warning(
                    "Twelve Data returned 403 — subscribe to the free plan on RapidAPI. "
                    "Disabling Twelve Data for this session."
                )
                self._disabled = True
                return None
            if resp.status_code == 429:
                logger.warning(f"Twelve Data rate limited on {endpoint}, waiting 60s...")
                time.sleep(60)
                resp = self._session.get(
                    f"{TWELVE_DATA_URL}/{endpoint}", params=params, timeout=10
                )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "error":
                logger.error(f"Twelve Data error: {data.get('message', 'unknown')}")
                return None
            return data
        except Exception as e:
            logger.error(f"Twelve Data {endpoint} error: {e}")
            return None

    def get_macd(self, ticker: str) -> dict | None:
        """MACD (12, 26, 9) — trend direction and momentum."""
        data = self._get("macd", {
            "symbol": ticker,
            "interval": "1day",
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "outputsize": 5,
        })
        if not data or "values" not in data:
            return None

        latest = data["values"][0]
        prev = data["values"][1] if len(data["values"]) > 1 else latest

        macd_val = float(latest.get("macd", 0))
        signal_val = float(latest.get("macd_signal", 0))
        hist_val = float(latest.get("macd_hist", 0))
        prev_hist = float(prev.get("macd_hist", 0))

        return {
            "macd": round(macd_val, 4),
            "signal": round(signal_val, 4),
            "histogram": round(hist_val, 4),
            "crossover": "bullish" if prev_hist < 0 and hist_val > 0
                        else "bearish" if prev_hist > 0 and hist_val < 0
                        else "none",
            "trend": "bullish" if macd_val > signal_val else "bearish",
        }

    def get_bbands(self, ticker: str) -> dict | None:
        """Bollinger Bands (20, 2) — volatility and overbought/oversold."""
        data = self._get("bbands", {
            "symbol": ticker,
            "interval": "1day",
            "time_period": 20,
            "sd": 2,
            "outputsize": 3,
        })
        if not data or "values" not in data:
            return None

        latest = data["values"][0]
        upper = float(latest.get("upper_band", 0))
        middle = float(latest.get("middle_band", 0))
        lower = float(latest.get("lower_band", 0))
        bandwidth = round((upper - lower) / middle * 100, 2) if middle > 0 else 0

        return {
            "upper": round(upper, 2),
            "middle": round(middle, 2),
            "lower": round(lower, 2),
            "bandwidth_pct": bandwidth,
        }

    def get_ema(self, ticker: str) -> dict | None:
        """EMA 9 and EMA 21 — short-term trend signals."""
        ema_9 = self._get("ema", {
            "symbol": ticker, "interval": "1day", "time_period": 9, "outputsize": 1,
        })
        ema_21 = self._get("ema", {
            "symbol": ticker, "interval": "1day", "time_period": 21, "outputsize": 1,
        })

        if not ema_9 or not ema_21:
            return None

        val_9 = float(ema_9["values"][0]["ema"])
        val_21 = float(ema_21["values"][0]["ema"])

        return {
            "ema_9": round(val_9, 2),
            "ema_21": round(val_21, 2),
            "crossover": "bullish" if val_9 > val_21 else "bearish",
        }

    def get_stoch(self, ticker: str) -> dict | None:
        """Stochastic Oscillator — overbought/oversold momentum."""
        data = self._get("stoch", {
            "symbol": ticker, "interval": "1day", "outputsize": 3,
        })
        if not data or "values" not in data:
            return None

        latest = data["values"][0]
        k = float(latest.get("slow_k", 50))
        d = float(latest.get("slow_d", 50))

        if k > 80:
            zone = "overbought"
        elif k < 20:
            zone = "oversold"
        else:
            zone = "neutral"

        return {
            "k": round(k, 1),
            "d": round(d, 1),
            "zone": zone,
            "crossover": "bullish" if k > d else "bearish",
        }

    def get_adx(self, ticker: str) -> dict | None:
        """ADX — trend strength (>25 = strong trend, <20 = weak/range-bound)."""
        data = self._get("adx", {
            "symbol": ticker, "interval": "1day", "time_period": 14, "outputsize": 1,
        })
        if not data or "values" not in data:
            return None

        adx_val = float(data["values"][0].get("adx", 0))

        if adx_val > 40:
            strength = "very_strong"
        elif adx_val > 25:
            strength = "strong"
        elif adx_val > 20:
            strength = "moderate"
        else:
            strength = "weak"

        return {
            "adx": round(adx_val, 1),
            "trend_strength": strength,
        }

    def get_atr(self, ticker: str) -> dict | None:
        """ATR (14) — average true range for volatility-based stop-loss sizing."""
        data = self._get("atr", {
            "symbol": ticker, "interval": "1day", "time_period": 14, "outputsize": 1,
        })
        if not data or "values" not in data:
            return None

        return {
            "atr": round(float(data["values"][0].get("atr", 0)), 2),
        }

    def get_full_technicals(self, ticker: str) -> dict:
        """Fetch all indicators for a ticker. Returns combined dict."""
        logger.info(f"Twelve Data: fetching advanced technicals for {ticker}")

        result = {"ticker": ticker, "source": "twelve_data"}

        macd = self.get_macd(ticker)
        if macd:
            result["macd"] = macd

        bbands = self.get_bbands(ticker)
        if bbands:
            result["bbands"] = bbands

        ema = self.get_ema(ticker)
        if ema:
            result["ema"] = ema

        stoch = self.get_stoch(ticker)
        if stoch:
            result["stoch"] = stoch

        adx = self.get_adx(ticker)
        if adx:
            result["adx"] = adx

        atr = self.get_atr(ticker)
        if atr:
            result["atr"] = atr

        indicators_found = len([k for k in result if k not in ("ticker", "source")])
        logger.info(f"Twelve Data: {indicators_found}/6 indicators loaded for {ticker}")

        return result

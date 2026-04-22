"""Alpaca Market Data client with X-Request-ID capture.

Uses both the alpaca-py SDK for convenient data access and raw HTTP
to persist X-Request-ID headers from every market data API call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import requests as http_requests
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame

from utils.database import Database

logger = logging.getLogger(__name__)

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"


class AlpacaMarketData:
    def __init__(self, api_key: str, secret_key: str, db: Database | None = None):
        """Market data client scoped to one Alpaca account.

        Market data is the same for every user, but each request authenticates
        with the caller's keys so rate limits apply per-account. Callers
        supply keys via ``secrets_vault.get_alpaca_keys(user_id)``.
        """
        self.db = db or Database()
        self.sdk_client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )
        # Raw HTTP session for X-Request-ID capture
        self._session = http_requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        })

    def _capture_request_id(
        self,
        response: http_requests.Response,
        endpoint: str,
        ticker: str | None = None,
    ) -> str | None:
        """Extract and persist X-Request-ID from market data response."""
        request_id = response.headers.get("X-Request-ID")
        if request_id:
            self.db.save_request_id(
                request_id=request_id,
                endpoint=endpoint,
                method="GET",
                ticker=ticker,
                http_status=response.status_code,
                success=response.ok,
            )
            logger.debug(
                f"Market Data X-Request-ID: {request_id} "
                f"(GET {endpoint} → {response.status_code})"
            )
        return request_id

    def get_bars(
        self,
        ticker: str,
        timeframe: str = "1Day",
        days: int = 30,
    ) -> pd.DataFrame:
        """Fetch historical bars via raw HTTP to capture X-Request-ID,
        then return as DataFrame."""
        end = datetime.now()
        start = end - timedelta(days=days)
        endpoint = f"/v2/stocks/{ticker}/bars"

        try:
            resp = self._session.get(
                f"{ALPACA_DATA_BASE_URL}{endpoint}",
                params={
                    "timeframe": timeframe,
                    "start": start.strftime("%Y-%m-%dT00:00:00Z"),
                    "end": end.strftime("%Y-%m-%dT00:00:00Z"),
                    "limit": 1000,
                    "adjustment": "raw",
                    "feed": "iex",
                },
            )
            self._capture_request_id(resp, endpoint, ticker)
            resp.raise_for_status()
            data = resp.json()

            bars = data.get("bars", [])
            if not bars:
                logger.warning(f"No bar data returned for {ticker}")
                return pd.DataFrame()

            df = pd.DataFrame(bars)
            df["t"] = pd.to_datetime(df["t"])
            df = df.rename(columns={
                "t": "timestamp",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "n": "trade_count",
                "vw": "vwap",
            })
            df = df.set_index("timestamp").sort_index()
            return df

        except Exception as e:
            logger.error(f"Alpaca bars error for {ticker}: {e}")
            return pd.DataFrame()

    def get_latest_bar(self, ticker: str) -> dict | None:
        """Fetch the latest bar for a ticker."""
        endpoint = f"/v2/stocks/{ticker}/bars/latest"
        try:
            resp = self._session.get(
                f"{ALPACA_DATA_BASE_URL}{endpoint}",
                params={"feed": "iex"},
            )
            self._capture_request_id(resp, endpoint, ticker)
            resp.raise_for_status()
            data = resp.json()
            bar = data.get("bar", {})
            return {
                "ticker": ticker,
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
                "vwap": bar.get("vw"),
                "timestamp": bar.get("t"),
            }
        except Exception as e:
            logger.error(f"Alpaca latest bar error for {ticker}: {e}")
            return None

    def get_snapshot(self, ticker: str) -> dict | None:
        """Fetch a full snapshot (latest trade, quote, bar, etc.)."""
        endpoint = f"/v2/stocks/{ticker}/snapshot"
        try:
            resp = self._session.get(
                f"{ALPACA_DATA_BASE_URL}{endpoint}",
                params={"feed": "iex"},
            )
            self._capture_request_id(resp, endpoint, ticker)
            resp.raise_for_status()
            data = resp.json()

            latest_bar = data.get("latestBar") or data.get("dailyBar", {})
            latest_trade = data.get("latestTrade", {})
            prev_bar = data.get("prevDailyBar", {})

            return {
                "ticker": ticker,
                "current_price": latest_trade.get("p", latest_bar.get("c", 0)),
                "today_open": latest_bar.get("o", 0),
                "today_high": latest_bar.get("h", 0),
                "today_low": latest_bar.get("l", 0),
                "today_close": latest_bar.get("c", 0),
                "today_volume": latest_bar.get("v", 0),
                "today_vwap": latest_bar.get("vw", 0),
                "prev_close": prev_bar.get("c", 0),
                "prev_volume": prev_bar.get("v", 0),
            }
        except Exception as e:
            logger.error(f"Alpaca snapshot error for {ticker}: {e}")
            return None

    def get_multi_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch snapshots for many symbols in a single API call.

        Returns dict mapping symbol -> snapshot data with normalized keys.
        """
        endpoint = "/v2/stocks/snapshots"
        all_results: dict[str, dict] = {}

        for i in range(0, len(symbols), 200):
            chunk = symbols[i:i + 200]
            try:
                resp = self._session.get(
                    f"{ALPACA_DATA_BASE_URL}{endpoint}",
                    params={"symbols": ",".join(chunk), "feed": "iex"},
                )
                self._capture_request_id(resp, endpoint)
                resp.raise_for_status()
                raw = resp.json()

                for sym, snap in raw.items():
                    daily = snap.get("dailyBar") or {}
                    prev = snap.get("prevDailyBar") or {}
                    trade = snap.get("latestTrade") or {}
                    minute = snap.get("minuteBar") or {}

                    price = trade.get("p") or minute.get("c") or daily.get("c", 0)
                    prev_close = prev.get("c", 0)

                    all_results[sym] = {
                        "price": price,
                        "prev_close": prev_close,
                        "daily_change_pct": round(
                            ((price - prev_close) / prev_close) * 100, 2
                        ) if prev_close > 0 else 0.0,
                        "volume": daily.get("v", 0),
                        "prev_volume": prev.get("v", 0),
                        "vwap": daily.get("vw", 0),
                    }

            except Exception as e:
                logger.error(f"Multi-snapshot error: {e}")

        logger.info(f"Batch snapshots: {len(all_results)} symbols loaded")
        return all_results

    def get_multi_bars(
        self,
        symbols: list[str],
        timeframe: str = "1Week",
        days: int = 90,
    ) -> dict[str, list[dict]]:
        """Fetch historical bars for many symbols in a single paginated API call.

        Returns dict mapping symbol -> list of bar dicts (oldest first).
        """
        endpoint = "/v2/stocks/bars"
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        all_bars: dict[str, list[dict]] = {}
        page_token = None

        while True:
            params: dict = {
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": start,
                "limit": 10000,
                "adjustment": "raw",
                "feed": "iex",
            }
            if page_token:
                params["page_token"] = page_token

            try:
                resp = self._session.get(
                    f"{ALPACA_DATA_BASE_URL}{endpoint}", params=params,
                )
                self._capture_request_id(resp, endpoint)
                resp.raise_for_status()
                data = resp.json()

                bars_by_sym = data.get("bars", {})
                for sym, bars in bars_by_sym.items():
                    all_bars.setdefault(sym, []).extend(bars)

                page_token = data.get("next_page_token")
                if not page_token:
                    break
            except Exception as e:
                logger.error(f"Multi-bars error: {e}")
                break

        logger.info(f"Batch bars ({timeframe}): {len(all_bars)} symbols loaded")
        return all_bars

    def get_technicals(self, ticker: str) -> dict:
        """Compute technical indicators from Alpaca historical bars.
        Drop-in replacement for yfinance-based technicals."""
        hist = self.get_bars(ticker, timeframe="1Day", days=30)
        snapshot = self.get_snapshot(ticker)

        if hist.empty or snapshot is None:
            return {"ticker": ticker, "error": "No data from Alpaca", "source": "alpaca"}

        current_price = snapshot["current_price"] or hist["close"].iloc[-1]
        prev_close = snapshot["prev_close"] or (
            hist["close"].iloc[-2] if len(hist) > 1 else current_price
        )

        # Simple moving averages
        sma_10 = round(hist["close"].tail(10).mean(), 2)
        sma_20 = round(hist["close"].tail(20).mean(), 2)

        # Volume analysis
        avg_volume = int(hist["volume"].mean())
        current_volume = int(snapshot["today_volume"]) if snapshot["today_volume"] else int(hist["volume"].iloc[-1])

        # RSI (14-day)
        delta = hist["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = round(rsi.iloc[-1], 1) if not rsi.empty and pd.notna(rsi.iloc[-1]) else 50.0

        return {
            "ticker": ticker,
            "source": "alpaca",
            "current_price": float(round(current_price, 2)),
            "previous_close": float(round(prev_close, 2)),
            "daily_change_pct": float(round(
                ((current_price - prev_close) / prev_close) * 100, 2
            )) if prev_close > 0 else 0.0,
            "current_volume": int(current_volume),
            "avg_volume": int(avg_volume),
            "volume_ratio": float(round(current_volume / avg_volume, 2)) if avg_volume > 0 else 0.0,
            "sma_10": float(sma_10),
            "sma_20": float(sma_20),
            "rsi_14": float(current_rsi),
            "above_sma_10": bool(current_price > sma_10),
            "above_sma_20": bool(current_price > sma_20),
            "today_vwap": float(round(snapshot.get("today_vwap", 0), 2)),
            "high_30d": float(round(hist["high"].max(), 2)),
            "low_30d": float(round(hist["low"].min(), 2)),
        }

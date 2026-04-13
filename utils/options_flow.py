"""Options flow monitor — detects unusual options activity via yfinance.

Scans option chains for volume spikes vs open interest, computes put/call
ratios, and tracks unusual premium to identify institutional positioning.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)


class OptionsFlowMonitor:
    def __init__(self, cache_ttl_minutes: int = 15):
        self._cache: dict[str, dict] = {}
        self._cache_ttl = timedelta(minutes=cache_ttl_minutes)

    def scan_unusual_activity(self, ticker: str) -> dict:
        """Scan options chain for unusual activity signals.

        Returns dict with:
            bullish_flow: bool — net bullish institutional signal
            put_call_ratio: float — total put vol / call vol (< 0.5 bullish, > 1.5 bearish)
            unusual_strikes: int — count of strikes with volume > 3x open interest
            total_unusual_premium: float — dollar value of unusual activity
            signal_strength: float — -1.0 (strong bearish) to 1.0 (strong bullish)
        """
        # Check cache
        cached = self._cache.get(ticker)
        if cached and cached["expires"] > datetime.utcnow():
            return cached["data"]

        # Run scan with timeout to prevent yfinance hangs
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._scan, ticker)
            try:
                result = future.result(timeout=30)
            except TimeoutError:
                logger.error(f"Options flow scan timed out for {ticker} after 30s")
                result = self._empty_result()
            except Exception as e:
                logger.error(f"Options flow scan failed for {ticker}: {e}")
                result = self._empty_result()

        self._cache[ticker] = {
            "data": result,
            "expires": datetime.utcnow() + self._cache_ttl,
        }
        return result

    @staticmethod
    def _empty_result() -> dict:
        return {
            "bullish_flow": False,
            "bearish_flow": False,
            "put_call_ratio": 1.0,
            "unusual_strikes": 0,
            "total_unusual_premium": 0.0,
            "signal_strength": 0.0,
            "call_volume": 0,
            "put_volume": 0,
            "unusual_calls": [],
            "unusual_puts": [],
        }

    def _scan(self, ticker: str) -> dict:
        empty = self._empty_result()

        try:
            stock = yf.Ticker(ticker)
            expirations = stock.options
            if not expirations:
                return empty

            # Scan nearest 2 expirations (most liquid, highest signal)
            dates_to_scan = expirations[:2]

            total_call_vol = 0
            total_put_vol = 0
            unusual_calls = []
            unusual_puts = []
            total_unusual_premium = 0.0

            for exp_date in dates_to_scan:
                try:
                    chain = stock.option_chain(exp_date)
                except Exception:
                    continue

                # Scan calls
                for _, row in chain.calls.iterrows():
                    import math
                    _vol = row.get("volume")
                    _oi = row.get("openInterest")
                    _last = row.get("lastPrice")
                    _strike = row.get("strike")
                    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in [_vol, _oi, _last, _strike]):
                        continue
                    vol = int(_vol)
                    oi = int(_oi)
                    last = float(_last)
                    strike = float(_strike)
                    total_call_vol += vol

                    if oi > 0 and vol > 3 * oi and vol > 100:
                        premium = vol * last * 100
                        total_unusual_premium += premium
                        unusual_calls.append({
                            "strike": strike,
                            "expiry": exp_date,
                            "volume": vol,
                            "oi": oi,
                            "ratio": round(vol / oi, 1),
                            "premium": round(premium),
                        })

                # Scan puts
                for _, row in chain.puts.iterrows():
                    _vol = row.get("volume")
                    _oi = row.get("openInterest")
                    _last = row.get("lastPrice")
                    _strike = row.get("strike")
                    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in [_vol, _oi, _last, _strike]):
                        continue
                    vol = int(_vol)
                    oi = int(_oi)
                    last = float(_last)
                    strike = float(_strike)
                    total_put_vol += vol

                    if oi > 0 and vol > 3 * oi and vol > 100:
                        premium = vol * last * 100
                        total_unusual_premium += premium
                        unusual_puts.append({
                            "strike": strike,
                            "expiry": exp_date,
                            "volume": vol,
                            "oi": oi,
                            "ratio": round(vol / oi, 1),
                            "premium": round(premium),
                        })

            # Compute put/call ratio
            pc_ratio = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

            unusual_count = len(unusual_calls) + len(unusual_puts)

            # Signal strength: -1.0 (bearish) to +1.0 (bullish)
            signal = 0.0

            # Put/call ratio signal
            if pc_ratio < 0.5:
                signal += 0.4  # Strong call bias
            elif pc_ratio < 0.7:
                signal += 0.2  # Mild call bias
            elif pc_ratio > 2.0:
                signal -= 0.4  # Strong put bias
            elif pc_ratio > 1.5:
                signal -= 0.2  # Mild put bias

            # Unusual activity signal
            if len(unusual_calls) > len(unusual_puts):
                signal += min(0.4, len(unusual_calls) * 0.08)
            elif len(unusual_puts) > len(unusual_calls):
                signal -= min(0.4, len(unusual_puts) * 0.08)

            # Premium magnitude amplifier
            if total_unusual_premium > 1_000_000:
                signal *= 1.3
            elif total_unusual_premium > 500_000:
                signal *= 1.15

            signal = max(-1.0, min(1.0, signal))

            bullish = signal > 0.15
            bearish = signal < -0.15

            if unusual_count > 0:
                logger.info(
                    f"Options flow {ticker}: P/C={pc_ratio:.2f}, "
                    f"unusual={unusual_count} ({len(unusual_calls)}C/{len(unusual_puts)}P), "
                    f"premium=${total_unusual_premium:,.0f}, signal={signal:+.2f}"
                )

            return {
                "bullish_flow": bullish,
                "bearish_flow": bearish,
                "put_call_ratio": round(pc_ratio, 3),
                "unusual_strikes": unusual_count,
                "total_unusual_premium": round(total_unusual_premium),
                "signal_strength": round(signal, 3),
                "call_volume": total_call_vol,
                "put_volume": total_put_vol,
                "unusual_calls": unusual_calls[:5],
                "unusual_puts": unusual_puts[:5],
            }

        except Exception as e:
            logger.error(f"Options flow error for {ticker}: {e}")
            return empty

"""Yahoo Finance fundamentals — earnings, analyst ratings, financials, insider activity.

All free via yfinance. No API key required.
"""

from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

logger = logging.getLogger(__name__)


class YahooFundamentals:
    def get_fundamentals(self, ticker: str) -> dict:
        """Fetch all available fundamental data for a ticker."""
        logger.info(f"Yahoo fundamentals: fetching data for {ticker}")
        result = {"ticker": ticker, "source": "yahoo_finance"}

        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}

            # Key financials
            result["financials"] = {
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "revenue": info.get("totalRevenue"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "return_on_equity": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "free_cash_flow": info.get("freeCashflow"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "50d_avg": info.get("fiftyDayAverage"),
                "200d_avg": info.get("twoHundredDayAverage"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }

            # Analyst recommendations
            result["analyst"] = self._get_analyst_data(stock, info)

            # Earnings dates
            result["earnings"] = self._get_earnings_data(stock, info)

            # Insider transactions
            result["insider"] = self._get_insider_data(stock)

            # Institutional holders summary
            result["institutional"] = self._get_institutional_data(stock)

            indicators_found = sum(
                1 for k in ["financials", "analyst", "earnings", "insider", "institutional"]
                if result.get(k) and any(v is not None for v in result[k].values())
                if isinstance(result[k], dict)
            )
            logger.info(f"Yahoo fundamentals: {indicators_found}/5 data sections loaded for {ticker}")

        except Exception as e:
            logger.error(f"Yahoo fundamentals error for {ticker}: {e}")

        return result

    def _get_analyst_data(self, stock: yf.Ticker, info: dict) -> dict:
        """Extract analyst recommendations and price targets."""
        try:
            rec = {}
            rec["target_mean"] = info.get("targetMeanPrice")
            rec["target_high"] = info.get("targetHighPrice")
            rec["target_low"] = info.get("targetLowPrice")
            rec["recommendation"] = info.get("recommendationKey")  # buy, hold, sell
            rec["num_analysts"] = info.get("numberOfAnalystOpinions")

            # Recent recommendation trends
            try:
                recs = stock.recommendations
                if recs is not None and not recs.empty:
                    recent = recs.tail(1).iloc[0]
                    rec["strong_buy"] = int(recent.get("strongBuy", 0))
                    rec["buy"] = int(recent.get("buy", 0))
                    rec["hold"] = int(recent.get("hold", 0))
                    rec["sell"] = int(recent.get("sell", 0))
                    rec["strong_sell"] = int(recent.get("strongSell", 0))
            except Exception:
                pass

            # Upside/downside from current price
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            target = rec.get("target_mean")
            if current and target:
                rec["upside_pct"] = round((target - current) / current * 100, 1)

            return rec
        except Exception as e:
            logger.debug(f"Analyst data error: {e}")
            return {}

    def _get_earnings_data(self, stock: yf.Ticker, info: dict) -> dict:
        """Get upcoming earnings date and recent EPS data."""
        try:
            earnings = {}

            # Upcoming earnings date
            try:
                cal = stock.calendar
                if cal is not None:
                    if isinstance(cal, dict):
                        earn_date = cal.get("Earnings Date")
                        if earn_date:
                            if isinstance(earn_date, list) and len(earn_date) > 0:
                                earnings["next_date"] = str(earn_date[0])
                            else:
                                earnings["next_date"] = str(earn_date)
                    elif hasattr(cal, "iloc"):
                        earnings["next_date"] = str(cal.iloc[0]) if len(cal) > 0 else None
            except Exception:
                pass

            # Days until earnings
            if earnings.get("next_date"):
                try:
                    earn_dt = datetime.strptime(earnings["next_date"][:10], "%Y-%m-%d")
                    days = (earn_dt - datetime.now()).days
                    earnings["days_until"] = days
                    earnings["imminent"] = days <= 7  # Flag if within a week
                except Exception:
                    earnings["days_until"] = None
                    earnings["imminent"] = False

            # EPS data
            earnings["trailing_eps"] = info.get("trailingEps")
            earnings["forward_eps"] = info.get("forwardEps")

            # Recent earnings history (beat/miss)
            try:
                hist = stock.earnings_history
                if hist is not None and not hist.empty:
                    recent = hist.tail(4)
                    beats = 0
                    for _, row in recent.iterrows():
                        actual = row.get("epsActual", 0)
                        estimate = row.get("epsEstimate", 0)
                        if actual and estimate and actual > estimate:
                            beats += 1
                    earnings["beats_last_4q"] = beats
                    earnings["beat_rate"] = round(beats / len(recent) * 100)
            except Exception:
                pass

            return earnings
        except Exception as e:
            logger.debug(f"Earnings data error: {e}")
            return {}

    def _get_insider_data(self, stock: yf.Ticker) -> dict:
        """Summarize recent insider buying/selling."""
        try:
            insiders = stock.insider_transactions
            if insiders is None or insiders.empty:
                return {"activity": "no data"}

            recent = insiders.head(20)
            buys = 0
            sells = 0
            buy_value = 0
            sell_value = 0

            for _, row in recent.iterrows():
                text = str(row.get("Text", "")).lower()
                shares = abs(row.get("Shares", 0) or 0)
                value = abs(row.get("Value", 0) or 0)

                if "purchase" in text or "buy" in text or "acquisition" in text:
                    buys += 1
                    buy_value += value
                elif "sale" in text or "sell" in text:
                    sells += 1
                    sell_value += value

            if buys > sells:
                signal = "net_buying"
            elif sells > buys:
                signal = "net_selling"
            else:
                signal = "neutral"

            return {
                "buys": buys,
                "sells": sells,
                "buy_value": buy_value,
                "sell_value": sell_value,
                "signal": signal,
            }
        except Exception as e:
            logger.debug(f"Insider data error: {e}")
            return {"activity": "no data"}

    def _get_institutional_data(self, stock: yf.Ticker) -> dict:
        """Summarize institutional ownership."""
        try:
            info = stock.info or {}
            result = {
                "held_pct": info.get("heldPercentInstitutions"),
                "insider_held_pct": info.get("heldPercentInsiders"),
            }

            holders = stock.institutional_holders
            if holders is not None and not holders.empty:
                result["top_holders"] = len(holders)
                result["top_holder_name"] = holders.iloc[0].get("Holder", "Unknown")

            return result
        except Exception as e:
            logger.debug(f"Institutional data error: {e}")
            return {}

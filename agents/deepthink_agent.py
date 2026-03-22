"""DeepThink Agent — Chain-of-thought analysis with conviction scoring and scenario modeling."""

from __future__ import annotations

import logging

from config import Config
from utils.claude_analyst import ClaudeAnalyst
from utils.database import Database
from utils.yahoo_fundamentals import YahooFundamentals

logger = logging.getLogger(__name__)


class DeepThinkAgent:
    def __init__(self, db: Database | None = None):
        self.config = Config()
        self.db = db or Database()
        self.yahoo = YahooFundamentals()
        self.claude = ClaudeAnalyst()

    def _score_factors(self, report: dict) -> tuple[list[dict], list[dict]]:
        """Extract and score bullish/bearish factors from research report."""
        bullish = []
        bearish = []

        # News sentiment
        news_score = report.get("news_impact_score", 0)
        if news_score > 0:
            bullish.append({
                "factor": f"Positive news sentiment ({news_score}/10)",
                "strength": min(10, max(1, int(abs(news_score)))),
            })
        elif news_score < 0:
            bearish.append({
                "factor": f"Negative news sentiment ({news_score}/10)",
                "strength": min(10, max(1, int(abs(news_score)))),
            })

        # Reddit sentiment
        reddit_score = report.get("reddit_sentiment_score", 0)
        reddit_data = report.get("reddit_data", {})
        post_count = reddit_data.get("post_count", 0)

        if reddit_score > 0.2:
            bullish.append({
                "factor": f"Bullish Reddit sentiment ({reddit_score:.2f}) across {post_count} posts",
                "strength": min(10, max(1, int(reddit_score * 10))),
            })
        elif reddit_score < -0.2:
            bearish.append({
                "factor": f"Bearish Reddit sentiment ({reddit_score:.2f})",
                "strength": min(10, max(1, int(abs(reddit_score) * 10))),
            })

        # Themes from Reddit
        themes = reddit_data.get("themes", [])
        for theme in themes:
            if any(w in theme.lower() for w in ["fomo", "moon", "bull", "squeeze"]):
                bullish.append({"factor": f"Reddit theme: {theme}", "strength": 4})
            elif any(w in theme.lower() for w in ["bear", "overvalued"]):
                bearish.append({"factor": f"Reddit theme: {theme}", "strength": 4})

        # Technicals
        tech = report.get("technicals", {})
        if "error" not in tech:
            rsi = tech.get("rsi_14", 50)
            if rsi < 30:
                bullish.append({"factor": f"RSI oversold ({rsi})", "strength": 7})
            elif rsi > 70:
                bearish.append({"factor": f"RSI overbought ({rsi})", "strength": 7})
            elif rsi < 45:
                bullish.append({"factor": f"RSI neutral-low ({rsi})", "strength": 3})

            if tech.get("above_sma_10") and tech.get("above_sma_20"):
                bullish.append({"factor": "Price above SMA-10 and SMA-20", "strength": 6})
            elif not tech.get("above_sma_10") and not tech.get("above_sma_20"):
                bearish.append({"factor": "Price below SMA-10 and SMA-20", "strength": 6})

            vol_ratio = tech.get("volume_ratio", 1)
            if vol_ratio > 1.5:
                bullish.append({"factor": f"High volume ({vol_ratio}x avg)", "strength": 5})
            elif vol_ratio < 0.5:
                bearish.append({"factor": f"Low volume ({vol_ratio}x avg)", "strength": 4})

            change = tech.get("daily_change_pct", 0)
            if change > 2:
                bullish.append({"factor": f"Strong daily gain ({change}%)", "strength": 5})
            elif change < -2:
                bearish.append({"factor": f"Sharp daily decline ({change}%)", "strength": 5})

        # Advanced technicals from Twelve Data
        adv = report.get("advanced_technicals", {})
        if adv:
            macd = adv.get("macd", {})
            if macd.get("crossover") == "bullish":
                bullish.append({"factor": "MACD bullish crossover", "strength": 8})
            elif macd.get("crossover") == "bearish":
                bearish.append({"factor": "MACD bearish crossover", "strength": 8})
            elif macd.get("trend") == "bullish":
                bullish.append({"factor": "MACD trending bullish", "strength": 4})
            elif macd.get("trend") == "bearish":
                bearish.append({"factor": "MACD trending bearish", "strength": 4})

            ema = adv.get("ema", {})
            if ema.get("crossover") == "bullish":
                bullish.append({"factor": "EMA 9/21 bullish crossover", "strength": 7})
            elif ema.get("crossover") == "bearish":
                bearish.append({"factor": "EMA 9/21 bearish crossover", "strength": 7})

            bbands = adv.get("bbands", {})
            tech = report.get("technicals", {})
            price = tech.get("current_price", 0)
            if bbands and price:
                if price > bbands.get("upper", float("inf")):
                    bearish.append({"factor": "Price above Bollinger upper band", "strength": 6})
                elif price < bbands.get("lower", 0):
                    bullish.append({"factor": "Price below Bollinger lower band", "strength": 6})
                if bbands.get("bandwidth_pct", 10) < 5:
                    bullish.append({"factor": "Bollinger squeeze — breakout likely", "strength": 5})

            stoch = adv.get("stoch", {})
            if stoch.get("zone") == "oversold" and stoch.get("crossover") == "bullish":
                bullish.append({"factor": f"Stochastic oversold + bullish cross ({stoch.get('k', 0):.0f})", "strength": 7})
            elif stoch.get("zone") == "overbought" and stoch.get("crossover") == "bearish":
                bearish.append({"factor": f"Stochastic overbought + bearish cross ({stoch.get('k', 0):.0f})", "strength": 7})

            adx = adv.get("adx", {})
            if adx.get("trend_strength") in ("strong", "very_strong"):
                # Strong trend amplifies the dominant direction
                bull_total = sum(f["strength"] for f in bullish)
                bear_total = sum(f["strength"] for f in bearish)
                if bull_total > bear_total:
                    bullish.append({"factor": f"Strong trend (ADX {adx.get('adx', 0)})", "strength": 5})
                else:
                    bearish.append({"factor": f"Strong downtrend (ADX {adx.get('adx', 0)})", "strength": 5})
            elif adx.get("trend_strength") == "weak":
                bearish.append({"factor": "Weak/no trend (ADX < 20) — range-bound", "strength": 3})

        # Seeking Alpha email intelligence
        sa = report.get("seeking_alpha", {})
        if sa.get("mentioned"):
            sa_sent = sa.get("avg_sentiment", 0)
            sa_cats = sa.get("categories", [])
            mentions = sa.get("mention_count", 0)

            if sa_sent > 0.2:
                strength = min(10, max(3, int(sa_sent * 8) + mentions))
                bullish.append({
                    "factor": f"Seeking Alpha bullish coverage ({sa_sent:.2f}, {mentions} mentions)",
                    "strength": strength,
                })
            elif sa_sent < -0.2:
                strength = min(10, max(3, int(abs(sa_sent) * 8) + mentions))
                bearish.append({
                    "factor": f"Seeking Alpha bearish coverage ({sa_sent:.2f})",
                    "strength": strength,
                })

            if "insider_activity" in sa_cats:
                if sa_sent > 0:
                    bullish.append({"factor": "SA insider buying signal", "strength": 6})
                else:
                    bearish.append({"factor": "SA insider selling signal", "strength": 6})

            if "earnings" in sa_cats:
                bearish.append({"factor": "SA earnings event risk", "strength": 4})

        # Pad minimums
        while len(bullish) < 2:
            bullish.append({"factor": "No additional bullish factor found", "strength": 1})
        while len(bearish) < 2:
            bearish.append({"factor": "No additional bearish factor found", "strength": 1})

        return bullish, bearish

    def _contrarian_analysis(
        self, bullish: list[dict], bearish: list[dict], report: dict
    ) -> list[str]:
        """Devil's advocate: what could go wrong in each scenario?"""
        contrarian = []

        if any(f["strength"] >= 6 for f in bullish):
            contrarian.append(
                "Strong bullish signals may indicate crowded trade — "
                "smart money could be distributing while retail piles in."
            )
        if any(f["strength"] >= 6 for f in bearish):
            contrarian.append(
                "Extreme bearishness often marks bottoms — "
                "capitulation selling could set up a snap-back rally."
            )

        reddit_data = report.get("reddit_data", {})
        if reddit_data.get("post_count", 0) > 10:
            contrarian.append(
                "High Reddit activity is a lagging indicator — "
                "the move may already be priced in by the time retail notices."
            )

        tech = report.get("technicals", {})
        if tech.get("volume_ratio", 1) > 2:
            contrarian.append(
                "Spike in volume without follow-through could be a "
                "one-day event (earnings, news) that fades quickly."
            )

        if not contrarian:
            contrarian.append("No strong contrarian signals detected.")

        return contrarian

    def _model_scenarios(self, report: dict) -> list[dict]:
        """Monte Carlo-style scenario modeling: bull, base, bear cases."""
        tech = report.get("technicals", {})
        current_price = tech.get("current_price", 100)
        catalyst = report.get("combined_catalyst_score", 0)

        # Estimate expected moves based on catalyst strength
        if catalyst > 0.3:
            bull_return = round(8 + catalyst * 15, 1)
            base_return = round(2 + catalyst * 5, 1)
            bear_return = round(-3 - abs(catalyst) * 5, 1)
            bull_prob, base_prob, bear_prob = 40, 35, 25
        elif catalyst < -0.3:
            bull_return = round(3 + abs(catalyst) * 5, 1)
            base_return = round(-2 + catalyst * 5, 1)
            bear_return = round(-10 - abs(catalyst) * 10, 1)
            bull_prob, base_prob, bear_prob = 20, 35, 45
        else:
            bull_return = 5.0
            base_return = 0.5
            bear_return = -4.0
            bull_prob, base_prob, bear_prob = 30, 40, 30

        return [
            {
                "scenario": "Bull",
                "probability_pct": bull_prob,
                "expected_1w_return_pct": bull_return,
                "target_price": round(current_price * (1 + bull_return / 100), 2),
            },
            {
                "scenario": "Base",
                "probability_pct": base_prob,
                "expected_1w_return_pct": base_return,
                "target_price": round(current_price * (1 + base_return / 100), 2),
            },
            {
                "scenario": "Bear",
                "probability_pct": bear_prob,
                "expected_1w_return_pct": bear_return,
                "target_price": round(current_price * (1 + bear_return / 100), 2),
            },
        ]

    def _calculate_conviction(
        self, bullish: list[dict], bearish: list[dict], catalyst: float
    ) -> float:
        """Calculate final conviction score 1-10."""
        bull_strength = sum(f["strength"] for f in bullish)
        bear_strength = sum(f["strength"] for f in bearish)

        # Count strong signals (strength >= 6)
        strong_bull = sum(1 for f in bullish if f["strength"] >= 6)
        strong_bear = sum(1 for f in bearish if f["strength"] >= 6)

        # Base: ratio of bull vs bear strength, centered at 5
        total = max(bull_strength + bear_strength, 1)
        ratio = bull_strength / total  # 0 to 1, 0.5 = balanced
        base = ratio * 10  # 0 to 10

        # Bonus for strong confirming signals
        signal_bonus = (strong_bull - strong_bear) * 0.5

        # Catalyst amplifier (scaled up — 0.3 catalyst = 1.5 points)
        catalyst_bonus = catalyst * 5

        conviction = base + signal_bonus + catalyst_bonus
        return round(max(1, min(10, conviction)), 1)

    # ── Phase 3: Multi-Edge Validation ──────────────────────────

    def _evaluate_technical_edge(self, report: dict) -> dict:
        """Phase 3b: Technical edge — price above 200-day SMA, RSI oversold, volume breakout."""
        tech = report.get("technicals", {})
        fundamentals = report.get("fundamentals", {})
        criteria_met = 0
        details = []

        # 1. Price above 200-day SMA (for longs)
        current_price = tech.get("current_price", 0)
        fin = fundamentals.get("financials", {}) if fundamentals else {}
        sma_200 = fin.get("200d_avg")
        if sma_200 and current_price and current_price > sma_200:
            criteria_met += 1
            details.append(f"Above 200-SMA (${current_price:.2f} > ${sma_200:.2f})")

        # 2. RSI(14) in oversold zone (< 30) or neutral-bullish (< 45)
        rsi = tech.get("rsi_14", 50)
        if rsi < 30:
            criteria_met += 1
            details.append(f"RSI oversold ({rsi})")
        elif rsi < 45:
            criteria_met += 1
            details.append(f"RSI neutral-bullish ({rsi})")

        # 3. Volume > 1.5x 20-day average
        vol_ratio = tech.get("volume_ratio", 1)
        if vol_ratio > 1.5:
            criteria_met += 1
            details.append(f"Volume breakout ({vol_ratio:.1f}x avg)")

        passed = criteria_met >= 2
        return {"passed": passed, "strength": criteria_met, "details": details, "label": "Technical"}

    def _evaluate_sentiment_edge(self, report: dict) -> dict:
        """Phase 3c: Sentiment/Regime edge — VIX, news catalyst score."""
        criteria_met = 0
        details = []

        # 1. Combined catalyst score positive
        catalyst = report.get("combined_catalyst_score", 0)
        if catalyst > 0.2:
            criteria_met += 1
            details.append(f"Positive catalyst ({catalyst:.3f})")

        # 2. News sentiment positive
        news_score = report.get("news_impact_score", 0)
        if news_score > 2:
            criteria_met += 1
            details.append(f"Bullish news ({news_score}/10)")

        # 3. Reddit sentiment positive
        reddit_score = report.get("reddit_sentiment_score", 0)
        if reddit_score > 0.3:
            criteria_met += 1
            details.append(f"Bullish Reddit ({reddit_score:.2f})")

        passed = criteria_met >= 2
        return {"passed": passed, "strength": criteria_met, "details": details, "label": "Sentiment"}

    def _evaluate_edges(self, report: dict) -> tuple[int, list[dict]]:
        """Run all 3 edge checks and return (edges_firing, edge_details)."""
        ticker = report["ticker"]

        # Edge 1: Fundamental
        fund_edge = self.yahoo.evaluate_fundamental_edge(ticker)

        # Edge 2: Technical
        tech_edge = self._evaluate_technical_edge(report)

        # Edge 3: Sentiment/Regime
        sent_edge = self._evaluate_sentiment_edge(report)

        edges = [fund_edge, tech_edge, sent_edge]
        edges_firing = sum(1 for e in edges if e["passed"])

        logger.info(
            f"Edge validation for {ticker}: {edges_firing}/3 edges firing — "
            f"Fund={'PASS' if fund_edge['passed'] else 'FAIL'}, "
            f"Tech={'PASS' if tech_edge['passed'] else 'FAIL'}, "
            f"Sent={'PASS' if sent_edge['passed'] else 'FAIL'}"
        )

        return edges_firing, edges

    def analyze(self, report: dict, portfolio: str = "main") -> dict:
        """Run full deep-think analysis on a research report."""
        ticker = report["ticker"]
        logger.info(f"DeepThink analysis starting for {ticker} [{portfolio}]...")

        # Step 1 & 2: Score factors
        bullish, bearish = self._score_factors(report)

        # Step 3: Contrarian analysis
        contrarian = self._contrarian_analysis(bullish, bearish, report)

        # Step 4: Scenario modeling
        scenarios = self._model_scenarios(report)

        # Step 5: Position sizing
        tech = report.get("technicals", {})
        current_price = tech.get("current_price", 100)
        catalyst = report.get("combined_catalyst_score", 0)

        # Dynamic stop-loss: use ATR if available, otherwise percentage-based
        conviction = self._calculate_conviction(bullish, bearish, catalyst)
        adv = report.get("advanced_technicals", {})
        atr = adv.get("atr", {}).get("atr", 0) if adv else 0

        if atr > 0 and current_price > 0:
            # ATR-based stop: 2x ATR as stop distance
            atr_stop_pct = round((atr * 2) / current_price * 100, 1)
            # Clamp between 2% and 10%
            base_stop = max(2.0, min(10.0, atr_stop_pct))
            logger.info(f"ATR-based stop for {ticker}: {base_stop}% (ATR={atr})")
        else:
            base_stop = 5.0

        if conviction >= 9:
            stop_loss_pct = round(base_stop * 0.8, 1)
        elif conviction >= 7:
            stop_loss_pct = base_stop
        else:
            stop_loss_pct = round(base_stop * 1.2, 1)

        # Use portfolio-specific parameters
        if portfolio == "penny":
            min_rr = self.config.PENNY_MIN_REWARD_RISK_RATIO
            max_risk = self.config.PENNY_MAX_RISK_PER_TRADE
            min_conv = self.config.PENNY_MIN_CONVICTION
        else:
            min_rr = self.config.MIN_REWARD_RISK_RATIO
            max_risk = self.config.MAX_RISK_PER_TRADE
            min_conv = self.config.MIN_CONVICTION

        # Use math.ceil to ensure take_profit always meets the R:R ratio after rounding
        import math
        take_profit_pct = math.ceil(stop_loss_pct * min_rr * 10) / 10
        position_size_pct = round(
            (max_risk * 100) / (stop_loss_pct / 100), 2
        )
        position_size_pct = min(position_size_pct, 10)  # Cap at 10% of account

        # Step 6: Edge validation (Phase 3)
        edges_firing, edge_details = self._evaluate_edges(report)

        # Phase 8c: Sector rotation awareness — penalize if sector ETF is weak
        fundamentals = report.get("fundamentals", {})
        sector = ""
        if fundamentals:
            try:
                import yfinance as yf
                ticker_obj = yf.Ticker(ticker)
                sector = ticker_obj.info.get("sector", "")
            except Exception:
                pass

        if sector:
            from utils.risk_manager import RiskManager
            rm = RiskManager(self.db)
            sector_trend = rm.check_sector_trend(sector)
            if not sector_trend["uptrend"]:
                conviction = max(1, conviction - 0.5)
                bearish.append({
                    "factor": f"Sector headwind: {sector} ({sector_trend['etf']}) below 50-SMA",
                    "strength": 4,
                })

        # Phase 8b: Adjust conviction based on historical edge combo performance
        combo_parts = []
        for e in edge_details:
            if e["passed"]:
                combo_parts.append(e["label"][0])  # F, T, or S
        edge_combo = "+".join(combo_parts) if combo_parts else "none"

        historical_wr = self.db.get_edge_combo_win_rate(edge_combo)
        if historical_wr is not None:
            if historical_wr > 0.65:
                bonus = round((historical_wr - 0.5) * 3, 1)  # up to +1.5
                conviction = min(10, conviction + bonus)
                logger.info(
                    f"Edge combo '{edge_combo}' has {historical_wr*100:.0f}% win rate — "
                    f"conviction boosted +{bonus}"
                )
            elif historical_wr < 0.35:
                penalty = round((0.5 - historical_wr) * 3, 1)  # up to -1.5
                conviction = max(1, conviction - penalty)
                logger.warning(
                    f"Edge combo '{edge_combo}' has {historical_wr*100:.0f}% win rate — "
                    f"conviction penalized -{penalty}"
                )

        # Step 7: Decision — require at least MIN_EDGES_REQUIRED edges
        if edges_firing < self.config.MIN_EDGES_REQUIRED:
            action = "HOLD"
            edge_reason = f"Only {edges_firing}/{self.config.MIN_EDGES_REQUIRED} edges firing"
        elif conviction >= min_conv and catalyst > 0:
            action = "BUY"
            edge_reason = f"{edges_firing}/3 edges confirmed"
        elif conviction >= min_conv and catalyst < 0:
            action = "SELL"
            edge_reason = f"{edges_firing}/3 edges confirmed"
        else:
            action = "HOLD"
            edge_reason = "Conviction below threshold"

        # Step 8: Claude qualitative analysis — adjusts conviction and can override action
        claude_analysis = {}
        if self.claude.enabled:
            pre_claude_analysis = {
                "action": action, "conviction": conviction,
                "bullish_factors": bullish, "bearish_factors": bearish,
                "edge_details": edge_details,
            }
            claude_analysis = self.claude.analyze_trade(report, pre_claude_analysis)

            # Apply conviction adjustment (scaled by Claude's confidence)
            adj = claude_analysis.get("conviction_adjustment", 0)
            conf = claude_analysis.get("confidence", 0)
            scaled_adj = adj * conf  # Low-confidence adjustments have less impact
            if abs(scaled_adj) > 0.1:
                conviction = round(max(1, min(10, conviction + scaled_adj)), 1)
                logger.info(
                    f"Claude adjusted conviction for {ticker}: {scaled_adj:+.1f} "
                    f"(raw={adj:+.1f}, confidence={conf:.0%}) → {conviction}"
                )

            # Action override — only if Claude is highly confident
            override = claude_analysis.get("action_override")
            if override and conf >= 0.8 and override != action:
                logger.warning(
                    f"CLAUDE OVERRIDE for {ticker}: {action} → {override} "
                    f"(confidence={conf:.0%}): {claude_analysis.get('qualitative_assessment', '')}"
                )
                action = override

            # Re-check decision after conviction adjustment
            if action != "HOLD" and conviction < min_conv:
                action = "HOLD"
                edge_reason = f"Conviction dropped below threshold after Claude analysis ({conviction})"

        # Build reasoning summary
        top_bull = sorted(bullish, key=lambda x: x["strength"], reverse=True)[:2]
        top_bear = sorted(bearish, key=lambda x: x["strength"], reverse=True)[:2]
        edge_summary = " | ".join(
            f"{e['label']}: {'PASS' if e['passed'] else 'FAIL'} ({', '.join(e['details'][:2])})"
            for e in edge_details
        )
        claude_note = ""
        if claude_analysis.get("qualitative_assessment"):
            claude_note = f" Claude: {claude_analysis['qualitative_assessment']}"
        reasoning = (
            f"Top bullish: {', '.join(f['factor'] for f in top_bull)}. "
            f"Top bearish: {', '.join(f['factor'] for f in top_bear)}. "
            f"Combined catalyst: {catalyst:.3f}. "
            f"Edges: {edge_summary}. "
            f"{edge_reason}.{claude_note}"
        )

        analysis = {
            "ticker": ticker,
            "action": action,
            "conviction": conviction,
            "position_size_pct": position_size_pct,
            "stop_loss_pct": round(stop_loss_pct, 1),
            "take_profit_pct": take_profit_pct,
            "reasoning_summary": reasoning,
            "bullish_factors": bullish,
            "bearish_factors": bearish,
            "contrarian_views": contrarian,
            "scenarios": scenarios,
            "risks": [f["factor"] for f in sorted(bearish, key=lambda x: x["strength"], reverse=True)[:3]],
            "current_price": current_price,
            "edges_firing": edges_firing,
            "edge_details": [
                {"label": e["label"], "passed": e["passed"], "strength": e["strength"], "details": e["details"]}
                for e in edge_details
            ],
            "claude_analysis": claude_analysis if claude_analysis else None,
        }

        self.db.save_analysis(analysis, portfolio=portfolio)
        logger.info(f"DeepThink result for {ticker} [{portfolio}]: {action} (conviction: {conviction})")

        return analysis

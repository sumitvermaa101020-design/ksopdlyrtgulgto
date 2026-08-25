"""
15-MINUTE SMC + ORDER FLOW CONFLUENCE RADAR
Computes Market Entry, Ideal Entry (FVG CE 50%), Stop Loss, and TP1/TP2/TP3.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List
import numpy as np

from indicators import QuantitativeEngine
from config import MIN_SL_DISTANCE_USD, MAX_SL_DISTANCE_USD


def _clamp_sl_dist(raw_dist: float) -> float:
    return min(max(raw_dist, MIN_SL_DISTANCE_USD), MAX_SL_DISTANCE_USD)


@dataclass
class ScalpSignal15M:
    timestamp_utc: str = ""
    symbol: str = "XAUUSDT"
    direction: str = "NEUTRAL"
    market_entry: float = 0.0
    ideal_entry: float = 0.0
    stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    risk_reward_ratio: float = 0.0
    risk_per_ounce: float = 0.0
    confluence_score: int = 0
    market_regime: str = "CHOP"
    structure_status: str = "SIDEWAYS"
    fvg_zone: str = "NONE"
    order_block_zone: str = "NONE"
    session_killzone: str = "NONE"
    confluence_reasons: List[str] = field(default_factory=list)


class SignalEngine15M:
    def evaluate_15m_klines(
        self,
        klines_15m: List[List[float]],
        current_price: float,
        cvd_5s: float,
        ob_imbalance: float,
        ofi: float,
    ) -> ScalpSignal15M:
        if len(klines_15m) < 30 or current_price <= 0:
            return ScalpSignal15M(
                direction="INITIALIZING",
                confluence_reasons=["Accumulating 15m candle history..."],
            )

        highs = np.array([k[2] for k in klines_15m])
        lows = np.array([k[3] for k in klines_15m])
        closes = np.array([k[4] for k in klines_15m])

        ema_20 = QuantitativeEngine.calculate_ema(closes, 20)
        ema_50 = QuantitativeEngine.calculate_ema(closes, 50)
        atr = max(QuantitativeEngine.calculate_atr(closes, highs, lows, 14), 1.50)
        rsi = QuantitativeEngine.calculate_rsi(closes, 14)
        vwap_15m, _vwap_upper, _vwap_lower = QuantitativeEngine.calculate_session_vwap(klines_15m)

        # Structural Extremes (10-bar swing excluded current bar)
        recent_high_10 = float(np.max(highs[-10:-1])) if len(highs) > 10 else float(np.max(highs[:-1]))
        recent_low_10 = float(np.min(lows[-10:-1])) if len(lows) > 10 else float(np.min(lows[:-1]))
        range_high_30 = float(np.max(highs[-30:]))
        range_low_30 = float(np.min(lows[-30:]))
        eq_range = (range_high_30 + range_low_30) / 2.0
        is_discount = current_price < eq_range
        is_premium = current_price > eq_range

        # Market Structure (BOS / CHoCH)
        structure_status = "SIDEWAYS"
        if closes[-1] > recent_high_10:
            structure_status = "BOS_BULL (Break of Structure High)"
        elif closes[-1] < recent_low_10:
            structure_status = "BOS_BEAR (Break of Structure Low)"
        elif len(closes) >= 2 and closes[-1] > ema_50 and closes[-2] < ema_50:
            structure_status = "CHOCH_BULL (Change of Character)"
        elif len(closes) >= 2 and closes[-1] < ema_50 and closes[-2] > ema_50:
            structure_status = "CHOCH_BEAR (Change of Character)"

        # Fair Value Gap (3-bar gap)
        fvg_bull = len(klines_15m) >= 3 and highs[-3] < lows[-1]
        fvg_bear = len(klines_15m) >= 3 and lows[-3] > highs[-1]
        if fvg_bull:
            fvg_lower = float(highs[-3])
            fvg_upper = float(lows[-1])
            fvg_ce = (fvg_lower + fvg_upper) / 2.0
            fvg_desc = f"Bull FVG: ${fvg_lower:,.2f}-${fvg_upper:,.2f} (CE: ${fvg_ce:,.2f})"
        elif fvg_bear:
            fvg_lower = float(highs[-1])
            fvg_upper = float(lows[-3])
            fvg_ce = (fvg_lower + fvg_upper) / 2.0
            fvg_desc = f"Bear FVG: ${fvg_lower:,.2f}-${fvg_upper:,.2f} (CE: ${fvg_ce:,.2f})"
        else:
            fvg_lower = fvg_upper = fvg_ce = 0.0
            fvg_desc = "None"

        # Order Block (last opposing candle before displacement)
        ob_bull_price = float(lows[-2]) if len(klines_15m) >= 2 and closes[-1] > highs[-2] else 0.0
        ob_bear_price = float(highs[-2]) if len(klines_15m) >= 2 and closes[-1] < lows[-2] else 0.0
        ob_desc = (
            f"Bull OB @ ${ob_bull_price:,.2f}" if ob_bull_price > 0
            else f"Bear OB @ ${ob_bear_price:,.2f}" if ob_bear_price > 0
            else "None"
        )

        # Killzone Status
        utc_now = datetime.now(timezone.utc)
        cur_hour = utc_now.hour
        session_kz = "ASIA ACCUMULATION"
        if 7 <= cur_hour < 10:
            session_kz = "LONDON OPEN KILLZONE"
        elif 12 <= cur_hour < 16:
            session_kz = "NY / COMEX OPEN KILLZONE"
        elif 15 <= cur_hour < 17:
            session_kz = "LONDON FIX / NY OVERLAP"

        bull_score = 0
        bear_score = 0
        reasons: List[str] = []

        # 1. EMA Stack (20)
        if current_price > ema_20 > ema_50:
            bull_score += 20
            reasons.append("15m Bullish EMA Stack (Price > EMA20 > EMA50)")
        elif current_price < ema_20 < ema_50:
            bear_score += 20
            reasons.append("15m Bearish EMA Stack (Price < EMA20 < EMA50)")

        # 2. Session VWAP (15)
        if current_price > vwap_15m:
            bull_score += 15
            reasons.append(f"Price Above 15m VWAP (${vwap_15m:,.2f})")
        else:
            bear_score += 15
            reasons.append(f"Price Below 15m VWAP (${vwap_15m:,.2f})")

        # 3. RSI Momentum (15)
        if 48 <= rsi <= 68:
            bull_score += 15
            reasons.append(f"Bullish RSI Momentum ({rsi:.1f})")
        elif 32 <= rsi <= 52:
            bear_score += 15
            reasons.append(f"Bearish RSI Momentum ({rsi:.1f})")

        # 4. Market Structure (20)
        if "BULL" in structure_status:
            bull_score += 20
            reasons.append(f"15m Market Structure: {structure_status}")
        elif "BEAR" in structure_status:
            bear_score += 20
            reasons.append(f"15m Market Structure: {structure_status}")

        # 5. FVG & Discount/Premium (15)
        if fvg_bull and is_discount:
            bull_score += 15
            reasons.append(f"Bull FVG in Discount Zone (CE: ${fvg_ce:,.2f})")
        elif fvg_bear and is_premium:
            bear_score += 15
            reasons.append(f"Bear FVG in Premium Zone (CE: ${fvg_ce:,.2f})")

        # 6. Order Flow Imbalance & CVD (15)
        if ob_imbalance > 15.0 and cvd_5s > 0:
            bull_score += 15
            reasons.append(f"L2 Bid Heavy (+{ob_imbalance:.1f}%) & Positive CVD")
        elif ob_imbalance < -15.0 and cvd_5s < 0:
            bear_score += 15
            reasons.append(f"L2 Ask Heavy ({ob_imbalance:.1f}%) & Negative CVD")

        now_str = utc_now.strftime("%H:%M:%S UTC")
        sig = ScalpSignal15M(
            timestamp_utc=now_str,
            fvg_zone=fvg_desc,
            order_block_zone=ob_desc,
            structure_status=structure_status,
            session_killzone=session_kz,
        )

        if bull_score >= 60 and bull_score > bear_score:
            sig.direction = "STRONG BUY (LONG)" if bull_score >= 80 else "BUY (LONG)"
            sig.confluence_score = bull_score
            sig.market_regime = "TRENDING BULL" if bull_score >= 80 else "MOMENTUM EXPANSION"
            sig.market_entry = current_price
            sig.ideal_entry = fvg_ce if fvg_bull else max(ema_20, current_price - (0.5 * atr))
            sig.stop_loss = round(min(recent_low_10 - 0.50, sig.ideal_entry - (1.5 * atr)), 2)
            risk_dist = _clamp_sl_dist(sig.ideal_entry - sig.stop_loss)
            sig.stop_loss = round(sig.ideal_entry - risk_dist, 2)
            sig.risk_per_ounce = risk_dist
            sig.tp1 = round(sig.ideal_entry + (1.5 * risk_dist), 2)
            sig.tp2 = round(sig.ideal_entry + (2.5 * risk_dist), 2)
            sig.tp3 = round(sig.ideal_entry + (4.0 * risk_dist), 2)
            sig.risk_reward_ratio = round((sig.tp2 - sig.ideal_entry) / risk_dist, 2)
            sig.confluence_reasons = reasons
        elif bear_score >= 60 and bear_score > bull_score:
            sig.direction = "STRONG SELL (SHORT)" if bear_score >= 80 else "SELL (SHORT)"
            sig.confluence_score = bear_score
            sig.market_regime = "TRENDING BEAR" if bear_score >= 80 else "MOMENTUM EXPANSION"
            sig.market_entry = current_price
            sig.ideal_entry = fvg_ce if fvg_bear else min(ema_20, current_price + (0.5 * atr))
            sig.stop_loss = round(max(recent_high_10 + 0.50, sig.ideal_entry + (1.5 * atr)), 2)
            risk_dist = _clamp_sl_dist(sig.stop_loss - sig.ideal_entry)
            sig.stop_loss = round(sig.ideal_entry + risk_dist, 2)
            sig.risk_per_ounce = risk_dist
            sig.tp1 = round(sig.ideal_entry - (1.5 * risk_dist), 2)
            sig.tp2 = round(sig.ideal_entry - (2.5 * risk_dist), 2)
            sig.tp3 = round(sig.ideal_entry - (4.0 * risk_dist), 2)
            sig.risk_reward_ratio = round((sig.ideal_entry - sig.tp2) / risk_dist, 2)
            sig.confluence_reasons = reasons
        else:
            sig.direction = "NEUTRAL (WAIT FOR CONFLUENCE)"
            sig.confluence_score = max(bull_score, bear_score)
            sig.market_entry = current_price
            sig.ideal_entry = current_price
            sig.stop_loss = round(current_price - (1.5 * atr), 2)
            sig.tp1 = round(current_price + (1.5 * atr), 2)
            sig.tp2 = round(current_price + (2.5 * atr), 2)
            sig.tp3 = round(current_price + (4.0 * atr), 2)
            sig.risk_reward_ratio = 1.67
            sig.risk_per_ounce = _clamp_sl_dist(1.5 * atr)
            sig.confluence_reasons = reasons or ["Awaiting 15m structural break or FVG trigger."]

        return sig


signal_engine_15m = SignalEngine15M()

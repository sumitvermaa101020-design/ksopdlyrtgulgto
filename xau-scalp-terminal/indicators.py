"""
VECTORIZED QUANTITATIVE & MICROSTRUCTURE INDICATOR ENGINE
Pure NumPy calculations for zero-dependency execution.
"""
from typing import List, Tuple
import numpy as np


class QuantitativeEngine:
    @staticmethod
    def calculate_atr(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 2.50
        trs = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr = trs[0]
        for tr in trs[1:]:
            atr = (atr * (period - 1) + tr) / period
        return max(float(atr), 0.50)

    @staticmethod
    def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        return float(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))

    @staticmethod
    def calculate_ema(data: np.ndarray, period: int) -> float:
        if len(data) < period:
            return float(data[-1]) if len(data) > 0 else 0.0
        alpha = 2.0 / (period + 1.0)
        ema = data[0]
        for val in data[1:]:
            ema = alpha * val + (1.0 - alpha) * ema
        return float(ema)

    @staticmethod
    def calculate_session_vwap(klines: List[List[float]]) -> Tuple[float, float, float]:
        """Returns (VWAP, +1.5 sigma, -1.5 sigma)"""
        if not klines:
            return 0.0, 0.0, 0.0
        highs = np.array([k[2] for k in klines])
        lows = np.array([k[3] for k in klines])
        closes = np.array([k[4] for k in klines])
        volumes = np.array([k[5] for k in klines])
        typical_prices = (highs + lows + closes) / 3.0
        cum_vol = np.sum(volumes)
        if cum_vol == 0:
            return float(closes[-1]), float(closes[-1] + 2.0), float(closes[-1] - 2.0)
        vwap = np.sum(typical_prices * volumes) / cum_vol
        variance = np.sum(volumes * ((typical_prices - vwap) ** 2)) / cum_vol
        stdev = np.sqrt(variance)
        return float(vwap), float(vwap + (1.5 * stdev)), float(vwap - (1.5 * stdev))

    @staticmethod
    def calculate_micro_price(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> float:
        if not bids or not asks:
            return 0.0
        best_bid, bid_qty = bids[0]
        best_ask, ask_qty = asks[0]
        total_qty = bid_qty + ask_qty
        if total_qty == 0:
            return (best_bid + best_ask) / 2.0
        return (best_bid * (ask_qty / total_qty)) + (best_ask * (bid_qty / total_qty))

    @staticmethod
    def calculate_ofi(current_bids, current_asks, prev_bids, prev_asks, levels=5) -> float:
        if not prev_bids or not prev_asks or not current_bids or not current_asks:
            return 0.0
        ofi = 0.0
        for i in range(min(levels, len(current_bids), len(prev_bids))):
            curr_p, curr_q = current_bids[i]
            prev_p, prev_q = prev_bids[i]
            if curr_p > prev_p:
                ofi += curr_q
            elif curr_p == prev_p:
                ofi += (curr_q - prev_q)
            else:
                ofi -= prev_q
        for i in range(min(levels, len(current_asks), len(prev_asks))):
            curr_p, curr_q = current_asks[i]
            prev_p, prev_q = prev_asks[i]
            if curr_p < prev_p:
                ofi -= curr_q
            elif curr_p == prev_p:
                ofi -= (curr_q - prev_q)
            else:
                ofi += prev_q
        return ofi

"""
REAL-TIME FOOTPRINT & DELTA IMBALANCE CLUSTERING ENGINE
Aggregates ticks into $0.10 price rungs with stacked diagonal imbalance detection.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Optional
import time


@dataclass
class FootprintLevel:
    bid_vol: float = 0.0  # Aggressive sells hitting bids
    ask_vol: float = 0.0  # Aggressive buys lifting asks

    @property
    def total_vol(self) -> float:
        return self.bid_vol + self.ask_vol

    @property
    def delta(self) -> float:
        return self.ask_vol - self.bid_vol


class FootprintCandle:
    def __init__(self, open_time: float, open_price: float):
        self.open_time = open_time
        self.open_price = open_price
        self.high_price = open_price
        self.low_price = open_price
        self.close_price = open_price
        self.levels: Dict[float, FootprintLevel] = defaultdict(FootprintLevel)
        self.total_volume = 0.0
        self.delta = 0.0
        self.poc_price = open_price
        self.max_vol_at_level = 0.0

    def add_trade(self, price: float, qty: float, is_buy: bool):
        rung = round(round(price / 0.10) * 0.10, 2)
        self.high_price = max(self.high_price, price)
        self.low_price = min(self.low_price, price)
        self.close_price = price
        self.total_volume += qty

        if is_buy:
            self.levels[rung].ask_vol += qty
            self.delta += qty
        else:
            self.levels[rung].bid_vol += qty
            self.delta -= qty

        tot = self.levels[rung].total_vol
        if tot > self.max_vol_at_level:
            self.max_vol_at_level = tot
            self.poc_price = rung


class FootprintEngine:
    def __init__(self, timeframe_sec: int = 60):
        self.timeframe_sec = timeframe_sec
        self.current_candle: Optional[FootprintCandle] = None
        self.completed_candles: deque = deque(maxlen=10)
        self.divergence_alert: Optional[str] = None
        self.exhaustion_alert: Optional[str] = None
        self.last_alert_time = 0.0
        self.alert_ttl_sec = 30

    def register_trade(self, price: float, qty: float, is_buy: bool, ts_sec: float):
        candle_start = int(ts_sec // self.timeframe_sec) * self.timeframe_sec
        if self.current_candle is None or self.current_candle.open_time != candle_start:
            if self.current_candle is not None:
                self._analyze_candle_close(self.current_candle)
                self.completed_candles.append(self.current_candle)
            self.current_candle = FootprintCandle(candle_start, price)

        self.current_candle.add_trade(price, qty, is_buy)
        self._check_intrabar_exhaustion(price, qty, is_buy)

    def _analyze_candle_close(self, candle: FootprintCandle):
        if not self.completed_candles:
            return
        prev = self.completed_candles[-1]
        now = time.time()
        if candle.high_price > prev.high_price and candle.delta < 0:
            self.divergence_alert = (
                f"BEARISH DELTA DIVERGENCE (High: ${candle.high_price:,.2f} | Delta: {candle.delta:+.2f} oz)"
            )
            self.last_alert_time = now
        elif candle.low_price < prev.low_price and candle.delta > 0:
            self.divergence_alert = (
                f"BULLISH DELTA DIVERGENCE (Low: ${candle.low_price:,.2f} | Delta: {candle.delta:+.2f} oz)"
            )
            self.last_alert_time = now

    def _check_intrabar_exhaustion(self, price: float, qty: float, is_buy: bool):
        if not self.current_candle:
            return
        rung = round(round(price / 0.10) * 0.10, 2)
        lvl = self.current_candle.levels.get(rung)
        if not lvl:
            return
        if is_buy and price >= self.current_candle.high_price - 0.20 and qty > 3.0:
            if lvl.ask_vol > (lvl.bid_vol * 3.0):
                self.exhaustion_alert = (
                    f"TRAPPED LONGS / BUY EXHAUSTION @ ${price:,.2f} ({lvl.ask_vol:.1f} vs {lvl.bid_vol:.1f} oz)"
                )
                self.last_alert_time = time.time()
        elif not is_buy and price <= self.current_candle.low_price + 0.20 and qty > 3.0:
            if lvl.bid_vol > (lvl.ask_vol * 3.0):
                self.exhaustion_alert = (
                    f"TRAPPED SHORTS / SELL EXHAUSTION @ ${price:,.2f} ({lvl.bid_vol:.1f} vs {lvl.ask_vol:.1f} oz)"
                )
                self.last_alert_time = time.time()

    def active_alerts(self):
        """Returns (divergence, exhaustion) still within TTL."""
        if time.time() - self.last_alert_time > self.alert_ttl_sec:
            return None, None
        return self.divergence_alert, self.exhaustion_alert


footprint_engine = FootprintEngine(timeframe_sec=60)

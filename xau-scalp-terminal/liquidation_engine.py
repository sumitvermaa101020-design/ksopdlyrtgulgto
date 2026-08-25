"""
LIQUIDATION CASCADE & VELOCITY EXHAUSTION ENGINE
Captures real-time force orders from xauusdt@forceOrder.
"""
from collections import deque
import time


class LiquidationEngine:
    def __init__(self, window_sec: float = 60.0):
        self.window_sec = window_sec
        self.events: deque = deque()
        self.state = "IDLE"  # IDLE, ARMED, EXHAUSTING, TRIGGERED
        self.armed_timestamp_ns = 0
        self.peak_velocity = 0.0
        self.cascade_side = None
        self.wick_extreme = 0.0

    def register_event(self, side: str, qty: float, price: float):
        now_ns = time.time_ns()
        usd = qty * price
        self.events.append((now_ns, side, qty, price, usd))
        cutoff_ns = now_ns - int(self.window_sec * 1_000_000_000)
        while self.events and self.events[0][0] < cutoff_ns:
            self.events.popleft()

    def update(self, current_price: float, recent_cvd_delta: float) -> dict:
        now_ns = time.time_ns()
        cutoff_10s_ns = now_ns - int(10.0 * 1_000_000_000)
        long_10s = sum(e[4] for e in self.events if e[0] >= cutoff_10s_ns and e[1] == "SELL")
        short_10s = sum(e[4] for e in self.events if e[0] >= cutoff_10s_ns and e[1] == "BUY")
        velocity = (long_10s + short_10s) / 10.0
        action = None

        if self.state == "IDLE":
            if long_10s >= 250_000.0 and velocity >= 25_000.0:
                self.state = "ARMED"
                self.cascade_side = "LONG_LIQ"
                self.armed_timestamp_ns = now_ns
                self.peak_velocity = velocity
                self.wick_extreme = current_price
            elif short_10s >= 250_000.0 and velocity >= 25_000.0:
                self.state = "ARMED"
                self.cascade_side = "SHORT_LIQ"
                self.armed_timestamp_ns = now_ns
                self.peak_velocity = velocity
                self.wick_extreme = current_price

        elif self.state == "ARMED":
            self.peak_velocity = max(self.peak_velocity, velocity)
            if self.cascade_side == "LONG_LIQ":
                self.wick_extreme = min(self.wick_extreme, current_price)
            else:
                self.wick_extreme = max(self.wick_extreme, current_price)
            if velocity < (self.peak_velocity * 0.5):
                self.state = "EXHAUSTING"
            if (now_ns - self.armed_timestamp_ns) > int(20.0 * 1_000_000_000):
                self.state = "IDLE"

        elif self.state == "EXHAUSTING":
            if self.cascade_side == "LONG_LIQ" and recent_cvd_delta > 0.5:
                action = "BUY_CAPITULATION"
                self.state = "TRIGGERED"
            elif self.cascade_side == "SHORT_LIQ" and recent_cvd_delta < -0.5:
                action = "SELL_SQUEEZE"
                self.state = "TRIGGERED"
            if (now_ns - self.armed_timestamp_ns) > int(25.0 * 1_000_000_000):
                self.state = "IDLE"

        elif self.state == "TRIGGERED":
            if (now_ns - self.armed_timestamp_ns) > int(30.0 * 1_000_000_000):
                self.state = "IDLE"

        return {
            "state": self.state,
            "side": self.cascade_side,
            "velocity": velocity,
            "long_10s": long_10s,
            "short_10s": short_10s,
            "wick_extreme": self.wick_extreme,
            "action": action,
        }


liquidation_engine = LiquidationEngine()

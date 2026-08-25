"""
LOCAL OHLC AGGREGATOR
Builds 15m (and 1m) candles directly from the raw trade stream.
The XAUUSDT kline websocket stream emits no updates on Binance's TradFi
perps, so bars are aggregated locally from tick data instead.
"""
from typing import List, Optional
from config import L2_RUNG_STEP

BUCKET_15M_SEC = 900
BUCKET_1M_SEC = 60
MAX_HISTORY = 400


class CandleAggregator:
    def __init__(self):
        self.closed: List[List[float]] = []
        self.forming: Optional[List[float]] = None  # [bucket_ts, o, h, l, c, v]

    @staticmethod
    def bucket_start(ts_sec: float, bucket_sec: int = BUCKET_15M_SEC) -> float:
        return int(ts_sec // bucket_sec) * bucket_sec

    def ingest_trade(self, price: float, qty: float, ts_sec: float):
        bucket = self.bucket_start(ts_sec)
        if self.forming is None or self.forming[0] != bucket:
            prev = self.forming
            if prev is not None:
                self.closed.append(prev)
                if len(self.closed) > MAX_HISTORY:
                    self.closed = self.closed[-MAX_HISTORY:]
            carry = prev[4] if prev is not None else (self.closed[-1][4] if self.closed else price)
            # candle opens at last known close for clean continuity
            self.forming = [bucket, carry, carry, carry, carry, 0.0]
        # update forming candle
        self.forming[2] = max(self.forming[2], price)  # high
        self.forming[3] = min(self.forming[3], price)  # low
        self.forming[4] = price                        # close
        self.forming[5] += qty                         # volume

    def seed_history(self, klines: List[List[float]]):
        """Set closed-bar history (REST/bootstrap). Keeps the live forming bar."""
        self.closed = [k[:] for k in klines][-MAX_HISTORY:]

    def series(self) -> List[List[float]]:
        """Closed bars + forming bar (if active) as [ts, o, h, l, c, v]."""
        if self.forming:
            return self.closed + [self.forming]
        return self.closed

"""
XAU/USDT IN-MEMORY REAL-TIME MARKET STATE ENGINE
Tracks tick-level trades, order book, liquidations, and latency telemetry.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Tuple


@dataclass
class MarketState:
    # 1. Ticker & Pricing
    last_price: float = 0.0
    mark_price: float = 0.0
    index_price: float = 0.0
    funding_rate: float = 0.0
    open_interest: float = 0.0
    basis_spread: float = 0.0

    # 2. L2 Depth & Microstructure
    bids: List[Tuple[float, float]] = field(default_factory=list)
    asks: List[Tuple[float, float]] = field(default_factory=list)
    prev_bids: List[Tuple[float, float]] = field(default_factory=list)
    prev_asks: List[Tuple[float, float]] = field(default_factory=list)
    ob_imbalance: float = 0.0
    micro_price: float = 0.0
    ofi: float = 0.0
    spread: float = 0.0

    # 3. Volume Profile ($0.10 Rungs)
    volume_at_price: Dict[float, float] = field(default_factory=lambda: defaultdict(float))
    max_profile_vol: float = 1.0

    # 4. Cumulative Volume Delta (CVD)
    cvd: float = 0.0
    trade_events_5s: deque = field(default_factory=deque)
    recent_cvd_5s: float = 0.0

    # 5. Candlestick Series
    klines_1m: deque = field(default_factory=lambda: deque(maxlen=200))
    klines_15m: List[List[float]] = field(default_factory=list)  # [ts, o, h, l, c, v]
    forming_candle: List[float] = field(default_factory=list)    # live 15m bar
    bootstrap_source: str = "none"

    # 6. Stream health & Latency
    streams_up: Dict[str, bool] = field(default_factory=dict)
    network_latency_ns: int = 0
    render_cycle_latency_ns: int = 0
    msg_count: int = 0
    start_time_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )

    def fifteem_series(self) -> List[List[float]]:
        """Closed 15m bars + the live forming bar appended (if any)."""
        if self.forming_candle:
            return self.klines_15m + [self.forming_candle]
        return self.klines_15m


market_state = MarketState()

#!/usr/bin/env python3
"""Render harness: feed REAL live websocket data into engines, render one frame."""
import asyncio, json, sys, time
import websockets
from rich.console import Console

sys.path.insert(0, ".")
import terminal as T
from config import SYMBOL, WS_BASE, L2_RUNG_STEP
from market_state import market_state
from indicators import QuantitativeEngine
from footprint_engine import footprint_engine
from bootstrap import bootstrap_market_snapshot
from candle_aggregator import CandleAggregator

async def feed(secs=8):
    await bootstrap_market_snapshot(market_state)
    T.candles15m.seed_history(market_state.klines_15m)
    t0 = time.time()
    async with websockets.connect(f"{WS_BASE}/{SYMBOL.lower()}@trade", ping_interval=10) as tws, \
               websockets.connect(f"{WS_BASE}/{SYMBOL.lower()}@depth20@100ms", ping_interval=10) as dws:
        while time.time() - t0 < secs:
            # one trade
            try:
                msg = await asyncio.wait_for(tws.recv(), timeout=2)
                d = json.loads(msg)
                p, q, m, tt = float(d["p"]), float(d["q"]), d["m"], d["T"]
                market_state.last_price = p
                is_buy = not m
                delta = q if is_buy else -q
                market_state.cvd += delta
                rung = round(round(p / L2_RUNG_STEP) * L2_RUNG_STEP, 2)
                market_state.volume_at_price[rung] += q
                footprint_engine.register_trade(p, q, is_buy, tt / 1000.0)
                T.candles15m.ingest_trade(p, q, tt / 1000.0)
                market_state.msg_count += 1
                now_ns = time.time_ns()
                market_state.trade_events_5s.append((now_ns, delta))
                while market_state.trade_events_5s and market_state.trade_events_5s[0][0] < now_ns - int(5e9):
                    market_state.trade_events_5s.popleft()
                market_state.recent_cvd_5s = sum(x[1] for x in market_state.trade_events_5s)
                market_state.streams_up["TRADE"] = True
            except asyncio.TimeoutError:
                pass
            # one depth
            try:
                msg = await asyncio.wait_for(dws.recv(), timeout=2)
                d = json.loads(msg)
                market_state.prev_bids, market_state.prev_asks = market_state.bids, market_state.asks
                market_state.bids = [(float(p0), float(q0)) for p0, q0 in d.get("b", [])]
                market_state.asks = [(float(p0), float(q0)) for p0, q0 in d.get("a", [])]
                if market_state.bids and market_state.asks:
                    market_state.spread = round(market_state.asks[0][0] - market_state.bids[0][0], 2)
                    market_state.micro_price = QuantitativeEngine.calculate_micro_price(market_state.bids, market_state.asks)
                    market_state.ofi = QuantitativeEngine.calculate_ofi(
                        market_state.bids, market_state.asks, market_state.prev_bids, market_state.prev_asks)
                    tb = sum(q for _, q in market_state.bids[:10]); ta = sum(q for _, q in market_state.asks[:10])
                    if tb + ta > 0:
                        market_state.ob_imbalance = ((tb - ta) / (tb + ta)) * 100.0
                market_state.streams_up["DEPTH"] = True
            except asyncio.TimeoutError:
                pass

def render_frame():
    from terminal import render_pro_terminal
    console = Console(force_terminal=True, width=120)
    layout = render_pro_terminal()
    console.print(layout)

asyncio.run(feed(8))
render_frame()
print("\nOK: rendered one frame from real live stream data.")

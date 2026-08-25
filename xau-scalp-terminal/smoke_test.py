#!/usr/bin/env python3
"""
End-to-end smoke test executed against REAL recent XAU/USDT 15m candles
pulled from the official Binance public-data archive (data.binance.vision).
No mocks - this runs the same engines the terminal runs.
"""
import io
import sys
import urllib.request
import zipfile

import numpy as np

from indicators import QuantitativeEngine
from signal_engine_15m import signal_engine_15m
from smart_bracket_engine import SmartBracketEngine
from candle_aggregator import CandleAggregator
from config import SYMBOL, VISION_S3, VISION_BASE


def fetch_vision_15m(days_back=2) -> list:
    """Fetch the newest available daily 15m kline zip for XAUUSDT."""
    import re
    prefix = f"data/futures/um/daily/klines/{SYMBOL}/15m/"
    xml = urllib.request.urlopen(
        urllib.request.Request(f"{VISION_S3}/?prefix={prefix}", headers={"User-Agent": "curl"}),
        timeout=30,
    ).read().decode()
    keys = [k for k in re.findall(r"<Key>([^<]+)</Key>", xml) if k.endswith(".zip")]
    assert keys, "no vision klines found"
    rows = []
    for key in keys[-days_back:]:
        url = f"{VISION_BASE}/{key}"
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "curl"}), timeout=30
        ).read()
        zf = zipfile.ZipFile(io.BytesIO(raw))
        name = zf.namelist()[0]
        for line in zf.read(name).decode().strip().split("\n"):
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                ts = float(parts[0]) / 1000.0
                o, h, l, c, v = (float(parts[1]), float(parts[2]),
                                 float(parts[3]), float(parts[4]), float(parts[5]))
            except (TypeError, ValueError):
                continue  # header
            rows.append([ts, o, h, l, c, v])
    assert len(rows) >= 30, "need at least 30 real bars"
    return rows


def main() -> int:
    print(f"[1] Fetching REAL {SYMBOL} 15m bars from Binance Vision archive...")
    klines = fetch_vision_15m()
    print(f"    -> {len(klines)} bars, last close ${klines[-1][4]:,.2f}")

    closes = np.array([k[4] for k in klines])
    highs = np.array([k[2] for k in klines])
    lows = np.array([k[3] for k in klines])

    atr = QuantitativeEngine.calculate_atr(closes, highs, lows, 14)
    rsi = QuantitativeEngine.calculate_rsi(closes, 14)
    ema20 = QuantitativeEngine.calculate_ema(closes, 20)
    ema50 = QuantitativeEngine.calculate_ema(closes, 50)
    vwap, vu, vl = QuantitativeEngine.calculate_session_vwap(klines)
    print(f"[2] Indicator core on real bars: ATR={atr:.2f} RSI={rsi:.1f} "
          f"EMA20={ema20:.2f} EMA50={ema50:.2f} VWAP={vwap:.2f}")
    assert atr > 0 and 0 <= rsi <= 100 and ema20 > 0 and ema50 > 0 and vwap > 0

    price = closes[-1]
    sig = signal_engine_15m.evaluate_15m_klines(
        klines, current_price=price, cvd_5s=25.0, ob_imbalance=20.0, ofi=3.0
    )
    print(f"[3] Signal engine: direction={sig.direction} score={sig.confluence_score}% "
          f"ideal=${sig.ideal_entry:,.2f} SL=${sig.stop_loss:,.2f}")
    assert sig.direction != "INITIALIZING"
    if "BUY" in sig.direction:
        assert sig.stop_loss < sig.ideal_entry < sig.tp3
        assert sig.tp1 < sig.tp2 < sig.tp3
    elif "SELL" in sig.direction:
        assert sig.tp3 < sig.tp1 < sig.tp2
        assert sig.stop_loss > sig.ideal_entry

    # Bracket lifecycle on the real bars: simulate a BUY and walk prices
    engine = SmartBracketEngine()
    size = engine.calculate_position_size(max(sig.risk_per_ounce, 0.001))
    assert size > 0, "invalid size"
    print(f"[4] Bracket sizing: {size:.3f} XAU for ${sig.risk_per_ounce:.2f}/oz risk")

    if sig.ideal_entry > 0 and (max(sig.ideal_entry - sig.stop_loss, 0.001) > 0.5):
        side = "BUY" if "SELL" not in sig.direction else "SELL"
        engine.open_position(side, sig.ideal_entry, size, atr, sig.stop_loss,
                             sig.tp1, sig.tp2, sig.tp3)
        # replay last 40 real closes through the bracket tick engine
        closes_iter = closes[-40:]
        for p in closes_iter:
            engine.update_market_price(float(p), atr)
        print(f"    after replay: active={engine.position.is_active} "
              f"realized=${engine.position.realized_pnl:+,.2f} "
              f"unrealized=${engine.position.unrealized_pnl:+,.2f}")

    # Candle aggregator ingesting replays of real OHLC as if ticks
    agg = CandleAggregator()
    for k in klines[-50:]:
        ts, o, h, l, c, v = k
        for price in (o, h, l, c):
            qty = max(v / 4.0, 0.001)
            agg.ingest_trade(price, qty, ts)
    series = agg.series()
    print(f"[5] Candle aggregator replay: {len(agg.closed)} closed + "
          f"forming={'yes' if agg.forming else 'no'}; series len {len(series)}")
    assert series and len(series) >= 2

    print("\nALL SMOKE TESTS PASSED - engines operational on real XAU data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

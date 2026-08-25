# XAU/USDT 15M Scalp Terminal

Bloomberg-style 15-minute scalp terminal for the **Binance USDⓈ-M Gold Perpetual `XAUUSDT`** (real gold perpetual — not PAXG).

All data is live and real, pulled from **free public Binance endpoints** — no API keys required, no dummy data:

- **Trade ticks** → `wss://fstream.binance.com/ws/xauusdt@trade` (CVD, footprint, local 15m OHLC aggregation)
- **L2 depth** → `wss://fstream.binance.com/ws/xauusdt@depth20@100ms` (micro price, OFI, imbalance, spread)
- **Mark price / funding** → `.../xauusdt@markPrice@1s` + `/fapi/v1/premiumIndex`
- **Liquidations** → `wss://fstream.binance.com/ws/xauusdt@forceOrder` (cascade velocity engine)
- **15m history bootstrap** → `/fapi/v1/klines` (primary) with **Binance Vision CDN** fallback if your region blocks `fapi.binance.com` REST

## Features

- 15m SMC radar: EMA stack, session VWAP bands, RSI momentum, BOS/CHoCH, Fair Value Gaps with Consequent Encroachment 50% ideal entry, Order Blocks
- Entry / Ideal Entry / Stop Loss / TP1 / TP2 / TP3 with 1.5R (50% + breakeven), 2.5R (30% + lock), 4R runner (Chandelier ATR trailing)
- Fixed-fractional sizing (1% equity-risk/ounce) auto-computed live
- Liquidation cascade detector (arm/exhaustion/trigger with velocity decay)
- Footprint delta divergence & trapped-side exhaustion alerts
- Interactive hotkeys in a `rich` Live TUI

## Quick start

```bash
pip install -r requirements.txt
python3 terminal.py
```

Hotkeys: `[B]` buy market · `[S]` sell market · `[I]` buy ideal limit · `[K]` sell ideal limit · `[F]` flatten · `[T]` toggle trailing · `[Q]` quit

`smoke_test.py` validates indicator math, the 15m signal engine and bracket lifecycle against **real** recent Binance 15m candles fetched from the Binance Vision public archive (no mocks).

```bash
python3 smoke_test.py
```

## Files

| File | Purpose |
| --- | --- |
| `terminal.py` | main event loop, streams, TUI, hotkeys |
| `bootstrap.py` | fapi REST primary + Vision CDN fallback bootstrap |
| `candle_aggregator.py` | local 15m OHLC from raw trade ticks |
| `signal_engine_15m.py` | 15m SMC confluence radar |
| `smart_bracket_engine.py` | position lifecycle, TP scaling, BE, trailing |
| `liquidation_engine.py` | forced-liquidation cascade FSM |
| `footprint_engine.py` | footprint divergence / exhaustion alerts |
| `indicators.py` | ATR / RSI / EMA / VWAP / micro price / OFI |
| `market_state.py` | in-memory shared state |
| `config.py` | risk, sizing, fees, killzones |
| `live_check.py` | live stream + render harness for headless verification |
| `smoke_test.py` | offline engine math on real Vision bars |

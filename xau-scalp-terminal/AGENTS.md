# Repo Notes: XAU/USDT 15M Scalp Terminal

## What this is
Bloomberg-style scalp terminal for Binance USD-M Gold Perm `XAUUSDT` (gold perp, NOT PAXG).

## Environment quirks discovered (2026-08-25)
- `fapi.binance.com` REST returns geo-block error from this sandbox; resolve via fallback bootstrap from Binance Vision S3 (data/futures/um/daily/klines/...).
- `wss://fstream.binance.com` IS reachable. Of stream types: `xauusdt@depth20@100ms`, `xauusdt@trade`, `xauusdt@bookTicker` work; `aggTrade`, `kline_15m/1m`, `miniTicker`, `markPrice@1s`, `forceOrder` return zero messages here (they work on user regions / when activity exists).
- Terminal builds 15m OHLC locally from raw `trade` stream — don't rely on `@kline` for this symbol.
- Raw trade message fields (`p`,`q`,`m`,`T`,`E`) are identical to `aggTrade` ones.

## Run commands
- Install: `pip install -r requirements.txt`
- Terminal: `python3 terminal.py` (interactive TTY needed for hotkeys)
- Web access: `bash serve.sh` -> serves via ttyd on ports 12000/12001 (work hosts)
- Verification: `python3 smoke_test.py` (uses real Binance Vision 15m bars; no mocks)

## Web serving notes (2026-08-25)
- ttyd binary lives in `bin/ttyd` (NOT /tmp — /tmp and ~/.local get wiped between sandbox sessions).
- `serve.sh` self-heals: re-downloads ttyd if missing and re-installs pip deps if imports fail.
- Rich Live must use `auto_refresh=False` under ttyd; main loop drives updates at 20fps.
- Set XAU_STATE_FILE=/path/state.json for a 2s engine-health dump (streams, price, msgs).

## Design decisions
- Every engine is a single shared singleton importable from module scope.
- Signal engine consumes closed-form of `CandleAggregator` + forming bar.
- Bracket engine updates on each trade tick with last-render ATR (global `last_atr`).
- Bootstrap: fapi REST klines → if geo-blocked → Binance Vision latest 2 daily zips → else live aggregation only.
- No dummy data anywhere; Vision fallback is official Binance archive (S3 host `s3-ap-northeast-1.amazonaws.com/data.binance.vision`).

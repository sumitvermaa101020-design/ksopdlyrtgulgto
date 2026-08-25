#!/usr/bin/env python3
"""
XAU/USDT 15M SCALP TERMINAL - MASTER EXECUTION ENGINE
Run: python3 terminal.py
Deps: pip install rich websockets aiohttp numpy
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

import aiohttp
import numpy as np
import websockets
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import (
    REST_BASE, WS_BASE, SYMBOL, L2_RUNG_STEP,
    EQUITY_USD, RISK_PER_TRADE_PCT,
)
from market_state import market_state
from indicators import QuantitativeEngine
from liquidation_engine import liquidation_engine
from footprint_engine import footprint_engine
from signal_engine_15m import signal_engine_15m
from smart_bracket_engine import bracket_engine
from candle_aggregator import CandleAggregator
from bootstrap import bootstrap_market_snapshot

candles15m = CandleAggregator()
quit_event = asyncio.Event()
last_atr = 2.50


# ==========================================
# STREAM HEALTH
# ==========================================
def _mark(stream: str, up: bool):
    market_state.streams_up[stream] = up


# ==========================================
# WEBSOCKET HANDLERS
# ==========================================
async def ws_trade_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@trade"
    while not quit_event.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                _mark("TRADE", True)
                async for msg in ws:
                    recv_ns = time.time_ns()
                    data = json.loads(msg)
                    price = float(data["p"])
                    qty = float(data["q"])
                    is_buyer_maker = data["m"]
                    market_state.msg_count += 1
                    market_state.network_latency_ns = max(0, recv_ns - (data["E"] * 1_000_000))
                    market_state.last_price = price

                    is_buy = not is_buyer_maker
                    delta = qty if is_buy else -qty
                    market_state.cvd += delta

                    rung = round(round(price / L2_RUNG_STEP) * L2_RUNG_STEP, 2)
                    market_state.volume_at_price[rung] += qty
                    if market_state.volume_at_price[rung] > market_state.max_profile_vol:
                        market_state.max_profile_vol = market_state.volume_at_price[rung]

                    footprint_engine.register_trade(price, qty, is_buy, data["T"] / 1000.0)

                    now_ns = recv_ns
                    market_state.trade_events_5s.append((now_ns, delta))
                    cutoff_ns = now_ns - int(5.0 * 1_000_000_000)
                    while market_state.trade_events_5s and market_state.trade_events_5s[0][0] < cutoff_ns:
                        market_state.trade_events_5s.popleft()
                    market_state.recent_cvd_5s = sum(t[1] for t in market_state.trade_events_5s)

                    # Feed candle aggregator; scalp bracket watches price too
                    candles15m.ingest_trade(price, qty, data["T"] / 1000.0)
                    bracket_engine.update_market_price(price, last_atr)
        except Exception:
            _mark("TRADE", False)
            if not quit_event.is_set():
                await asyncio.sleep(0.7)


async def ws_depth_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@depth20@100ms"
    while not quit_event.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                _mark("DEPTH", True)
                async for msg in ws:
                    data = json.loads(msg)
                    market_state.prev_bids = market_state.bids
                    market_state.prev_asks = market_state.asks
                    market_state.bids = [(float(p), float(q)) for p, q in data.get("b", [])]
                    market_state.asks = [(float(p), float(q)) for p, q in data.get("a", [])]

                    if market_state.bids and market_state.asks:
                        market_state.spread = round(
                            market_state.asks[0][0] - market_state.bids[0][0], 2
                        )
                        market_state.micro_price = QuantitativeEngine.calculate_micro_price(
                            market_state.bids, market_state.asks
                        )
                        market_state.ofi = QuantitativeEngine.calculate_ofi(
                            market_state.bids, market_state.asks,
                            market_state.prev_bids, market_state.prev_asks,
                        )
                        top10_b = sum(q for _, q in market_state.bids[:10])
                        top10_a = sum(q for _, q in market_state.asks[:10])
                        if top10_b + top10_a > 0:
                            market_state.ob_imbalance = (
                                (top10_b - top10_a) / (top10_b + top10_a)
                            ) * 100.0
        except Exception:
            _mark("DEPTH", False)
            if not quit_event.is_set():
                await asyncio.sleep(0.7)


async def ws_mark_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@markPrice@1s"
    while not quit_event.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                _mark("MARK", True)
                async for msg in ws:
                    data = json.loads(msg)
                    market_state.mark_price = float(data.get("p", 0.0) or 0.0)
                    market_state.index_price = float(data.get("i", 0.0) or 0.0)
                    market_state.funding_rate = float(data.get("r", 0.0) or 0.0) * 100.0
                    if market_state.mark_price and market_state.index_price:
                        market_state.basis_spread = market_state.mark_price - market_state.index_price
        except Exception:
            _mark("MARK", False)
            if not quit_event.is_set():
                await asyncio.sleep(1.0)


async def ws_force_order_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@forceOrder"
    while not quit_event.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                _mark("FORCE", True)
                async for msg in ws:
                    data = json.loads(msg)
                    o = data.get("o", {})
                    side = o.get("S", "")
                    try:
                        qty = float(o.get("q", 0.0))
                        price = float(o.get("p", 0.0))
                    except (TypeError, ValueError):
                        continue
                    if side:
                        liquidation_engine.register_event(side, qty, price)
        except Exception:
            _mark("FORCE", False)
            if not quit_event.is_set():
                await asyncio.sleep(1.2)


# ==========================================
# SIGNAL SNAPSHOT
# ==========================================
def _current_signal():
    series = candles15m.series()
    if not series:
        series = market_state.fifteem_series()
    return signal_engine_15m.evaluate_15m_klines(
        series, market_state.last_price,
        market_state.recent_cvd_5s, market_state.ob_imbalance, market_state.ofi,
    )


def _current_atr() -> float:
    series = candles15m.series() or market_state.fifteem_series()
    if len(series) < 15:
        return 2.50
    highs = np.array([k[2] for k in series])
    lows = np.array([k[3] for k in series])
    closes = np.array([k[4] for k in series])
    return QuantitativeEngine.calculate_atr(closes, highs, lows, 14)


# ==========================================
# RICH TUI RENDER
# ==========================================
def render_pro_terminal() -> Layout:
    global last_atr
    t_start_ns = time.perf_counter_ns()
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["main"].split_row(
        Layout(name="left_dom", ratio=2),
        Layout(name="center_signal", ratio=3),
        Layout(name="right_exec", ratio=2),
    )

    pos = bracket_engine.position
    sig = _current_signal()
    liq = liquidation_engine.update(market_state.last_price, market_state.recent_cvd_5s / max(abs(market_state.recent_cvd_5s), 1.0) if market_state.recent_cvd_5s else 0.0)
    last_atr = _current_atr()

    pos_style = "bold green" if pos.side == "BUY" else "bold red" if pos.side == "SELL" else "dim yellow"
    pos_txt = (
        f"POS: [{pos_style}]{pos.side} {pos.size_remaining:.3f}oz @ ${pos.entry_price:,.2f}[/{pos_style}] "
        f"(uPnL: {pos.unrealized_pnl:+,.2f})"
        if pos.is_active
        else "POS: FLAT (IDLE)"
    )

    streams_state = " ".join(
        f"{name}:{ 'UP' if ok else 'DOWN' }" for name, ok in market_state.streams_up.items()
    )

    # 1. Header
    header_text = (
        f" XAU/USDT INSTITUTIONAL 15M SCALP TERMINAL | UTC: {datetime.now(timezone.utc).strftime('%H:%M:%S')} | "
        f"LAST: ${market_state.last_price:,.2f} | LAT: {market_state.network_latency_ns/1000:,.0f}s | "
        f"FR: {market_state.funding_rate:+.4f}% | BOOT: {market_state.bootstrap_source} | {pos_txt}"
    )
    layout["header"].update(Panel(Text(header_text, style="bold black on gold1"), style="gold1"))

    # 2. Dynamic L2 DOM Ladder
    dom_table = Table(expand=True, box=None, padding=(0, 0))
    dom_table.add_column("Ord", justify="center", style="bold yellow", width=3)
    dom_table.add_column("Bid", justify="right", style="green", width=7)
    dom_table.add_column("Price", justify="center", style="bold", width=9)
    dom_table.add_column("Ask", justify="left", style="red", width=7)
    dom_table.add_column("Profile", justify="left", style="cyan", width=11)

    if market_state.last_price > 0:
        center_p = round(round(market_state.last_price / L2_RUNG_STEP) * L2_RUNG_STEP, 2)
    else:
        center_p = (market_state.bids[0][0] + market_state.asks[0][0]) / 2 if market_state.bids and market_state.asks else 0.0
    b_dict = {round(p, 2): q for p, q in market_state.bids}
    a_dict = {round(p, 2): q for p, q in market_state.asks}

    if center_p > 0:
        for r in [round(center_p + (i * L2_RUNG_STEP), 2) for i in range(6, -7, -1)]:
            ord_m = ""
            if pos.is_active:
                if abs(r - pos.entry_price) < 0.05:
                    ord_m = "ENT"
                elif abs(r - pos.current_sl) < 0.05:
                    ord_m = "SL "
            bq = f"{b_dict[r]:.2f}" if r in b_dict else ""
            aq = f"{a_dict[r]:.2f}" if r in a_dict else ""
            vol = market_state.volume_at_price.get(r, 0.0)
            bar = "█" * int((vol / market_state.max_profile_vol) * 8) + f" {vol:.1f}" if vol > 0 else ""
            p_style = "bold white on blue" if abs(r - center_p) < 0.05 else "bold white"
            dom_table.add_row(ord_m, bq, f"[{p_style}]${r:,.2f}[/{p_style}]", aq, bar)

    micro_note = (
        f" micro ${market_state.micro_price:,.2f} | spr ${market_state.spread:.2f} | "
        f"imb {market_state.ob_imbalance:+.1f}% | OFI {market_state.ofi:+.2f}"
    )
    layout["left_dom"].update(
        Panel(dom_table, title=f"[bold gold1]L2 DOM LADDER[/bold gold1]", subtitle=micro_note, border_style="gold1")
    )

    # 3. 15M Scalp Signal Radar
    sig_col = "green" if "BUY" in sig.direction else "red" if "SELL" in sig.direction else "yellow"
    sig_table = Table(expand=True, box=None, padding=(0, 1))
    sig_table.add_column("15M Metric", style="bold white", width=18)
    sig_table.add_column("Value / Level", justify="left")

    sig_table.add_row("Action", f"[bold {sig_col}]{sig.direction}[/bold {sig_col}] ({sig.confluence_score}%)")
    sig_table.add_row("Market Price", f"${sig.market_entry:,.2f}")
    sig_table.add_row("IDEAL ENTRY", f"[bold white on blue] ${sig.ideal_entry:,.2f} [/bold white on blue]")
    sig_table.add_row("STOP LOSS", f"[bold white on red] ${sig.stop_loss:,.2f} [/bold white on red]")
    sig_table.add_row("TARGET 1", f"[bold green]${sig.tp1:,.2f}[/bold green] (1.5R - 50% + BE)")
    sig_table.add_row("TARGET 2", f"[bold green]${sig.tp2:,.2f}[/bold green] (2.5R - 30% + Lock)")
    sig_table.add_row("TARGET 3", f"[bold bright_green]${sig.tp3:,.2f}[/bold bright_green] (4.0R - Runner)")
    sig_table.add_row("Risk / Reward", f"[bold gold1]1 : {sig.risk_reward_ratio:.2f}[/bold gold1]")
    sig_table.add_row("Session Zone", f"[cyan]{sig.session_killzone}[/cyan]")
    sig_table.add_row("Structure", f"[white]{sig.structure_status}[/white]")
    sig_table.add_row("FVG Imbalance", f"[magenta]{sig.fvg_zone}[/magenta]")
    sig_table.add_row("Order Block", f"[magenta]{sig.order_block_zone}[/magenta]")
    sig_table.add_row("Confluences", "\n".join([f"• {r}" for r in sig.confluence_reasons[:3]]))
    layout["center_signal"].update(
        Panel(sig_table, title=f"[bold {sig_col}]15M SCALP RADAR[/bold {sig_col}]", border_style=sig_col)
    )

    # 4. Right Exec Panels
    r_split = Layout()
    r_split.split_column(Layout(name="brk"), Layout(name="sz"), Layout(name="flow"))

    brk_t = Table(expand=True, box=None, padding=(0, 1))
    brk_t.add_column("Param", style="bold")
    brk_t.add_column("Status", justify="right")
    if pos.is_active:
        brk_t.add_row("Position", f"{pos.side} {pos.size_remaining:.3f}oz")
        brk_t.add_row("Trailing SL", f"[bold red]${pos.current_sl:,.2f}[/bold red]")
        be_style = "bold green" if pos.is_breakeven_triggered else "bold yellow"
        brk_t.add_row("Breakeven", f"[{be_style}]{'ACTIVE' if pos.is_breakeven_triggered else 'PENDING'}[/{be_style}]")
        pnl_style = "green" if pos.realized_pnl >= 0 else "red"
        brk_t.add_row("Realized PnL", f"[bold {pnl_style}]${pos.realized_pnl:+,.2f}[/bold {pnl_style}]")
        upnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
        brk_t.add_row("Unrealized PnL", f"[bold {upnl_style}]${pos.unrealized_pnl:+,.2f}[/bold {upnl_style}]")
    else:
        brk_t.add_row("Bracket", "[dim yellow]IDLE / AWAITING ORDER[/dim yellow]")
        pnl_style = "green" if pos.realized_pnl >= 0 else "red"
        brk_t.add_row("Realized PnL", f"[bold {pnl_style}]${pos.realized_pnl:+,.2f}[/bold {pnl_style}]")
    r_split["brk"].update(Panel(brk_t, title="[bold magenta]SMART BRACKET[/bold magenta]", border_style="magenta"))

    sz_t = Table(expand=True, box=None, padding=(0, 1))
    sz_t.add_column("Param", style="bold")
    sz_t.add_column("Val", justify="right")
    planned_sz = bracket_engine.calculate_position_size(sig.risk_per_ounce) if sig.risk_per_ounce > 0 else 0.0
    sz_t.add_row("Planned Size", f"[bold gold1]{planned_sz:.3f} XAU[/bold gold1]")
    tp1_yield = (planned_sz * 0.5) * abs(sig.tp1 - sig.ideal_entry) if sig.ideal_entry else 0
    tp2_yield = (planned_sz * 0.3) * abs(sig.tp2 - sig.ideal_entry) if sig.ideal_entry else 0
    sz_t.add_row("TP1 Yield", f"[green]+${tp1_yield:,.2f}[/green]")
    sz_t.add_row("TP2 Yield", f"[green]+${tp2_yield:,.2f}[/green]")
    sz_t.add_row("5s CVD Flow", f"{market_state.recent_cvd_5s:+.2f} oz")
    sz_t.add_row("Spread", f"${market_state.spread:.2f}")
    sz_t.add_row("ATR(14)", f"${last_atr:.2f}")
    r_split["sz"].update(Panel(sz_t, title="[bold cyan]POSITION SIZING[/bold cyan]", border_style="cyan"))

    # Flow / alerts panel
    flow_t = Table(expand=True, box=None, padding=(0, 1))
    flow_t.add_column("Flow", style="bold")
    flow_t.add_column("Data", justify="left")
    div_alert, exh_alert = footprint_engine.active_alerts()
    flow_t.add_row("Liq State", f"{liq['state']} v=${liq['velocity']:,.0f}/s")
    flow_t.add_row("Footprint", div_alert or exh_alert or "Scanning delta imbalance...")
    flow_t.add_row("Streams", streams_state or "connecting...")
    r_split["flow"].update(Panel(flow_t, title="[bold yellow]ORDER FLOW[/bold yellow]", border_style="yellow"))

    layout["right_exec"].update(r_split)

    # 5. Footer
    layout["footer"].update(
        Panel(
            Text("[B] BUY MKT | [S] SELL MKT | [I] BUY IDEAL | [K] SELL IDEAL | [F] FLATTEN | [T] TRAIL TOGGLE | [Q] QUIT",
                 style="bold black on bright_cyan"),
            style="bright_cyan",
        )
    )
    market_state.render_cycle_latency_ns = time.perf_counter_ns() - t_start_ns
    return layout


# ==========================================
# KEYBOARD HOTKEYS
# ==========================================
async def keyboard_hotkey_listener():
    loop = asyncio.get_event_loop()
    try:
        if not sys.stdin.isatty():
            return  # headless: skip keyboard
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
        )
    except Exception:
        return
    while not quit_event.is_set():
        try:
            data = await reader.read(1)
            if not data:
                await asyncio.sleep(0.05)
                continue
            c = data.decode("utf-8", errors="ignore").lower()
        except Exception:
            await asyncio.sleep(0.05)
            continue

        sig = _current_signal()
        atr = _current_atr()
        size = bracket_engine.calculate_position_size(max(sig.risk_per_ounce, 0.001))

        if c == "b":
            bracket_engine.open_position("BUY", market_state.last_price, size, atr,
                                         sig.stop_loss, sig.tp1, sig.tp2, sig.tp3)
        elif c == "s":
            bracket_engine.open_position("SELL", market_state.last_price, size, atr,
                                         sig.stop_loss, sig.tp1, sig.tp2, sig.tp3)
        elif c == "i" and sig.ideal_entry > 0:
            bracket_engine.open_position("BUY", sig.ideal_entry, size, atr,
                                         sig.stop_loss, sig.tp1, sig.tp2, sig.tp3)
        elif c == "k" and sig.ideal_entry > 0:
            bracket_engine.open_position("SELL", sig.ideal_entry, size, atr,
                                         sig.stop_loss, sig.tp1, sig.tp2, sig.tp3)
        elif c == "f":
            bracket_engine.flatten_position(market_state.last_price)
        elif c == "t":
            pos = bracket_engine.position
            pos.is_trailing_active = not pos.is_trailing_active
        elif c == "q":
            quit_event.set()


async def _state_dumper(path: str):
    """Diagnostics: dump engine state to a file every 2s (set XAU_STATE_FILE)."""
    while not quit_event.is_set():
        try:
            with open(path, "w") as f:
                json.dump({
                    "streams": market_state.streams_up,
                    "last_price": market_state.last_price,
                    "spread": market_state.spread,
                    "bids": len(market_state.bids),
                    "cvd_5s": market_state.recent_cvd_5s,
                    "msgs": market_state.msg_count,
                    "klines_15m": len(candles15m.series()),
                    "render_us": market_state.render_cycle_latency_ns / 1000,
                }, f)
        except Exception:
            pass
        await asyncio.sleep(2.0)


# ==========================================
# MAIN EVENT LOOP
# ==========================================
async def main():
    console = Console()
    console.print("[bold gold1]Starting XAU/USDT 15M Scalp Terminal on Binance Futures...[/bold gold1]")
    src = await bootstrap_market_snapshot(market_state)
    if market_state.bootstrap_source == "fapi-rest":
        console.print("[green]Bootstrap: fapi REST klines loaded (%d bars)[/green]" % len(market_state.klines_15m))
    elif market_state.bootstrap_source == "binance-vision":
        console.print("[green]Bootstrap: Binance Vision klines loaded (%d bars, fapi REST geo-blocked)[/green]" % len(market_state.klines_15m))
    else:
        console.print("[yellow]Bootstrap: no history available yet; building bars live.[/yellow]")
    if market_state.klines_15m:
        candles15m.seed_history(market_state.klines_15m)

    tasks = [
        asyncio.create_task(ws_trade_stream()),
        asyncio.create_task(ws_depth_stream()),
        asyncio.create_task(ws_mark_stream()),
        asyncio.create_task(ws_force_order_stream()),
        asyncio.create_task(keyboard_hotkey_listener()),
    ]
    if os.getenv("XAU_STATE_FILE"):
        tasks.append(asyncio.create_task(_state_dumper(os.getenv("XAU_STATE_FILE"))))

    use_screen = sys.stdout.isatty()
    # auto_refresh=False: the main loop drives live.update() itself; avoids a
    # background refresh thread racing pty resize signals under web terminals.
    with Live(render_pro_terminal(), console=console, auto_refresh=False, screen=use_screen) as live:
        while not quit_event.is_set():
            live.update(render_pro_terminal())
            await asyncio.sleep(0.05)

    for t in tasks:
        t.cancel()
    console.print("[bold gold1]Terminal closed cleanly.[/bold gold1]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)

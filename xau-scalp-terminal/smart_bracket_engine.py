"""
AUTONOMOUS POSITION LIFECYCLE & RISK EXECUTION ENGINE
Handles fixed fractional sizing, TP1/TP2/TP3 scale-outs, BE migration, and trailing SL.
"""
from dataclasses import dataclass
from typing import Optional
from config import (
    EQUITY_USD, RISK_PER_TRADE_PCT, SYMBOL,
    TP1_SCALE_PCT, TP2_SCALE_PCT, FEE_SLIPPAGE_BUFFER_USD,
)


@dataclass
class PositionBracket:
    symbol: str = SYMBOL
    side: Optional[str] = None
    entry_price: float = 0.0
    size_total: float = 0.0
    size_remaining: float = 0.0
    initial_sl: float = 0.0
    current_sl: float = 0.0
    tp1: float = 0.0
    tp1_filled: bool = False
    tp2: float = 0.0
    tp2_filled: bool = False
    tp3_runner: float = 0.0
    is_trailing_active: bool = True
    is_breakeven_triggered: bool = False
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    highest_price_reached: float = 0.0
    lowest_price_reached: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.size_remaining > 0.0001


class SmartBracketEngine:
    def __init__(self):
        self.position = PositionBracket()

    def calculate_position_size(self, risk_per_ounce: float) -> float:
        risk_usd = EQUITY_USD * RISK_PER_TRADE_PCT
        if risk_per_ounce <= 0:
            return 1.0
        size_oz = risk_usd / risk_per_ounce
        return max(round(size_oz, 3), 0.001)

    def open_position(self, side: str, price: float, size: float, atr: float,
                      sl: float, tp1: float, tp2: float, tp3: float):
        if self.position.is_active:
            self.flatten_position(price)
        self.position = PositionBracket(
            symbol=SYMBOL,
            side=side,
            entry_price=price,
            size_total=size,
            size_remaining=size,
            initial_sl=sl,
            current_sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3_runner=tp3,
            highest_price_reached=price,
            lowest_price_reached=price,
        )

    def update_market_price(self, current_price: float, atr: float):
        if not self.position.is_active:
            return
        pos = self.position
        atr_val = max(atr, 1.50)

        if pos.side == "BUY":
            pos.unrealized_pnl = (current_price - pos.entry_price) * pos.size_remaining
            pos.highest_price_reached = max(pos.highest_price_reached, current_price)

            # TP1: 50% scale-out + Move SL to Breakeven (+fees)
            if not pos.tp1_filled and current_price >= pos.tp1:
                tp_qty = round(pos.size_total * TP1_SCALE_PCT, 3)
                pos.realized_pnl += (pos.tp1 - pos.entry_price) * tp_qty
                pos.size_remaining -= tp_qty
                pos.tp1_filled = True
                pos.current_sl = max(pos.current_sl, pos.entry_price + FEE_SLIPPAGE_BUFFER_USD)
                pos.is_breakeven_triggered = True

            # TP2: 30% scale-out + Lock SL at TP1
            if not pos.tp2_filled and current_price >= pos.tp2:
                tp_qty = min(round(pos.size_total * TP2_SCALE_PCT, 3), pos.size_remaining)
                pos.realized_pnl += (pos.tp2 - pos.entry_price) * tp_qty
                pos.size_remaining -= tp_qty
                pos.tp2_filled = True
                pos.current_sl = max(pos.current_sl, pos.tp1)

            # TP3 / Runner: Chandelier ATR Trailing Stop
            if pos.is_trailing_active and (pos.tp1_filled or current_price > pos.entry_price + (1.2 * atr_val)):
                trailing_level = current_price - (1.2 * atr_val)
                if trailing_level > pos.current_sl:
                    pos.current_sl = trailing_level

            # Stop Loss Triggered
            if current_price <= pos.current_sl:
                pos.realized_pnl += (pos.current_sl - pos.entry_price) * pos.size_remaining
                pos.unrealized_pnl = 0.0
                pos.size_remaining = 0.0

        elif pos.side == "SELL":
            pos.unrealized_pnl = (pos.entry_price - current_price) * pos.size_remaining
            pos.lowest_price_reached = min(pos.lowest_price_reached, current_price)

            # TP1: 50% scale-out + Move SL to Breakeven (-fees)
            if not pos.tp1_filled and current_price <= pos.tp1:
                tp_qty = round(pos.size_total * TP1_SCALE_PCT, 3)
                pos.realized_pnl += (pos.entry_price - pos.tp1) * tp_qty
                pos.size_remaining -= tp_qty
                pos.tp1_filled = True
                pos.current_sl = min(pos.current_sl, pos.entry_price - FEE_SLIPPAGE_BUFFER_USD)
                pos.is_breakeven_triggered = True

            # TP2: 30% scale-out + Lock SL at TP1
            if not pos.tp2_filled and current_price <= pos.tp2:
                tp_qty = min(round(pos.size_total * TP2_SCALE_PCT, 3), pos.size_remaining)
                pos.realized_pnl += (pos.entry_price - pos.tp2) * tp_qty
                pos.size_remaining -= tp_qty
                pos.tp2_filled = True
                pos.current_sl = min(pos.current_sl, pos.tp1)

            # TP3 / Runner: Chandelier ATR Trailing Stop
            if pos.is_trailing_active and (pos.tp1_filled or current_price < pos.entry_price - (1.2 * atr_val)):
                trailing_level = current_price + (1.2 * atr_val)
                if trailing_level < pos.current_sl:
                    pos.current_sl = trailing_level

            # Stop Loss Triggered
            if current_price >= pos.current_sl:
                pos.realized_pnl += (pos.entry_price - pos.current_sl) * pos.size_remaining
                pos.unrealized_pnl = 0.0
                pos.size_remaining = 0.0

    def flatten_position(self, current_price: float):
        if not self.position.is_active:
            return
        pnl = (
            (current_price - self.position.entry_price)
            if self.position.side == "BUY"
            else (self.position.entry_price - current_price)
        ) * self.position.size_remaining
        self.position.realized_pnl += pnl
        self.position.unrealized_pnl = 0.0
        self.position.size_remaining = 0.0


bracket_engine = SmartBracketEngine()

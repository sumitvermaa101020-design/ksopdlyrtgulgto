"""
XAU/USDT 15M SCALP TERMINAL - MASTER CONFIGURATION
Asset: Gold Perpetual Contract (XAU/USDT) - Binance USD(S)-M Futures
"""
import os

# ==========================================
# 1. NETWORK & EXCHANGE SPECIFICATIONS
# ==========================================
SYMBOL = "XAUUSDT"
BASE_ASSET = "XAU"  # Gold (price of 1 Troy Oz tracked per contract specs)
SETTLEMENT_ASSET = "USDT"
TICK_SIZE = 0.01
LOT_SIZE = 0.001
PRICE_DECIMALS = 2
QTY_DECIMALS = 3

REST_BASE = "https://fapi.binance.com"
WS_BASE = "wss://fstream.binance.com/ws"

# Official Binance public-data CDN fallback (data.binance.vision).
# Used only when the fapi REST endpoint is geo-blocked from the host region.
VISION_BASE = "https://data.binance.vision"
VISION_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ==========================================
# 2. RISK & CAPITAL GOVERNANCE
# ==========================================
EQUITY_USD = 10_000.0
RISK_PER_TRADE_PCT = 0.01
MAX_LEVERAGE = 20
DAILY_MAX_DRAWDOWN_PCT = 0.03
MAX_CONSECUTIVE_LOSSES = 3
STAGNATION_MAX_BARS_15M = 6

MIN_SL_DISTANCE_USD = 1.50
MAX_SL_DISTANCE_USD = 6.00
ATR_SL_MULTIPLIER = 1.5
FEE_SLIPPAGE_BUFFER_USD = 0.15

# ==========================================
# 3. PROFIT TARGET SCALE-OUT MATRIX
# ==========================================
TP1_RR_RATIO = 1.5
TP2_RR_RATIO = 2.5
TP3_RR_RATIO = 4.0

TP1_SCALE_PCT = 0.50
TP2_SCALE_PCT = 0.30
TP3_RUNNER_PCT = 0.20

# ==========================================
# 4. ORDER FLOW & MICROSTRUCTURE THRESHOLDS
# ==========================================
L2_RUNG_STEP = 0.10
OFI_LEVELS = 5
IMBALANCE_RATIO_TRIGGER = 3.0
CASCADE_THRESHOLD_USD = 250_000
VELOCITY_THRESHOLD_USD_S = 25_000
MAX_SPREAD_FILTER_USD = 0.15

# ==========================================
# 5. SESSION KILLZONE HOURS (UTC)
# ==========================================
KILLZONES = {
    "ASIA": (0, 7),
    "FRANKFURT_BURST": (6, 7),
    "LONDON_OPEN": (7, 10),
    "NY_COMEX_OPEN": (12, 16),
    "LONDON_FIX": (15, 17),
}

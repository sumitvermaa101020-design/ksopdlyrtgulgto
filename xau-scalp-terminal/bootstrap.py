"""
BOOTSTRAP STRATEGY
Primary: Binance USD-M fapi REST (klines, open interest, premium index).
Fallback: Binance Vision public-data CDN (official archive of fapi kline
            CSVs) covering the same market - used when fapi REST is
            geo-blocked from the running region.
"""
import io
import re
import zipfile
from typing import List, Optional, Tuple

import aiohttp

from config import REST_BASE, VISION_BASE, VISION_S3, SYMBOL


LISTING_RE = re.compile(r"<Key>([^<]+)</Key>")


async def _fetch_rest_klines(session: aiohttp.ClientSession, limit: int = 100) -> Optional[List[List[float]]]:
    url = f"{REST_BASE}/fapi/v1/klines?symbol={SYMBOL}&interval=15m&limit={limit}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            raw = await resp.json(content_type=None)
            if not isinstance(raw, list) or not raw:
                return None
            out = []
            for k in raw:
                try:
                    out.append([float(k[0]) / 1000.0, float(k[1]), float(k[2]),
                                float(k[3]), float(k[4]), float(k[5])])
                except (TypeError, ValueError, IndexError):
                    continue
            return out or None
    except Exception:
        return None


async def _fetch_rest_open_interest(session: aiohttp.ClientSession) -> Optional[float]:
    url = f"{REST_BASE}/fapi/v1/openInterest?symbol={SYMBOL}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            return float(data.get("openInterest", 0.0))
    except Exception:
        return None


async def _fetch_rest_premium_index(session: aiohttp.ClientSession) -> Optional[Tuple[float, float, float]]:
    """Returns (funding_rate_pct, mark_price, index_price)"""
    url = f"{REST_BASE}/fapi/v1/premiumIndex?symbol={SYMBOL}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            fr = float(data.get("lastFundingRate", 0.0)) * 100.0
            mark = float(data.get("markPrice", 0.0))
            index = float(data.get("indexPrice", 0.0))
            return fr, mark, index
    except Exception:
        return None


def _vision_list(session: aiohttp.ClientSession, prefix: str):
    """Synchronous-ish helper returning list request; caller awaits."""
    url = f"{VISION_S3}/?prefix={prefix}"
    return session.get(url, timeout=aiohttp.ClientTimeout(total=20))


async def _fetch_vision_klines(session: aiohttp.ClientSession) -> Optional[List[List[float]]]:
    """Grab last two daily 15m kline zips from the public Vision CDN."""
    prefix = f"data/futures/um/daily/klines/{SYMBOL}/15m/"
    try:
        async with session.get(f"{VISION_S3}/?prefix={prefix}", timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None
            xml = await resp.text()
        keys = [k for k in LISTING_RE.findall(xml) if k.endswith(".zip")]
        if not keys:
            return None
        rows: List[List[float]] = []
        for key in keys[-2:]:
            url = f"{VISION_BASE}/{key}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    continue
                zip_raw = await resp.read()
            zf = zipfile.ZipFile(io.BytesIO(zip_raw))
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
                    continue  # header row
                rows.append([ts, o, h, l, c, v])
        return rows[-400:] or None
    except Exception:
        return None


async def bootstrap_market_snapshot(market_state) -> str:
    """Returns the bootstrap source tag: 'fapi-rest', 'binance-vision' or 'live-only'."""
    async with aiohttp.ClientSession() as session:
        klines = await _fetch_rest_klines(session)
        source = "none"
        if klines:
            market_state.klines_15m = klines
            source = "fapi-rest"
            if klines[-1][4] > 0:
                market_state.last_price = klines[-1][4]

        # Optional enrichment (safe if blocked)
        for coro, setter in (
            (_fetch_rest_open_interest(session), lambda v: setattr(market_state, "open_interest", v)),
            (_fetch_rest_premium_index(session), lambda v: setattr(market_state, "funding_rate", v[0])),
        ):
            try:
                val = await coro
                if val is not None:
                    if isinstance(val, tuple):
                        market_state.funding_rate = val[0]
                        if val[1] > 0:
                            market_state.mark_price = val[1]
                        if val[2] > 0:
                            market_state.index_price = val[2]
                    else:
                        setter(val)
            except Exception:
                pass

        if source == "none":
            klines = await _fetch_vision_klines(session)
            if klines:
                market_state.klines_15m = klines
                source = "binance-vision"
                if klines[-1][4] > 0:
                    market_state.last_price = klines[-1][4]
        elif source == "fapi-rest":
            pass
        else:
            source = "live-only"

        market_state.bootstrap_source = source
        return source

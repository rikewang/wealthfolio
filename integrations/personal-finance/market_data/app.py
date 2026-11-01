"""Public China market data adapter for Wealthfolio. No holdings or credentials.

AKShare runs in bounded child processes. The original direct fetcher remains
available as an explicit rollback backend; there is no silent source fallback.
Raw/unadjusted prices value positions; dividends are separate.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
import json
import math
import os
from importlib.metadata import version
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
import httpx

SHANGHAI = ZoneInfo("Asia/Shanghai")
CACHE = Path(os.environ.get("MARKET_CACHE_DIR", "data/market"))
CACHE.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 900
MAX_QUOTE_AGE_DAYS = 10  # Conservative calendar-day guard, not a trading calendar.
MAX_BODY = 8 * 1024 * 1024
ENGINE = os.environ.get("MARKET_DATA_ENGINE", "akshare")
if ENGINE not in {"akshare", "direct"}:
    raise ValueError("MARKET_DATA_ENGINE must be akshare or direct")
ENGINE_VERSION = version("akshare") if ENGINE == "akshare" else "1"
WORKER_TIMEOUT = 40
workers = asyncio.Semaphore(2)
SAMPLES = {
    "600519.SS": {"name": "贵州茅台", "type": "A股", "unit": "元/股"},
    "110022.OF": {"name": "易方达消费行业股票", "type": "场外公募基金", "unit": "元/份"},
    "518880.SS": {"name": "华安黄金ETF", "type": "黄金ETF", "unit": "元/份"},
    "AU9999.SGE": {"name": "上金所 Au99.99", "type": "黄金现货", "unit": "元/克"},
}
app = FastAPI(title="本地中国市场数据适配器 · AKShare", version="0.2.0",
    description="日频观察；仅公开行情，无账户、持仓或交易权限。/catalog 提供可直接复制的标的代码。")
locks: dict[str, asyncio.Lock] = {}


def normalized_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol == "AU9999.SGE" or re.fullmatch(r"\d{6}\.(SS|SZ|OF)", symbol):
        return symbol
    raise ValueError("支持 600519.SS、000001.SZ、110022.OF、AU9999.SGE 等格式")


def positive(value) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("上游返回无效价格")
    return result


def clean_rows(rows: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SHANGHAI)
    by_date = {}
    for raw in rows:
        day = date.fromisoformat(raw["date"])
        if day > now.date():
            raise ValueError("上游返回未来日期")
        row = {"date": day.isoformat(), "close": positive(raw["close"])}
        for key in ("open", "high", "low"):
            if key in raw:
                row[key] = positive(raw[key])
        if "volume" in raw:
            volume = float(raw["volume"])
            if not math.isfinite(volume) or volume < 0:
                raise ValueError("上游返回无效成交量")
            row["volume"] = volume
        if "high" in row and "low" in row and row["high"] < row["low"]:
            raise ValueError("上游最高价低于最低价")
        if row["date"] in by_date and by_date[row["date"]] != row:
            raise ValueError("同一天出现冲突行情")
        by_date[row["date"]] = row
    if not by_date:
        raise ValueError("上游没有返回可用日线数据")
    return [by_date[key] for key in sorted(by_date)]


def parse_fund(text: str, now: datetime | None = None) -> list[dict]:
    match = re.search(r"\bvar\s+Data_netWorthTrend\s*=\s*", text)
    if not match:
        raise ValueError("基金响应中没有正式单位净值序列")
    values, _ = json.JSONDecoder().raw_decode(text[match.end():])
    if not isinstance(values, list):
        raise ValueError("基金净值格式变化")
    rows = []
    for item in values:
        day = datetime.fromtimestamp(float(item["x"]) / 1000, timezone.utc).astimezone(SHANGHAI).date()
        rows.append({"date": day.isoformat(), "close": item["y"]})
    return clean_rows(rows, now)


def parse_tencent(payload: dict, key: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SHANGHAI)
    if payload.get("code") != 0:
        raise ValueError("腾讯行情接口错误")
    series = payload.get("data", {}).get(key, {}).get("day")
    if not series:
        raise ValueError("没有未复权日线；不以复权价格替代持仓估值")
    rows = []
    for point in series:
        if point[0] == now.date().isoformat() and now.time() < time(16, 30):
            continue  # Do not label today's unfinished bar as a closing price.
        rows.append({"date": point[0], "open": point[1], "close": point[2],
            "high": point[3], "low": point[4], "volume": float(point[5]) * 100})
    return clean_rows(rows, now)


def parse_sge(payload: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SHANGHAI)
    rows = []
    for point in payload.get("time", []):
        if point[0] == now.date().isoformat() and now.time() < time(16, 30):
            continue
        rows.append({"date": point[0], "open": point[1], "close": point[2], "low": point[3], "high": point[4]})
    return clean_rows(rows, now)


async def download(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> bytes:
    chunks = []
    length = 0
    async with client.stream(method, url, **kwargs) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            length += len(chunk)
            if length > MAX_BODY:
                raise ValueError("上游响应超过大小限制")
            chunks.append(chunk)
    return b"".join(chunks)


async def fetch_direct(symbol: str) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10),
        follow_redirects=False, trust_env=False,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate"}) as client:
        if symbol.endswith(".OF"):
            source = "东方财富·天天基金正式单位净值"
            url = f"https://fund.eastmoney.com/pingzhongdata/{symbol[:6]}.js"
            raw = await download(client, "GET", url)
            rows = parse_fund(raw.decode("utf-8-sig"))
            price_type = "official_unit_nav"
            unit = "CNY/unit"
        elif symbol == "AU9999.SGE":
            source = "上海黄金交易所"
            url = "https://www.sge.com.cn/graph/Dailyhq"
            raw = await download(client, "POST", url, data={"instid": "Au99.99"},
                headers={"Referer": "https://www.sge.com.cn/sjzx/mrhq"})
            rows = parse_sge(json.loads(raw))
            price_type = "spot_daily_close"
            unit = "CNY/gram"
        else:
            source = "腾讯财经未复权日线"
            key = ("sh" if symbol.endswith(".SS") else "sz") + symbol[:6]
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            raw = await download(client, "GET", url, params={"param": f"{key},day,,,640,"})
            rows = parse_tencent(json.loads(raw), key)
            price_type = "unadjusted_daily_close"
            unit = "CNY/unit"
        return {"symbol": symbol, "currency": "CNY", "source": source,
            "source_url": url, "price_type": price_type, "unit": unit,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "rows": rows}


async def fetch_series(symbol: str) -> dict:
    if ENGINE == "direct":
        return {**await fetch_direct(symbol), "engine": "direct", "engine_version": "1"}
    await asyncio.wait_for(workers.acquire(), timeout=10)
    process = None
    try:
        # No Wealthfolio settings, credentials or proxy environment reach workers.
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TZ"}}
        env.update(PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        process = await asyncio.create_subprocess_exec(sys.executable,
            str(Path(__file__).with_name("akshare_worker.py")), symbol,
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        raw, _ = await asyncio.wait_for(process.communicate(), timeout=WORKER_TIMEOUT)
        if process.returncode != 0 or len(raw) > MAX_BODY:
            raise ValueError("AKShare worker failed or exceeded response limit")
        result = json.loads(raw)
        if result.get("engine_version") != ENGINE_VERSION or result.get("symbol") != symbol:
            raise ValueError("AKShare worker identity mismatch")
        result["rows"] = clean_rows(result["rows"])
        if symbol.endswith((".SS", ".SZ")):
            result["rows"] = result["rows"][-640:]
        result["fetched_at"] = datetime.now(timezone.utc).isoformat()
        return result
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        workers.release()


async def series(symbol: str) -> dict:
    try:
        symbol = normalized_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    async with locks.setdefault(symbol, asyncio.Lock()):
        path = CACHE / f"{symbol}.json"
        if path.exists():
            try:
                cached = json.loads(path.read_text())
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
                if (0 <= age < CACHE_TTL_SECONDS and cached.get("engine") == ENGINE
                        and cached.get("engine_version") == ENGINE_VERSION):
                    return cached
            except (ValueError, KeyError, OSError):
                pass
        try:
            result = await fetch_series(symbol)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OverflowError, TimeoutError, OSError) as exc:
            # Do not present an old cache or an invented default as a fresh quote.
            raise HTTPException(502, f"数据源暂不可用：{type(exc).__name__}；保留 Wealthfolio 中上次价格及其原日期") from exc
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False))
        tmp.replace(path)
        return result


def latest_payload(data: dict, today: date | None = None) -> dict:
    row = data["rows"][-1]
    today = today or datetime.now(SHANGHAI).date()
    age = (today - date.fromisoformat(row["date"])).days
    if age < 0 or age > MAX_QUOTE_AGE_DAYS:
        raise HTTPException(503, f"报价日期 {row['date']} 不满足时效要求；不冒充实时价格")
    return {key: value for key, value in data.items() if key != "rows"} | {
        "price": row["close"], "date": row["date"], "age_calendar_days": age,
        "available_from": data["rows"][0]["date"], "points": len(data["rows"]),
        "frequency": "daily", "is_realtime": False,
    }


@app.get("/health")
def health():
    return {"status": "ok", "scope": "public_market_data_only", "engine": ENGINE,
        "engine_version": ENGINE_VERSION, "worker_timeout_seconds": WORKER_TIMEOUT}


@app.get("/catalog")
def catalog():
    return {"examples": SAMPLES, "patterns": ["六位代码.SS", "六位代码.SZ", "六位代码.OF", "AU9999.SGE"],
        "note": "样本不构成持仓或推荐。日频数据；A股/ETF历史最多640根，基金与黄金按上游实际返回。"}


@app.get("/v1/latest/{symbol}")
async def latest(symbol: str):
    return latest_payload(await series(symbol))


@app.get("/v1/history/{symbol}")
async def history(symbol: str, from_date: date | None = Query(None, alias="from"),
                  to_date: date | None = Query(None, alias="to")):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "起始日期不能晚于结束日期")
    data = await series(symbol)
    rows = [row for row in data["rows"] if
        (not from_date or row["date"] >= from_date.isoformat()) and
        (not to_date or row["date"] <= to_date.isoformat())]
    return {key: value for key, value in data.items() if key != "rows"} | {
        "prices": rows, "available_from": data["rows"][0]["date"],
        "available_to": data["rows"][-1]["date"], "count": len(rows)}


@app.get("/status")
async def status():
    async def inspect(symbol):
        try:
            return {"status": "ok", **SAMPLES[symbol], **await latest(symbol)}
        except HTTPException as exc:
            return {"status": "error", "symbol": symbol, **SAMPLES[symbol], "error": exc.detail}
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
        "samples": await asyncio.gather(*(inspect(symbol) for symbol in SAMPLES))}

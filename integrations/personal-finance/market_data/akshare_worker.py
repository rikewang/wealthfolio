"""One bounded, credential-free AKShare fetch per child process.

AKShare 1.20.2 evaluates the fund provider's JS in MiniRacer. Keeping it here
allows the API parent to kill a stalled fetch, including its JS runtime.
"""
from contextlib import redirect_stdout
from datetime import datetime, time, timedelta
import json
import sys
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_BODY = 8 * 1024 * 1024


def require_unadjusted(payload, symbol):
    if payload.get("code") != 0 or not payload.get("data", {}).get(symbol, {}).get("day"):
        # AKShare otherwise silently falls back to hfqday/qfqday.
        raise ValueError("没有未复权日线，不接受复权价格替代")


def install_transport_guard():
    import requests

    class BoundedSession(requests.Session):
        def __init__(self):
            super().__init__()
            self.trust_env = False

        def send(self, request, **kwargs):
            url = urlsplit(request.url)
            if url.scheme != "https" or url.hostname not in {
                "proxy.finance.qq.com", "web.ifzq.gtimg.cn",
                "fund.eastmoney.com", "www.sge.com.cn",
            }:
                raise ValueError("非预期行情地址")
            kwargs.update(timeout=(8, 15), stream=True, allow_redirects=False)
            response = super().send(request, **kwargs)
            try:
                response.raise_for_status()
                if response.is_redirect:
                    raise ValueError("上游重定向需重新验证")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise ValueError("行情响应超过大小限制")
                    chunks.append(chunk)
                response._content = b"".join(chunks)
                response._content_consumed = True
                param = parse_qs(url.query).get("param", [""])[0]
                if url.path.endswith("/newfqkline/get") and param.endswith(","):
                    raw = response.text
                    payload, _ = json.JSONDecoder().raw_decode(raw[raw.index("{"):])
                    require_unadjusted(payload, param.split(",")[0])
                return response
            finally:
                response.close()

    # AKShare uses requests.get/post, which create requests.sessions.Session.
    # This replacement exists only for this short-lived worker, never the API.
    requests.sessions.Session = BoundedSession


def map_rows(records, symbol, now=None):
    now = now or datetime.now(SHANGHAI)
    rows = []
    for record in records:
        day = record["净值日期"] if symbol.endswith(".OF") else record["date"]
        day = day.isoformat() if hasattr(day, "isoformat") else str(day)
        if symbol.endswith(".OF"):
            rows.append({"date": day, "close": record["单位净值"]})
        elif day != now.date().isoformat() or now.time() >= time(16, 30):
            # Volume is deliberately omitted: AKShare 1.20.2 has inconsistent
            # lot/share normalization for Shenzhen 000xxx. We only promise OHLC.
            rows.append({"date": day, **{k: record[k] for k in ("open", "close", "high", "low")}})
    return rows


def fetch(symbol):
    import akshare as ak

    install_transport_guard()
    if symbol.endswith(".OF"):
        frame = ak.fund_open_fund_info_em(symbol=symbol[:6], indicator="单位净值走势")
        function = "fund_open_fund_info_em"
        source, url = "东方财富·天天基金正式单位净值", f"https://fund.eastmoney.com/pingzhongdata/{symbol[:6]}.js"
        price_type, unit = "official_unit_nav", "CNY/unit"
    elif symbol == "AU9999.SGE":
        frame = ak.spot_hist_sge(symbol="Au99.99")
        function = "spot_hist_sge"
        source, url = "上海黄金交易所", "https://www.sge.com.cn/graph/Dailyhq"
        price_type, unit = "spot_daily_close", "CNY/gram"
    else:
        today = datetime.now(SHANGHAI).date()
        start = (today - timedelta(days=1100)).strftime("%Y%m%d")
        key = ("sh" if symbol.endswith(".SS") else "sz") + symbol[:6]
        frame = ak.stock_zh_a_hist_tx(symbol=key, start_date=start,
            end_date=today.strftime("%Y%m%d"), adjust="", timeout=15)
        function = "stock_zh_a_hist_tx"
        source, url = "腾讯财经未复权日线", "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
        price_type, unit = "unadjusted_daily_close", "CNY/unit"
    return {"symbol": symbol, "currency": "CNY", "engine": "akshare",
        "engine_version": ak.__version__, "source_function": function,
        "source": source, "source_url": url, "price_type": price_type, "unit": unit,
        "rows": map_rows(frame.to_dict("records"), symbol)}


if __name__ == "__main__":
    # Library progress output must not corrupt the JSON protocol.
    with redirect_stdout(sys.stderr):
        result = fetch(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))

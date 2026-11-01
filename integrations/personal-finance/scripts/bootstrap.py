"""Initial local setup. Creates sample holdings only inside the named demo profile."""
import json
import httpx
from wf_client import ROOT, Wealthfolio

DEMO = "数据接入验证（示例）"
PERSONAL = "个人资产"
CODE = "cn-local"
PROVIDER = {
    "code": CODE, "name": "中国市场 · AKShare 日频", "priority": 0,
    "description": "本地 AKShare：A股/ETF 未复权收盘价；场外基金正式单位净值；上金所 Au99.99 元/克。仅公开数据，无需 Connect。",
    "useAsFallback": False,
    "sources": [
        {"kind": "latest", "format": "json", "method": "GET",
         "url": "http://market-data:8090/v1/latest/{SYMBOL}",
         "pricePath": "$.price", "datePath": "$.date", "dateFormat": "%Y-%m-%d",
         "currencyPath": "$.currency", "factor": 1, "invert": False},
        {"kind": "historical", "format": "json", "method": "GET",
         "url": "http://market-data:8090/v1/history/{SYMBOL}?from={FROM}&to={TO}",
         "pricePath": "$.prices[*].close", "datePath": "$.prices[*].date", "dateFormat": "%Y-%m-%d",
         "currencyPath": "$.currency", "factor": 1, "invert": False},
    ],
}
# Date-only observations deliberately have no timezone conversion. Wealthfolio
# stores these as calendar-day UTC noon, keeping NAV dates unchanged.
SAMPLES = [
    ("600519.SS", "贵州茅台", "EQUITY", "XSHG", "100"),
    ("110022.OF", "易方达消费行业股票", "EQUITY", None, "1000"),
    ("518880.SS", "华安黄金ETF", "EQUITY", "XSHG", "100"),
    ("AU9999.SGE", "上金所 Au99.99（按克）", "METAL", None, "10"),
]


def add_asset(wf, symbol, name, instrument_type, mic=None):
    existing = wf.request("GET", "assets")
    def matches(asset):
        override = (asset.get("providerConfig") or {}).get("overrides", {}).get(f"CUSTOM:{CODE}", {})
        return override.get("symbol") == symbol or (
            asset.get("displayCode") == symbol and asset.get("instrumentExchangeMic") == mic)
    found = next((a for a in existing if matches(a)), None)
    if found:
        return found
    return wf.request("POST", "assets", {
        "kind": "INVESTMENT", "name": name, "displayCode": symbol,
        "quoteMode": "MARKET", "quoteCcy": "CNY", "isActive": True,
        "instrumentType": instrument_type, "instrumentSymbol": symbol,
        "instrumentExchangeMic": mic,
        "providerConfig": {"preferred_provider": "CUSTOM_SCRAPER", "custom_provider_code": CODE,
            "overrides": {f"CUSTOM:{CODE}": {"type": "equity_symbol", "symbol": symbol}}},
        "notes": (
            "数量单位：克；价格单位：人民币/克。原版界面的“股/股份”为通用文案，输入 10 代表 10 克。"
            "上金所 Au99.99 日收盘价，不含金饰工费、成色折价或回购价差。"
            if instrument_type == "METAL" else "本地日频数据；基金价格为正式单位净值，数量为份。"
        ),
        "metadata": {"contractMultiplier": 1},
    })


def classify(wf, asset_id, taxonomy, category):
    wf.request("PUT", f"taxonomies/assignments/asset/{asset_id}/taxonomy/{taxonomy}", [{
        "assetId": asset_id, "taxonomyId": taxonomy, "categoryId": category,
        "weight": 10000, "source": "manual"}])


def main():
    if (ROOT / "data/setup-state.json").exists():
        print("初始化记录已存在，保留现有档案与持仓；更新行情请用 ./finance refresh。")
        return
    wf = Wealthfolio()
    state = wf.state()
    personal = next((p for p in state["profiles"] if p["name"] == PERSONAL), None)
    if not personal:
        default = next((p for p in state["profiles"] if p["name"] == "Personal"), None)
        if default:
            wf.select(default["id"])
            if wf.request("GET", "accounts"):
                raise RuntimeError("默认档案已含账户，拒绝自动改动；请单独创建个人资产档案。")
            wf.request("POST", "profiles/update_profile", {"name": PERSONAL, "avatarId": "default"})
            personal = default
        else:
            wf.request("POST", "profiles/create_profile", {"name": PERSONAL, "avatarId": "default"})
            personal = next(p for p in wf.state()["profiles"] if p["name"] == PERSONAL)
    demo = next((p for p in wf.state()["profiles"] if p["name"] == DEMO), None)
    if not demo:
        wf.request("POST", "profiles/create_profile", {"name": DEMO, "avatarId": "default"})
        demo = next(p for p in wf.state()["profiles"] if p["name"] == DEMO)

    manifest = {"personalProfileId": personal["id"], "demoProfileId": demo["id"], "assets": []}
    with httpx.Client(trust_env=False, timeout=45) as market:
        for profile in (personal, demo):
            wf.select(profile["id"])
            wf.request("PUT", "settings", {"baseCurrency": "CNY", "timezone": "Asia/Shanghai",
                "language": "zh", "formattingRegion": "CN", "onboardingCompleted": True,
                "syncEnabled": False, "autoUpdateCheckEnabled": False})
            providers = wf.request("GET", "custom-providers")
            if not any(p["id"] == CODE for p in providers):
                wf.request("POST", "custom-providers", PROVIDER)
            if not (ROOT / "data/setup-state.json").exists():
                for provider in wf.request("GET", "providers"):
                    if provider["enabled"] and provider["id"] not in ("CUSTOM_SCRAPER", "YAHOO"):
                        wf.request("PUT", "providers/settings", {"providerId": provider["id"],
                            "priority": provider["priority"], "enabled": False})
            assets = [add_asset(wf, symbol, name, kind, mic) for symbol, name, kind, mic, qty in SAMPLES]
            if not (ROOT / "data/setup-state.json").exists():
                classify(wf, assets[1]["id"], "instrument_type", "FUND_MUTUAL")
                classify(wf, assets[2]["id"], "instrument_type", "ETF")
                classify(wf, assets[2]["id"], "asset_classes", "COMMODITIES")
            if profile["id"] == demo["id"]:
                accounts = wf.request("GET", "accounts")
                account = next((a for a in accounts if a["name"] == "验证样本（非真实资产）"), None)
                if not account:
                    account = wf.request("POST", "accounts", {"name": "验证样本（非真实资产）",
                        "accountType": "SECURITIES", "currency": "CNY", "isDefault": True,
                        "isActive": True, "isArchived": False, "trackingMode": "HOLDINGS"})
                snapshots = wf.request("GET", "snapshots", params={"accountId": account["id"]})
                if not snapshots:
                    quotes = []
                    for symbol, *_ in SAMPLES:
                        response = market.get(f"http://127.0.0.1:8090/v1/latest/{symbol}")
                        response.raise_for_status()
                        quotes.append(response.json())
                    snapshot_date = max(q["date"] for q in quotes)
                    wf.request("POST", "snapshots", {"accountId": account["id"], "snapshotDate": snapshot_date,
                        "cashBalances": {"CNY": "0"}, "holdings": [
                            {"assetId": asset["id"], "symbol": spec[0], "quantity": spec[4],
                             "currency": "CNY", "averageCost": str(quote["price"])}
                            for spec, asset, quote in zip(SAMPLES, assets, quotes)]})
                manifest["accountId"] = account["id"]
                manifest["assets"] = [{"symbol": spec[0], "id": asset["id"], "quantity": spec[4]}
                    for spec, asset in zip(SAMPLES, assets)]
            wf.request("POST", "market-data/sync", {"assetIds": [a["id"] for a in assets],
                "refetchAll": False, "refetchRecentDays": 1825})
    (ROOT / "data/setup-state.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    wf.close()
    print("已配置个人档案与独立示例档案，已请求四类资产历史同步。真实持仓尚未录入。")


if __name__ == "__main__":
    main()

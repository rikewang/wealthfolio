"""Populate the existing isolated demo profile with reproducible fictional finances.

Prices come from the configured providers. Quantities, trades, cashflows, manual
valuations, classifications and planning assumptions are demonstration data.
Never writes to the personal profile. Stable activity IDs make retries safe.
"""
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import time
import uuid

from bootstrap import add_asset, classify
from wf_client import ROOT, Wealthfolio

TAG = "DEMO-RICH-V1"
START = "2025-01-02"
END = "2026-10-30"
STATE = ROOT / "data/demo-rich-state.json"
NOTE = "【模拟演示】"

# symbol, name, account, currency, type, MIC, quantity, structure, exposure, industry, region
SPECS = [
    ("600519.SS", "贵州茅台", "cn", "CNY", "EQUITY", "XSHG", "100", "STOCK_COMMON", "EQUITY", "30", "R30"),
    ("000001.SZ", "平安银行", "cn", "CNY", "EQUITY", "XSHE", "1800", "STOCK_COMMON", "EQUITY", "40", "R30"),
    ("300750.SZ", "宁德时代", "cn", "CNY", "EQUITY", "XSHE", "200", "STOCK_COMMON", "EQUITY", "20", "R30"),
    ("510300.SS", "华泰柏瑞沪深300ETF", "cn", "CNY", "EQUITY", "XSHG", "16000", "ETF", "EQUITY", None, "R30"),
    ("510500.SS", "南方中证500ETF", "cn", "CNY", "EQUITY", "XSHG", "6000", "ETF", "EQUITY", None, "R30"),
    ("512480.SS", "国联安中证全指半导体ETF", "cn", "CNY", "EQUITY", "XSHG", "18000", "ETF", "EQUITY", "45", "R30"),
    ("513180.SS", "华夏恒生科技ETF（QDII）", "cn", "CNY", "EQUITY", "XSHG", "20000", "ETF", "EQUITY", None, "R30"),
    ("110022.OF", "易方达消费行业股票", "fund", "CNY", "EQUITY", None, "12000", "FUND_MUTUAL", "EQUITY", None, "R30"),
    ("161725.OF", "招商中证白酒指数A", "fund", "CNY", "EQUITY", None, "20000", "FUND_MUTUAL", "EQUITY", None, "R30"),
    ("511010.SS", "国泰上证5年期国债ETF", "defensive", "CNY", "EQUITY", "XSHG", "600", "ETF", "FIXED_INCOME", None, "R30"),
    ("518880.SS", "华安黄金ETF", "defensive", "CNY", "EQUITY", "XSHG", "6000", "ETF", "COMMODITIES", None, "R30"),
    ("AU9999.SGE", "上金所 Au99.99（按克）", "defensive", "CNY", "METAL", None, "30", "PHYSICAL_METAL", "COMMODITIES", None, "R30"),
    ("QQQ", "Invesco QQQ · 纳斯达克100ETF", "us", "USD", "EQUITY", "XNAS", "25", "ETF", "EQUITY", None, "R20"),
    ("MSFT", "Microsoft · 微软", "us", "USD", "EQUITY", "XNAS", "20", "STOCK_COMMON", "EQUITY", "45", "R20"),
    ("0700.HK", "腾讯控股", "hk", "HKD", "EQUITY", "XHKG", "100", "STOCK_COMMON", "EQUITY", "50", "R30"),
    ("BTC-USD", "Bitcoin · 比特币", "crypto", "USD", "CRYPTO", None, "0.04", "CRYPTO_NATIVE", "DIGITAL_ASSETS", None, None),
]
ACCOUNTS = {
    "cn": ("A股与指数策略（模拟）", "SECURITIES", "CNY", "450000", "国内投资"),
    "fund": ("公募基金定投（模拟）", "SECURITIES", "CNY", "90000", "国内投资"),
    "defensive": ("黄金与固收（模拟）", "SECURITIES", "CNY", "160000", "防御资产"),
    "us": ("美股科技与指数（模拟）", "SECURITIES", "USD", "36000", "海外投资"),
    "hk": ("港股账户（模拟）", "SECURITIES", "HKD", "100000", "海外投资"),
    "crypto": ("数字资产观察仓（模拟）", "CRYPTOCURRENCY", "USD", "8000", "海外投资"),
    "cash": ("工资与日常收支（模拟）", "CASH", "CNY", "120000", "生活资金"),
    "reserve": ("家庭应急储备（模拟）", "CASH", "CNY", "80000", "生活资金"),
}


def uid(key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, TAG + ":" + key))


def money(value):
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def fingerprint(wf, profile_id):
    wf.select(profile_id)
    # Ignore market quote caches: only compare user-owned ledger entities.
    entities = {p: wf.request("GET", p) for p in ("accounts", "goals", "portfolios")}
    entities["activities"] = wf.request("POST", "activities/search", {"page": 0, "pageSize": 10000})
    return hashlib.sha256(json.dumps(entities, sort_keys=True).encode()).hexdigest()


def activity(key, account, kind, day, currency, amount=None, asset_id=None, quantity=None, price=None, fee=None, notes="", category=None):
    row = {"id": uid(key), "accountId": account, "activityType": kind,
           "activityDate": day + "T07:00:00Z", "currency": currency,
           "status": "POSTED", "notes": NOTE + " " + notes,
           "sourceSystem": "MANUAL", "sourceRecordId": TAG + ":" + key,
           "idempotencyKey": TAG + ":" + key, "needsReview": False}
    if amount is not None:
        row["amount"] = money(amount)
    if asset_id:
        row["asset"] = {"id": asset_id}
    if quantity is not None:
        row["quantity"] = str(quantity)
    if price is not None:
        row["unitPrice"] = str(price)
    if fee is not None:
        row["fee"] = money(fee)
    return row, category


def price_on(history, wanted):
    eligible = [q for q in history if q["timestamp"][:10] <= wanted and Decimal(str(q["close"])) > 0]
    if not eligible:
        raise RuntimeError("缺少交易日之前的真实行情：" + wanted)
    q = max(eligible, key=lambda x: x["timestamp"])
    return q["timestamp"][:10], Decimal(str(q["close"]))


def main():
    setup = json.loads((ROOT / "data/setup-state.json").read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {"version": TAG, "accounts": {}, "assets": {}, "alternatives": {}, "goals": {}}
    wf = Wealthfolio()
    profile = next(p for p in wf.state()["profiles"] if p["id"] == setup["demoProfileId"])
    assert "示例" in profile["name"] and profile["id"] != setup["personalProfileId"]
    before = fingerprint(wf, setup["personalProfileId"])
    state.setdefault("personalLedgerFingerprint", before)
    wf.select(profile["id"])
    state["profileId"] = profile["id"]
    existing_accounts = wf.request("GET", "accounts")
    for key, (name, typ, ccy, opening, group) in ACCOUNTS.items():
        found = next((a for a in existing_accounts if a["name"] == name), None)
        if not found:
            found = wf.request("POST", "accounts", {"name": name, "accountType": typ, "currency": ccy,
                "group": group, "isDefault": False, "isActive": True, "isArchived": False, "trackingMode": "TRANSACTIONS"})
        elif found["accountType"] != typ:
            found = wf.request("PUT", "accounts/" + found["id"], {**found, "accountType": typ})
        state["accounts"][key] = found["id"]
        save(state)
    print("已准备 8 个模拟账户。", flush=True)

    for symbol, name, account, ccy, typ, mic, qty, structure, exposure, industry, region in SPECS:
        if symbol in state["assets"]:
            continue
        if ccy == "CNY":
            asset = add_asset(wf, symbol, name, typ, mic)
        else:
            found = next((a for a in wf.request("GET", "assets") if a.get("instrumentSymbol") in (symbol, symbol.split(".")[0], symbol.split("-")[0]) and a.get("quoteCcy") == ccy), None)
            override = {"type": "crypto_symbol" if typ == "CRYPTO" else "equity_symbol", "symbol": symbol}
            asset = found or wf.request("POST", "assets", {"kind": "INVESTMENT", "name": name,
                "displayCode": symbol, "quoteMode": "MARKET", "quoteCcy": ccy,
                "instrumentType": typ, "instrumentSymbol": symbol, "instrumentExchangeMic": mic,
                "isActive": True, "notes": NOTE + " 行情来自 Yahoo Finance。",
                "providerConfig": {"preferred_provider": "YAHOO", "overrides": {"YAHOO": override}}})
        state["assets"][symbol] = asset["id"]
        classify(wf, asset["id"], "instrument_type", structure)
        classify(wf, asset["id"], "asset_classes", exposure)
        classify(wf, asset["id"], "risk_category", "MEDIUM" if exposure in ("FIXED_INCOME", "COMMODITIES") else "HIGH")
        if industry:
            classify(wf, asset["id"], "industries_gics", industry)
        if region:
            classify(wf, asset["id"], "regions", region)
        save(state)
        print("资产已配置：" + symbol, flush=True)

    # Account currency creation supplies the FX instruments; sync those as well.
    ids = list(state["assets"].values()) + [a["id"] for a in wf.request("GET", "assets") if a["kind"] == "FX"]
    if not state.get("quotesReady"):
        wf.request("POST", "market-data/sync", {"assetIds": ids, "refetchAll": False, "refetchRecentDays": 730})
        print("已请求 16 个标的与汇率历史；检查实际入库结果。", flush=True)
    histories = {}
    for attempt in range(36):
        pending = []
        for symbol, asset_id in state["assets"].items():
            if symbol in histories:
                continue
            h = wf.request("GET", "market-data/quotes/history", params={"symbol": asset_id})
            if h and min(q["timestamp"][:10] for q in h) <= START and max(q["timestamp"][:10] for q in h) >= END:
                histories[symbol] = h
            else:
                pending.append(symbol)
        if not pending:
            break
        print("等待行情：" + ", ".join(pending), flush=True)
        time.sleep(5)
    if pending:
        raise RuntimeError("尚未取得完整真实历史，未伪造价格：" + ", ".join(pending))
    state["quotesReady"] = True
    state["quoteCounts"] = {s: len(h) for s, h in histories.items()}
    save(state)

    rows = []
    # Preserve the four original verification positions while giving the whole
    # profile transaction history, avoiding unsupported mixed-mode performance.
    original = next(a for a in existing_accounts if a["id"] == setup["accountId"])
    if original["trackingMode"] != "TRANSACTIONS":
        wf.request("PUT", "accounts/" + original["id"], {**original, "trackingMode": "TRANSACTIONS"})
    original_cost = Decimal(0)
    for sample in setup["assets"]:
        day, price = price_on(histories[sample["symbol"]], END)
        qty = Decimal(sample["quantity"])
        original_cost += qty * price
        rows.append(activity("verification-buy-" + sample["symbol"], original["id"], "BUY", day, "CNY", qty * price,
                             sample["id"], qty, price, 0, "保留原来的接口核验样本数量与成本。"))
    rows.append(activity("verification-funding", original["id"], "DEPOSIT", END, "CNY", original_cost,
                         notes="原接口核验样本的模拟入金，与四笔建仓金额相等。"))
    for key, (name, typ, ccy, opening, group) in ACCOUNTS.items():
        rows.append(activity("opening-" + key, state["accounts"][key], "DEPOSIT", START, ccy, amount=opening, notes="模拟期初资金；不作为工资收入。"))
    for symbol, name, key, ccy, typ, mic, qty, structure, exposure, industry, region in SPECS:
        day, price = price_on(histories[symbol], "2025-01-06")
        quantity = Decimal(qty)
        fee = Decimal("5") if ccy == "CNY" and typ == "EQUITY" and not symbol.endswith(".OF") else Decimal("0")
        rows.append(activity("buy-open-" + symbol, state["accounts"][key], "BUY", day, ccy,
            quantity * price + fee, state["assets"][symbol], quantity, price, fee,
            "模拟首次建仓；成交价使用该日公开收盘价。"))
        if symbol in ("510300.SS", "512480.SS", "QQQ", "MSFT"):
            for label, wanted, kind, ratio in (("rebalance", "2025-09-12", "SELL", Decimal("0.2")), ("add", "2026-04-10", "BUY", Decimal("0.3"))):
                day, price = price_on(histories[symbol], wanted)
                units = (quantity * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                if ccy == "CNY":
                    units = (units / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 100
                rows.append(activity(label + symbol, state["accounts"][key], kind, day, ccy,
                    units * price + (fee if kind == "BUY" else -fee), state["assets"][symbol], units, price, fee,
                    "模拟减仓 / 加仓，用于展示已实现与未实现盈亏。"))
        if symbol in ("600519.SS", "000001.SZ", "511010.SS", "QQQ", "MSFT"):
            for wanted in ("2025-06-20", "2025-12-19", "2026-06-19", "2026-09-18"):
                day, price = price_on(histories[symbol], wanted)
                rows.append(activity("div-" + symbol + wanted, state["accounts"][key], "DIVIDEND", day, ccy,
                    quantity * price * Decimal("0.003"), state["assets"][symbol], notes="模拟现金分红，用于收入页展示；不是该证券实际分红公告。"))

    # 22 months of linked salary, spending, investment transfers and fund purchases.
    expenses = [("food", "cat_food", 1500, "餐饮与咖啡"), ("groceries", "cat_groceries", 1200, "超市与生鲜"),
                ("transport", "cat_transport", 650, "通勤与打车"), ("bills", "cat_bills", 900, "水电网络与物业"),
                ("shopping", "cat_shopping", 1800, "日用品与服饰"), ("health", "cat_health", 450, "健康与运动"),
                ("education", "cat_education", 1200, "学习与课程"), ("entertainment", "cat_entertainment", 600, "影音与娱乐")]
    for i in range(22):
        year, month = 2025 + i // 12, i % 12 + 1
        ym = f"{year}-{month:02}"
        salary = 32000 if year == 2025 else 35000
        rows.append(activity("salary-" + ym, state["accounts"]["cash"], "DEPOSIT", ym + "-05", "CNY", salary, notes="模拟工资收入", category=("income_sources", "cat_income_salary")))
        if month in (2, 8):
            rows.append(activity("bonus-" + ym, state["accounts"]["cash"], "DEPOSIT", ym + "-08", "CNY", 22000 if month == 2 else 9000, notes="模拟奖金", category=("income_sources", "cat_income_bonus")))
        for j, (slug, cat, base, label) in enumerate(expenses):
            amount = Decimal(base) * Decimal(str(0.88 + ((i * 3 + j * 5) % 9) * 0.04))
            rows.append(activity(slug + ym, state["accounts"]["cash"], "WITHDRAWAL", ym + f"-{10+j:02}", "CNY", amount, notes="模拟消费：" + label, category=("spending_categories", cat)))
        rows.append(activity("interest-" + ym, state["accounts"]["reserve"], "INTEREST", ym + "-25", "CNY", 100 + i * 2, notes="模拟存款利息", category=("income_sources", "cat_income_interest")))
        rows.append(activity("mortgage-payment-" + ym, state["accounts"]["cash"], "WITHDRAWAL", ym + "-20", "CNY", 6500, notes="模拟房贷现金还款，包含本金与利息；贷款余额另以月度手工估值展示。", category=("spending_categories", "cat_housing")))
        rows.append(activity("car-payment-" + ym, state["accounts"]["cash"], "WITHDRAWAL", ym + "-21", "CNY", 2400, notes="模拟车贷现金还款，包含本金与利息；贷款余额另以月度手工估值展示。", category=("spending_categories", "cat_transport")))
        if month in (5, 10):
            rows.append(activity("travel-" + ym, state["accounts"]["cash"], "WITHDRAWAL", ym + "-03", "CNY", 6800 + i * 90, notes="模拟家庭旅行支出", category=("spending_categories", "cat_travel")))
        # Both legs are explicitly linked through sourceGroupId and a common key.
        for dest, amount in (("fund", 4500), ("reserve", 1500)):
            group_id = uid("transfer-" + dest + ym)
            for direction, account in (("OUT", "cash"), ("IN", dest)):
                row, cat = activity("transfer-" + dest + direction + ym, state["accounts"][account], "TRANSFER_" + direction, ym + "-06", "CNY", amount, notes="内部转账：工资账户 → " + ACCOUNTS[dest][0], category=("savings_categories", "cat_savings_investments") if dest == "fund" and direction == "OUT" else None)
                row["sourceGroupId"] = group_id
                rows.append((row, cat))
        for symbol, budget in (("110022.OF", 3000), ("161725.OF", 1500)):
            day, price = price_on(histories[symbol], ym + "-08")
            units = (Decimal(budget) / price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            rows.append(activity("sip-" + symbol + ym, state["accounts"]["fund"], "BUY", day, "CNY", units * price, state["assets"][symbol], units, price, 0, "模拟月度定投；金额与份额按真实历史净值换算。"))
    # A few November 1 examples make the default current-month spending view useful.
    for slug, cat, amount, title in (("food", "cat_food", 86, "周末餐饮"), ("groceries", "cat_groceries", 268, "家庭采购"), ("bills", "cat_bills", 238, "网络与电话")):
        rows.append(activity("current-" + slug, state["accounts"]["cash"], "WITHDRAWAL", "2026-11-01", "CNY", amount, notes="模拟当月支出：" + title, category=("spending_categories", cat)))

    existing = wf.request("POST", "activities/search", {"page": 0, "pageSize": 10000})
    existing_rows = existing.get("activities", existing.get("data", []))
    existing_records = {a.get("sourceRecordId"): a["id"] for a in existing_rows}
    creates = [r for r, _ in rows if r["sourceRecordId"] not in existing_records]
    existing_by_record = {a.get("sourceRecordId"): a for a in existing_rows}
    note_updates = []
    for row, _ in rows:
        old = existing_by_record.get(row["sourceRecordId"])
        # Updating the outgoing leg also maintains its linked incoming leg.
        if old and old.get("comment") != row["notes"] and row["activityType"] != "TRANSFER_IN":
            patch = {k: row[k] for k in ("accountId", "activityType", "activityDate", "currency", "notes")}
            note_updates.append({**patch, "id": old["id"]})
    for offset in range(0, len(note_updates), 150):
        result = wf.request("POST", "activities/bulk", {"updates": note_updates[offset:offset + 150]})
        if result.get("errors"):
            raise RuntimeError("模拟流水备注更新失败：" + json.dumps(result["errors"], ensure_ascii=False)[:1200])
    for offset in range(0, len(creates), 150):
        result = wf.request("POST", "activities/bulk", {"creates": creates[offset:offset + 150]})
        if result.get("errors"):
            raise RuntimeError("演示流水部分写入失败：" + json.dumps(result["errors"], ensure_ascii=False)[:1800])
        print(f"模拟流水写入 {offset + len(result['created'])}/{len(creates)}", flush=True)
    state["activityCount"] = len(rows)
    save(state)
    wf.request("PUT", "spending/settings", {"enabled": True, "accountIds": [state["accounts"]["cash"], state["accounts"]["reserve"]]})
    persisted = wf.request("POST", "activities/search", {"page": 0, "pageSize": 10000})["data"]
    record_ids = {a.get("sourceRecordId"): a["id"] for a in persisted}
    assignments = [{"activityId": record_ids[r["sourceRecordId"]], "taxonomyId": cat[0], "categoryId": cat[1]} for r, cat in rows if cat]
    wf.request("POST", "spending/assignments/bulk", assignments)
    for period in ("2026-10", "2026-11"):
        for slug, cat, amount, name in expenses + [("travel", "cat_travel", 8000, "旅行"), ("housing", "cat_housing", 6500, "房贷")]:
            if cat == "cat_transport":
                amount += 2400
            wf.request("POST", "spending/budget/targets", {"id": uid("budget-" + period + cat), "periodKey": period, "targetType": "category", "taxonomyId": "spending_categories", "categoryId": cat, "amount": money(amount)})

    event_types = wf.request("GET", "spending/event-types")
    travel_type = next((x for x in event_types if (x.get("key") or "").lower() == "travel" or x["name"].lower() == "travel"), None)
    if travel_type:
        existing_events = wf.request("GET", "spending/events")
        for year in (2025, 2026):
            name = f"{year} 国庆家庭旅行（模拟）"
            event = next((x for x in existing_events if x["name"] == name), None)
            event = event or wf.request("POST", "spending/events", {"name": name, "description": NOTE,
                "eventTypeId": travel_type["id"], "startDate": f"{year}-10-01T00:00:00+08:00", "endDate": f"{year}-10-07T23:59:59+08:00"})
            activity_id = record_ids[f"{TAG}:travel-{year}-10"]
            wf.request("PUT", f"spending/cash-activities/{activity_id}/event", {"eventId": event["id"]})

    # Manual non-market assets: their values are entirely fictional and labeled.
    alternatives = [
        ("home", "property", "自住房 · 模拟估值", 2800000, 2680000, {"property_type": "primary_residence", "location": "虚构示例住宅", "area": "90"}),
        ("car", "vehicle", "家庭汽车 · 模拟估值", 160000, 210000, {"make": "示例品牌", "model": "家庭用车", "year": "2023"}),
        ("mortgage", "liability", "住房贷款 · 模拟余额", 1185000, 1260000, {"liability_type": "mortgage"}),
        ("loan", "liability", "汽车贷款 · 模拟余额", 42000, 85000, {"liability_type": "auto_loan"}),
    ]
    for key, kind, name, current, purchase, metadata in alternatives:
        if key not in state["alternatives"]:
            body = {"kind": kind, "name": name, "currency": "CNY", "currentValue": str(current), "valueDate": END,
                    "purchasePrice": str(purchase), "purchaseDate": START, "metadata": metadata}
            if key in ("mortgage", "loan"):
                body["linkedAssetId"] = state["alternatives"]["home" if key == "mortgage" else "car"]
                body["loan"] = {"originalAmount": purchase, "originationDate": START, "interestRate": 3.1 if key == "mortgage" else 4.2}
            created = wf.request("POST", "alternative-assets", body)
            state["alternatives"][key] = created["assetId"]
            save(state)
        asset_id = state["alternatives"][key]
        wf.request("PUT", f"alternative-assets/{asset_id}/metadata", {"name": name, "metadata": metadata, "notes": NOTE + "手工估值为虚构演示。"})
        for i in range(22):
            year, month = 2025 + i // 12, i % 12 + 1
            day = f"{year}-{month:02}-{min(28, calendar.monthrange(year, month)[1]):02}"
            value = Decimal(purchase) + (Decimal(current) - Decimal(purchase)) * Decimal(i) / 21
            wf.request("PUT", f"alternative-assets/{asset_id}/valuation", {"value": money(value), "date": day, "notes": "模拟月度估值 / 贷款余额，非真实资产价格"})
    print("房产、汽车和两笔关联负债已补齐 22 个月的模拟估值。", flush=True)

    portfolios = wf.request("GET", "portfolios")
    groups = [("全景投资组合（模拟）", ["cn", "fund", "defensive", "us", "hk", "crypto"]),
              ("国内配置（模拟）", ["cn", "fund", "defensive"]), ("海外与数字资产（模拟）", ["us", "hk", "crypto"])]
    for i, (name, keys) in enumerate(groups):
        found = next((p for p in portfolios if p["name"] == name), None)
        if not found:
            found = wf.request("POST", "portfolios", {"name": name, "description": NOTE, "sortOrder": i, "accountIds": [state["accounts"][k] for k in keys]})
        state.setdefault("portfolios", {})[name] = found["id"]
        save(state)

    goals = [("reserve", "custom_save_up", "六个月应急金（模拟）", 150000, "2027-12-31", "reserve", 100, 2500, 0.015),
             ("education", "education", "进修与教育储备（模拟）", 180000, "2030-09-01", "fund", 35, 2500, 0.03),
             ("travel", "custom_save_up", "家庭旅行计划（模拟）", 45000, "2027-06-01", "cash", 10, 1200, 0),
             ("car", "car", "家庭换车储备（模拟）", 150000, "2030-06-01", "cash", 15, 1800, 0.02),
             ("home", "home", "住房改善储备（模拟）", 800000, "2032-12-31", "fund", 50, 2800, 0.03),
             ("freedom", "custom_save_up", "长期投资里程碑（模拟）", 2000000, "2033-12-31", "cn", 100, 5000, 0.04)]
    for key, typ, title, target, target_date, acc, share, contribution, growth in goals:
        if key not in state["goals"]:
            g = wf.request("POST", "goals", {"id": uid("goal-" + key), "goalType": typ, "title": title, "description": NOTE + "预期回报仅为情景假设。", "targetAmount": target, "statusLifecycle": "active", "priority": 1, "coverImageKey": typ, "startDate": START, "targetDate": target_date})
            state["goals"][key] = g["id"]
            save(state)
        goal_id = state["goals"][key]
        goal = wf.request("GET", "goals/" + goal_id)
        goal.update({"targetAmount": target, "targetDate": target_date})
        wf.request("PUT", "goals", goal)
        wf.request("PUT", f"goals/{goal_id}/funding", [{"accountId": state["accounts"][acc], "sharePercent": share}])
        wf.request("POST", "goals/plan", {"goalId": goal_id, "planKind": "save_up", "settingsJson": json.dumps({"monthlyContribution": contribution, "expectedAnnualReturn": growth})})
        overview = wf.request("GET", f"goals/{goal_id}/save-up/overview")
        goal = wf.request("GET", "goals/" + goal_id)
        goal.update({"description": f"模拟计划：每月储蓄 ¥{contribution:,}，观察目标进度与不同回报假设。",
                     "summaryCurrentValue": overview["currentValue"], "summaryProgress": overview["progress"],
                     "projectedValueAtTargetDate": overview["projectedValueAtTargetDate"],
                     "projectedCompletionDate": overview.get("projectedCompletionDate"), "statusHealth": overview["health"]})
        wf.request("PUT", "goals", goal)

    targets = wf.request("GET", "allocation-targets")
    target_name = "多资产配置目标（模拟假设）"
    found = next((t for t in targets if t["name"] == target_name), None)
    target_payload = {"id": found["id"] if found else None,
        "input": {"name": target_name, "scopeType": "portfolio", "scopeId": state["portfolios"]["全景投资组合（模拟）"],
                  "taxonomyId": "asset_classes", "triggerType": "threshold", "driftBandBps": 500,
                  "minTradeAmount": "1000", "wholeSharesOnly": False, "allowSells": False},
        "weights": [{"categoryId": cat, "targetBps": weight, "isLocked": False, "isRequired": True}
                    for cat, weight in [("EQUITY", 5500), ("FIXED_INCOME", 1500), ("COMMODITIES", 1500), ("CASH", 1200), ("DIGITAL_ASSETS", 300)]]}
    wf.request("POST", "allocation-targets/save-with-weights", target_payload)
    all_target_name = "全账户配置目标（模拟假设）"
    all_target = next((t for t in targets if t["name"] == all_target_name), None)
    target_payload["id"] = all_target["id"] if all_target else None
    target_payload["input"].update({"name": all_target_name, "scopeType": "all", "scopeId": None})
    wf.request("POST", "allocation-targets/save-with-weights", target_payload)
    # Names only: preserve the system taxonomy IDs/keys and all calculations.
    translated = {
        "asset_classes": {"CASH": "现金", "EQUITY": "股票权益", "FIXED_INCOME": "固定收益", "COMMODITIES": "黄金与商品", "REAL_ESTATE": "房地产", "ALTERNATIVES": "其他资产", "DIGITAL_ASSETS": "数字资产"},
        "regions": {"R10": "欧洲", "R20": "美洲", "R30": "亚洲", "R40": "非洲", "R50": "大洋洲"},
        "industries_gics": {"10": "能源", "15": "原材料", "20": "工业", "25": "可选消费", "30": "日常消费", "35": "医疗保健", "40": "金融", "45": "信息技术", "50": "通信服务", "55": "公用事业", "60": "房地产"},
        "risk_category": {"LOW": "较低", "MEDIUM": "中等", "HIGH": "较高", "UNKNOWN": "未分类"},
        "spending_categories": {"cat_housing": "住房与房贷", "cat_groceries": "超市生鲜", "cat_food": "餐饮咖啡", "cat_transport": "交通与车贷", "cat_shopping": "日用购物", "cat_entertainment": "休闲娱乐", "cat_health": "健康运动", "cat_bills": "水电网络", "cat_education": "学习进修", "cat_travel": "旅行度假", "cat_gifts": "人情礼赠", "cat_fees": "手续费", "cat_other_expense": "其他支出", "cat_personal": "个人护理"},
        "income_sources": {"cat_income_salary": "工资", "cat_income_bonus": "奖金", "cat_income_interest": "利息", "cat_income_dividends": "分红", "cat_income_other": "其他收入"},
        "savings_categories": {"cat_savings_investments": "投资定投", "cat_savings_emergency": "应急储备"},
    }
    for taxonomy, names in translated.items():
        for category in wf.request("GET", "taxonomies/" + taxonomy)["categories"]:
            if category["id"] in names and category["name"] != names[category["id"]]:
                wf.request("PUT", "taxonomies/categories", {**category, "name": names[category["id"]]})
    print("数据已写入，正在等待账户历史重算完成。", flush=True)
    wf.request("POST", "health/fix", {"id": "rebuild_account_history", "label": "Rebuild History",
        "payload": list(state["accounts"].values()) + [setup["accountId"]]})
    state["completedAt"] = datetime.now(timezone.utc).isoformat()
    save(state)
    after = fingerprint(wf, setup["personalProfileId"])
    assert before == after, "个人档案账本发生变化，请核对是否有用户同时编辑。"
    state["personalLedgerUnchanged"] = True
    save(state)
    wf.close()
    print("演示数据扩充完成；个人档案账户、流水、组合与目标保持不变。", flush=True)


if __name__ == "__main__":
    main()

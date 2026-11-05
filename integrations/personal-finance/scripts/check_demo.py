"""Read-only accounting and presentation checks for the expanded demo profile."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import json

from enrich_demo import TAG, fingerprint
from wf_client import ROOT, Wealthfolio


def main():
    state = json.loads((ROOT / "data/demo-rich-state.json").read_text())
    setup = json.loads((ROOT / "data/setup-state.json").read_text())
    wf = Wealthfolio()
    assert state["profileId"] != setup["personalProfileId"]
    wf.select(state["profileId"])
    accounts = wf.request("GET", "accounts")
    result = {"checkedAt": datetime.now(timezone.utc).isoformat(), "profileId": state["profileId"]}
    all_rows = wf.request("POST", "activities/search", {"page": 0, "pageSize": 10000})["data"]
    rows = [r for r in all_rows if (r.get("sourceRecordId") or "").startswith(TAG + ":")]
    assert len(rows) == state["activityCount"] == 464
    assert len({r["sourceRecordId"] for r in rows}) == len(rows), "重复模拟流水"
    assert all("模拟" in r["comment"] and r["status"] == "POSTED" for r in rows)
    pairs = defaultdict(list)
    expected_quantities = defaultdict(Decimal)
    expected_cash = defaultdict(Decimal)
    daily_cash = defaultdict(Decimal)
    cash_in = {"DEPOSIT", "TRANSFER_IN", "SELL", "DIVIDEND", "INTEREST"}
    for row in rows:
        account = row["accountId"]
        amount = Decimal(row["amount"] or "0")
        delta = amount if row["activityType"] in cash_in else -amount
        expected_cash[account] += delta
        daily_cash[(account, row["date"][:10])] += delta
        if row.get("sourceGroupId"):
            pairs[row["sourceGroupId"]].append(row)
        if row["activityType"] in ("BUY", "SELL"):
            expected_quantities[(account, row["assetId"])] += Decimal(row["quantity"]) * (1 if row["activityType"] == "BUY" else -1)
    assert len(pairs) == 44
    for pair in pairs.values():
        assert len(pair) == 2 and {p["activityType"] for p in pair} == {"TRANSFER_IN", "TRANSFER_OUT"}
        assert pair[0]["amount"] == pair[1]["amount"] and pair[0]["currency"] == pair[1]["currency"]
    balances = defaultdict(Decimal)
    for (account, day), delta in sorted(daily_cash.items()):
        balances[account] += delta
        assert balances[account] >= Decimal("-0.02"), ("出现负现金", account, day)
    holding_rows = []
    for account in accounts:
        holdings = wf.request("GET", "holdings", params={"accountId": account["id"]})
        holding_rows += holdings
        for holding in holdings:
            if holding["holdingType"] == "cash":
                assert abs(Decimal(str(holding["marketValue"]["local"])) - expected_cash[account["id"]]) <= Decimal("0.02"), "现金与流水不一致"
            else:
                expected = expected_quantities[(account["id"], holding["instrument"]["id"])]
                assert abs(Decimal(str(holding["quantity"])) - expected) < Decimal("0.000001"), "持仓数量与买卖流水不一致"
                computed = Decimal(str(holding["price"])) * expected
                assert abs(Decimal(str(holding["marketValue"]["local"])) - computed) <= Decimal("0.02"), "单位价格估值不一致"
    result.update({"accountCount": len(accounts), "distinctInvestmentAssets": len(state["assets"]),
                   "simulatedActivities": len(rows), "linkedTransfers": len(pairs),
                   "activityTypes": dict(Counter(r["activityType"] for r in rows)),
                   "positionsAndCashReconcile": True, "nonnegativeDailyCash": True})
    nw = wf.request("GET", "net-worth")
    assert abs(nw["assets"]["total"] - nw["liabilities"]["total"] - nw["netWorth"]) < 0.02
    assert nw["liabilities"]["total"] == 1227000
    history = wf.request("GET", "net-worth/history", params={"startDate": "2025-01-02", "endDate": "2026-11-01"})
    assert len(history) >= 600
    result.update({"netWorthCny": round(nw["netWorth"], 2), "netWorthHistoryPoints": len(history), "liabilitiesCny": nw["liabilities"]["total"]})
    report = wf.request("POST", "spending/report", {"startDate": "2026-10-01T00:00:00+08:00", "endDate": "2026-10-31T23:59:59+08:00"})
    assert report["current"]["income"] == 35142 and report["current"]["outflow"] == 25982
    assert report["current"]["saved"] == 4500
    assert len(report["spendingBreakdown"]) == 10
    assert all(r["categoryId"] != "__uncategorized__" for r in report["spendingBreakdown"] + report["savingsBreakdown"])
    result["octoberCashflow"] = report["current"]
    goals = wf.request("GET", "goals")
    own_goals = [g for g in goals if g["id"] in state["goals"].values()]
    assert len(own_goals) == 6
    assert all(g["summaryCurrentValue"] > 0 and g["statusHealth"] != "not_applicable" for g in own_goals)
    result["simulatedGoalStates"] = dict(Counter(g["statusHealth"] for g in own_goals))
    assert len(wf.request("GET", "allocation-targets")) >= 2
    health = wf.request("POST", "health/check", {})
    assert not health["issues"], [(i["code"], i["title"]) for i in health["issues"]]
    result["healthIssues"] = 0
    result["personalLedgerUnchanged"] = fingerprint(wf, setup["personalProfileId"]) == state["personalLedgerFingerprint"]
    assert result["personalLedgerUnchanged"]
    wf.close()
    (ROOT / "data/demo-rich-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

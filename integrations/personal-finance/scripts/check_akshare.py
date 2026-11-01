"""Read-only AKShare migration verification; does not reseed or refresh portfolios."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

import httpx

from wf_client import ROOT, Wealthfolio


def ledger_snapshot(wf):
    snapshot = {}
    for profile in wf.state()["profiles"]:
        if profile.get("lockEnabled"):
            continue
        wf.select(profile["id"])
        entities = {name: wf.request("GET", name) for name in (
            "accounts", "goals", "portfolios", "alternative-holdings")}
        entities["activities"] = wf.request("POST", "activities/search", {"page": 0, "pageSize": 10000})
        snapshot[profile["id"]] = {
            "name": profile["name"],
            "sha256": hashlib.sha256(json.dumps(entities, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "accounts": len(entities["accounts"]),
            "activities": entities["activities"]["meta"]["totalRowCount"],
        }
    return snapshot


def main():
    wf = Wealthfolio()
    try:
        before = json.loads((ROOT / "data/akshare-ledger-before.json").read_text())
        after = ledger_snapshot(wf)
        assert before == after, "账户、流水、目标、组合或非标资产与迁移前不一致"
        report = {"checked_at": datetime.now(timezone.utc).isoformat(),
            "ledger_unchanged": True, "profiles": after, "samples": []}
        baseline = ROOT / "data/akshare-baseline"
        with httpx.Client(trust_env=False, timeout=55) as client:
            health = client.get("http://127.0.0.1:8090/health").raise_for_status().json()
            assert health["engine"] == "akshare"
            report["engine_version"] = health["engine_version"]
            symbols = [p.stem for p in sorted(baseline.glob("*.json"))]
            assert {"600519.SS", "110022.OF", "AU9999.SGE", "518880.SS"} <= set(symbols)
            for symbol in symbols:
                latest = client.get(f"http://127.0.0.1:8090/v1/latest/{symbol}").raise_for_status().json()
                assert latest["engine"] == "akshare" and latest["engine_version"] == health["engine_version"]
                rows = client.get(f"http://127.0.0.1:8090/v1/history/{symbol}").raise_for_status().json()["prices"]
                current = {r["date"]: Decimal(str(r["close"])) for r in rows}
                old = json.loads((baseline / f"{symbol}.json").read_text())
                overlap = [r for r in old["rows"] if r["date"] in current]
                assert overlap, f"{symbol}: 无可比较历史"
                assert all(Decimal(str(r["close"])) == current[r["date"]] for r in overlap), f"{symbol}: 历史价格不同"
                report["samples"].append({k: latest[k] for k in (
                    "symbol", "date", "price", "unit", "source_function", "points")}
                    | {"compared_closes": len(overlap), "historical_prices_match": True})
        (ROOT / "data/akshare-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        wf.close()


if __name__ == "__main__":
    main()

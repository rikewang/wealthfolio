"""Read-only end-to-end verification of the installed demo. Prints public data only."""
from datetime import datetime, timezone
from decimal import Decimal
import json
import httpx
from wf_client import ROOT, Wealthfolio


def main():
    manifest = json.loads((ROOT / "data/setup-state.json").read_text())
    wf = Wealthfolio()
    wf.select(manifest["demoProfileId"])
    assets = manifest["assets"]
    latest = wf.request("POST", "market-data/quotes/latest", {"assetIds": [a["id"] for a in assets]})
    holdings = wf.request("GET", "holdings", params={"accountId": manifest["accountId"]})
    result = {"checkedAt": datetime.now(timezone.utc).isoformat(), "samples": []}
    with httpx.Client(trust_env=False, timeout=45) as client:
        unauthorized = client.get("http://127.0.0.1:8088/api/v1/assets")
        assert unauthorized.status_code in (401, 403), "未登录接口不应能访问资产"
        result["authRequired"] = True
        for asset in assets:
            response = client.get("http://127.0.0.1:8090/v1/latest/" + asset["symbol"])
            response.raise_for_status()
            public = response.json()
            quote = latest[asset["id"]]
            assert Decimal(str(quote["quote"]["close"])) == Decimal(str(public["price"])), asset["symbol"]
            assert quote["quoteDate"] == public["date"], "价格日期发生偏移"
            history = wf.request("GET", "market-data/quotes/history", params={"symbol": asset["id"]})
            assert len(history) >= 100, "历史同步尚未完成，请稍后重试"
            # Compare every persisted daily closing price against the original adapter series.
            response = client.get("http://127.0.0.1:8090/v1/history/" + asset["symbol"])
            response.raise_for_status()
            source_rows = {row["date"]: Decimal(str(row["close"])) for row in response.json()["prices"]}
            assert all(source_rows[row["timestamp"][:10]] == Decimal(str(row["close"])) for row in history)
            holding = next(h for h in holdings if h["instrument"]["id"] == asset["id"])
            expected = Decimal(str(public["price"])) * Decimal(str(holding["quantity"]))
            assert Decimal(str(holding["marketValue"]["local"])) == expected, "持仓计价单位错误"
            dates = [row["timestamp"][:10] for row in history]
            result["samples"].append({"symbol": asset["symbol"], "price": public["price"],
                "date": public["date"], "unit": public["unit"], "source": public["source"],
                "historyPoints": len(history), "historyStart": min(dates), "historyEnd": max(dates)})
    databases = list((ROOT / "data/wealthfolio/profiles").glob("*/app.db"))
    assert len(databases) >= 2
    for path in databases:
        with path.open("rb") as database:
            assert database.read(16) != b"SQLite format 3\x00", "检测到明文数据库"
    result["databaseHeadersEncrypted"] = True
    wf.select(manifest["personalProfileId"])
    result["personalAccountCount"] = len(wf.request("GET", "accounts"))
    wf.close()
    (ROOT / "data/verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

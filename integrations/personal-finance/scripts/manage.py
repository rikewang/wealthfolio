"""Small local operations CLI. No broker login, order execution or cloud sync."""
import argparse
from datetime import datetime
import os
import subprocess
import tarfile
import httpx
from bootstrap import PERSONAL, add_asset, classify
from wf_client import ROOT, Wealthfolio


def backup():
    os.umask(0o077)
    directory = ROOT / "backups"
    directory.mkdir(exist_ok=True)
    target = directory / f"person-finance-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    # A stopped writer guarantees a consistent SQLite + registry + vault snapshot.
    subprocess.run(["docker", "compose", "stop", "wealthfolio"], cwd=ROOT, check=True)
    try:
        with tarfile.open(target, "w:gz") as archive:
            for name in (".env", ".secrets/local-login-password.txt", "data/wealthfolio", "data/setup-state.json", "data/demo-rich-state.json", "data/demo-rich-verification.json", "compose.yml"):
                path = ROOT / name
                if path.exists():
                    archive.add(path, arcname=name)
        with tarfile.open(target) as archive:
            names = archive.getnames()
            assert ".env" in names and any(n.endswith("/app.db") for n in names)
        target.chmod(0o600)
        print(f"备份已创建：{target}\n包含加密密钥，请仅放在受保护的本地位置。")
    finally:
        subprocess.run(["docker", "compose", "start", "wealthfolio"], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("refresh", help="刷新所有档案的已登记行情")
    commands.add_parser("backup", help="停写后备份本地数据库和恢复所需密钥，再启动服务")
    add = commands.add_parser("add", help="在个人资产档案登记可跟踪证券，不创建持仓")
    add.add_argument("symbol", help="例如 000001.SZ、110022.OF、AU9999.SGE")
    add.add_argument("name", help="页面显示名称")
    add.add_argument("--type", choices=["stock", "fund", "etf", "gold"], required=True)
    args = parser.parse_args()
    if args.command == "backup":
        backup()
        return
    wf = Wealthfolio()
    if args.command == "refresh":
        for profile in wf.state()["profiles"]:
            if profile["lockEnabled"]:
                continue
            wf.select(profile["id"])
            assets = wf.request("GET", "assets")
            ids = [a["id"] for a in assets if a.get("quoteMode") == "MARKET"]
            if ids:
                wf.request("POST", "market-data/sync", {"assetIds": ids, "refetchAll": False})
        print("已提交增量行情刷新；请稍后在页面查看报价日期。")
    elif args.command == "add":
        symbol = args.symbol.upper()
        with httpx.Client(trust_env=False, timeout=45) as client:
            response = client.get("http://127.0.0.1:8090/v1/latest/" + symbol)
            response.raise_for_status()
            quote = response.json()
        profile = next(p for p in wf.state()["profiles"] if p["name"] == PERSONAL)
        wf.select(profile["id"])
        if symbol == "AU9999.SGE" and args.type != "gold":
            raise SystemExit("AU9999.SGE 请使用 --type gold，数量单位为克。")
        if symbol.endswith(".OF") and args.type != "fund":
            raise SystemExit("场外基金请使用 --type fund。")
        if args.type == "gold" and symbol != "AU9999.SGE":
            raise SystemExit("当前现货黄金仅支持 AU9999.SGE；黄金ETF 使用 --type etf。")
        mic = "XSHG" if symbol.endswith(".SS") else "XSHE" if symbol.endswith(".SZ") else None
        asset = add_asset(wf, symbol, args.name, "METAL" if args.type == "gold" else "EQUITY", mic)
        classify(wf, asset["id"], "instrument_type", {"stock": "STOCK_COMMON", "fund": "FUND_MUTUAL", "etf": "ETF", "gold": "PHYSICAL_METAL"}[args.type])
        if args.type in ("etf", "fund"):
            print("请在界面的资产分类中核对股票/债券/商品等底层风险敞口。")
        wf.request("POST", "market-data/sync", {"assetIds": [asset["id"]], "refetchAll": False, "refetchRecentDays": 1825})
        print(f"已登记 {symbol} {args.name}；最新 {quote['price']} {quote['unit']}，日期 {quote['date']}。未创建持仓。")
    wf.close()


if __name__ == "__main__":
    main()

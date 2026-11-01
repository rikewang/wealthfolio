import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from market_data import app as feed
from market_data.akshare_worker import map_rows, require_unadjusted

NOW = datetime(2026, 10, 31, 12, tzinfo=feed.SHANGHAI)


class DataSemanticsTests(unittest.TestCase):
    def test_fund_uses_unit_nav_and_shanghai_date_not_accumulated_nav(self):
        timestamp = datetime(2026, 10, 30, tzinfo=feed.SHANGHAI).timestamp() * 1000
        text = 'var Data_ACWorthTrend=[[0,99]];var Data_netWorthTrend=' + json.dumps([
            {"x": timestamp, "y": 2.871, "equityReturn": 2.35}]) + ';evil();'
        self.assertEqual(feed.parse_fund(text, NOW), [{"date": "2026-10-30", "close": 2.871}])

    def test_gold_close_is_third_column_and_not_converted_to_ounces(self):
        result = feed.parse_sge({"time": [["2026-10-30", 863.8, 854.76, 853.5, 867.0]]}, NOW)
        self.assertEqual(result[0]["close"], 854.76)
        self.assertEqual(result[0]["low"], 853.5)
        self.assertEqual(10 * result[0]["close"], 8547.6)

    def test_reject_adjusted_stock_prices_and_exclude_unfinished_bar(self):
        point = ["2026-10-30", "10", "11", "12", "9", "20"]
        with self.assertRaises(ValueError):
            feed.parse_tencent({"code": 0, "data": {"sh600519": {"qfqday": [point]}}}, "sh600519", NOW)
        rows = feed.parse_tencent({"code": 0, "data": {"sh600519": {"day": [point,
            ["2026-10-31", "10", "11", "12", "9", "20"]]}}}, "sh600519", NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["volume"], 2000)

    def test_dates_sort_deduplicate_and_conflicts_fail(self):
        rows = [{"date": "2026-10-30", "close": 2}, {"date": "2026-10-29", "close": 1}]
        self.assertEqual(feed.clean_rows(rows + [rows[0]], NOW)[0]["close"], 1)
        with self.assertRaises(ValueError):
            feed.clean_rows(rows + [{"date": "2026-10-30", "close": 3}], NOW)
        for price in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                feed.clean_rows([{"date": "2026-10-30", "close": price}], NOW)

    def test_stale_and_future_quotes_never_relabel_as_today(self):
        data = {"rows": [{"date": "2026-10-01", "close": 1}]}
        with self.assertRaises(HTTPException) as ctx:
            feed.latest_payload(data, date(2026, 10, 31))
        self.assertEqual(ctx.exception.status_code, 503)
        data["rows"][0]["date"] = "2026-11-01"
        with self.assertRaises(HTTPException):
            feed.latest_payload(data, date(2026, 10, 31))

    def test_bad_symbols_cannot_be_used_as_paths_or_arbitrary_urls(self):
        for symbol in ("../../.env", "https://example.com", "600519", "600519.SS?x=1"):
            with self.assertRaises(ValueError):
                feed.normalized_symbol(symbol)

    def test_upstream_failure_does_not_return_expired_cache(self):
        old = {"fetched_at": "2000-01-01T00:00:00+00:00", "rows": [{"date": "2000-01-01", "close": 1}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "600519.SS.json"
            path.write_text(json.dumps(old))
            with patch.object(feed, "CACHE", Path(tmp)), patch.object(feed, "fetch_series",
                    AsyncMock(side_effect=httpx.ConnectError("offline"))):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(feed.series("600519.SS"))
            self.assertEqual(ctx.exception.status_code, 502)
            self.assertEqual(json.loads(path.read_text()), old)

    def test_api_date_filter_and_invalid_range(self):
        data = {"rows": [{"date": "2026-10-29", "close": 1}, {"date": "2026-10-30", "close": 2}]}
        with TestClient(feed.app) as client, patch.object(feed, "series", AsyncMock(return_value=data)):
            good = client.get("/v1/history/600519.SS?from=2026-10-30&to=2026-10-30")
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.json()["prices"], [data["rows"][1]])
            self.assertEqual(client.get("/v1/history/600519.SS?from=2026-10-31&to=2026-10-30").status_code, 400)

    def test_akshare_mapping_preserves_nav_and_gold_units(self):
        nav = map_rows([{"净值日期": date(2026, 10, 30), "单位净值": 2.871,
            "累计净值": 99}], "110022.OF", NOW)
        self.assertEqual(feed.clean_rows(nav, NOW), [{"date": "2026-10-30", "close": 2.871}])
        bar = {"date": date(2026, 10, 30), "open": 863.8, "close": 854.76,
            "low": 853.5, "high": 867, "volume": 123}
        gold = feed.clean_rows(map_rows([bar], "AU9999.SGE", NOW), NOW)
        self.assertEqual(gold[0]["close"] * 10, 8547.6)
        self.assertNotIn("volume", gold[0])
        bar["date"] = NOW.date()
        self.assertEqual(map_rows([bar], "600519.SS", NOW), [])

    def test_akshare_adjusted_fallback_is_blocked(self):
        for key in ("qfqday", "hfqday"):
            with self.assertRaises(ValueError):
                require_unadjusted({"code": 0, "data": {"sh600519": {key: [[1]]}}}, "sh600519")
        require_unadjusted({"code": 0, "data": {"sh600519": {"day": [[1]]}}}, "sh600519")

    def test_new_engine_never_reuses_fresh_legacy_cache(self):
        old = {"fetched_at": datetime.now(feed.timezone.utc).isoformat(),
            "rows": [{"date": "2026-10-30", "close": 1}]}
        fresh = {**old, "engine": "akshare", "engine_version": feed.ENGINE_VERSION}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "600519.SS.json"
            path.write_text(json.dumps(old))
            fetch = AsyncMock(return_value=fresh)
            with patch.object(feed, "CACHE", Path(tmp)), patch.object(feed, "fetch_series", fetch):
                result = asyncio.run(feed.series("600519.SS"))
            fetch.assert_awaited_once()
            self.assertEqual(result["engine"], "akshare")

    def test_hung_akshare_worker_is_killed_and_slot_released(self):
        async def check():
            process = AsyncMock()
            process.returncode = None
            process.kill = unittest.mock.Mock()
            async def hang():
                await asyncio.sleep(60)
            process.communicate.side_effect = hang
            slots = asyncio.Semaphore(1)
            with patch.object(feed, "workers", slots), patch.object(feed, "WORKER_TIMEOUT", 0.01), \
                    patch.object(feed.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
                with self.assertRaises(TimeoutError):
                    await feed.fetch_series("600519.SS")
            process.kill.assert_called_once()
            process.wait.assert_awaited_once()
            self.assertFalse(slots.locked())
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()

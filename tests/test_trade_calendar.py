"""data.trade_calendar 单元测试（离线：mock 数据源与校验）。

覆盖：新浪主源 → Tushare 兜底 → 缓存复用 → 工作日回退；
不完整的接口返回绝不写入缓存。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import data.trade_calendar as tc

SINA_DATES = sorted(
    d.strftime("%Y%m%d")
    for d in pd.date_range("20260601", "20260915")
    if d.weekday() < 5
)  # 近 90 天工作日，约 76 个，满足缓存可用性阈值
TUSHARE_CAL = pd.DataFrame([
    {"cal_date": "20260911", "is_open": 1},
    {"cal_date": "20260914", "is_open": 1},
    {"cal_date": "20260915", "is_open": 1},
])


class TestRefreshCalendar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cal_path = os.path.join(self.tmp, "cal.parquet")
        self.patch_path = mock.patch.object(tc, "CALENDAR_FILE", self.cal_path)
        self.patch_path.start()
        self.addCleanup(self.patch_path.stop)

    def test_sina_primary_writes_cache(self):
        with mock.patch.object(tc, "_sina_dates", return_value=list(SINA_DATES)), \
             mock.patch.object(tc, "_validate", return_value=True):
            df = tc.refresh_calendar("20260915")
        self.assertEqual(len(df), len(SINA_DATES))
        self.assertTrue(os.path.exists(self.cal_path))
        got = pd.read_parquet(self.cal_path)
        self.assertEqual(got["is_open"].tolist(), [1] * len(SINA_DATES))

    def test_sina_invalid_falls_back_to_tushare(self):
        with mock.patch.object(tc, "_sina_dates", return_value=list(SINA_DATES)), \
             mock.patch.object(tc, "_validate", return_value=False), \
             mock.patch.object(tc.pro, "trade_cal", return_value=TUSHARE_CAL.copy()):
            df = tc.refresh_calendar("20260915")
        self.assertEqual(df["cal_date"].tolist(),
                         ["20260911", "20260914", "20260915"])

    def test_incomplete_tushare_response_not_written(self):
        """trade_cal 返回不覆盖 end（如服务端截断为最近 3 行且不含 end）→ 不写缓存。"""
        bad = pd.DataFrame([{"cal_date": "20260911", "is_open": 1}])
        with mock.patch.object(tc, "_sina_dates", return_value=list(SINA_DATES)), \
             mock.patch.object(tc, "_validate", return_value=False), \
             mock.patch.object(tc.pro, "trade_cal", return_value=bad):
            with self.assertRaises(RuntimeError):
                tc.refresh_calendar("20260915")
        self.assertFalse(os.path.exists(self.cal_path))

    def test_broken_small_cache_is_not_used(self):
        """3 行坏缓存即使 max 覆盖 end 也不可信 → 触发刷新而非直接复用。"""
        broken = pd.DataFrame({"cal_date": ["20260911", "20260914", "20260915"],
                               "is_open": [1, 1, 1]})
        broken.to_parquet(self.cal_path, index=False)
        with mock.patch.object(tc, "_sina_dates", return_value=list(SINA_DATES)), \
             mock.patch.object(tc, "_validate", return_value=True):
            df = tc.refresh_calendar("20260915")
        self.assertEqual(len(df), len(SINA_DATES))

    def test_fresh_cache_used_without_fetch(self):
        cache = pd.DataFrame({"cal_date": SINA_DATES, "is_open": 1})
        cache.to_parquet(self.cal_path, index=False)
        with mock.patch.object(tc, "_sina_dates", side_effect=AssertionError("不应被调用")), \
             mock.patch.object(tc.pro, "trade_cal", side_effect=AssertionError("不应被调用")):
            df = tc.refresh_calendar("20260915")
        self.assertEqual(len(df), len(SINA_DATES))


class TestGetTradeDates(unittest.TestCase):
    def test_weekday_fallback_when_all_sources_fail(self):
        with mock.patch.object(tc, "refresh_calendar", side_effect=RuntimeError):
            dates = tc.get_trade_dates("20260911", "20260914")
        self.assertEqual(dates, ["20260911", "20260914"])

    def test_mask_from_calendar(self):
        cal = pd.DataFrame({
            "cal_date": ["20260911", "20260912", "20260914", "20260915"],
            "is_open": [1, 0, 1, 1],
        })
        with mock.patch.object(tc, "refresh_calendar", return_value=cal):
            dates = tc.get_trade_dates("20260911", "20260915")
        self.assertEqual(dates, ["20260911", "20260914", "20260915"])


class TestConsoleEncoding(unittest.TestCase):
    def test_stdout_reconfigured_to_utf8(self):
        """模块导入后 stdout/stderr 已按 UTF-8 重配置（GBK 控制台下打印 ⚠️ 不再崩溃）。"""
        self.assertEqual(sys.stdout.encoding, "utf-8")


class TestMissingTradeDates(unittest.TestCase):
    def test_finds_missing_days(self):
        cal = pd.DataFrame({
            "cal_date": ["20260911", "20260914", "20260915"],
            "is_open": [1, 1, 1],
        })
        have = pd.Series(["20260911", "20260915"])
        with mock.patch.object(tc, "refresh_calendar", return_value=cal):
            missing = tc.missing_trade_dates(have, "20260911", "20260915")
        self.assertEqual(missing, ["20260914"])


if __name__ == "__main__":
    unittest.main()

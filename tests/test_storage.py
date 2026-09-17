"""data.storage 单元测试：原子写 + 去重追加。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from data.storage import atomic_save, append_dedupe


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "test.parquet")

    def _df(self, codes_dates):
        return pd.DataFrame(
            [{"ts_code": c, "trade_date": d, "close": 1.0}
             for c, d in codes_dates]
        )

    def test_atomic_save_creates_file(self):
        df = self._df([("000001.SZ", "20260915")])
        atomic_save(df, self.path)
        got = pd.read_parquet(self.path)
        self.assertEqual(len(got), 1)
        self.assertEqual(got.iloc[0]["ts_code"], "000001.SZ")

    def test_append_dedupe_new_file(self):
        df = self._df([("000001.SZ", "20260912"), ("000001.SZ", "20260915")])
        append_dedupe(df, self.path)
        got = pd.read_parquet(self.path)
        self.assertEqual(len(got), 2)
        # 按 key 排序
        self.assertEqual(got.iloc[0]["trade_date"], "20260912")

    def test_append_dedupe_merges_and_removes_duplicates(self):
        append_dedupe(self._df([("000001.SZ", "20260912")]), self.path)
        append_dedupe(self._df([("000001.SZ", "20260912"),
                                ("000002.SZ", "20260915")]), self.path)
        got = pd.read_parquet(self.path)
        self.assertEqual(len(got), 2)
        codes = set(got["ts_code"])
        self.assertEqual(codes, {"000001.SZ", "000002.SZ"})

    def test_append_dedupe_handles_int_trade_date(self):
        """旧文件 trade_date 可能是非字符串类型，需统一后再去重。"""
        df = self._df([("000001.SZ", "20260912")])
        df.to_parquet(self.path, index=False)
        new = pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260912", "close": 1.0}])
        new["trade_date"] = 20260912  # int 类型
        append_dedupe(new, self.path)
        got = pd.read_parquet(self.path)
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()

"""data.sina_factor 单元测试：因子链解析与合成。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.sina_factor import parse_chain, factor_at, synth_factors


FAKE_JS = (
    'var sz000001qfq={"total":3,"data":'
    '[{"d":"2026-06-12", "f":"1.0000000000000000"},'
    '{"d":"2025-10-15", "f":"1.0329067641682"},'
    '{"d":"1900-01-01", "f":"1.0329067641682"}]}'
)


class TestParseChain(unittest.TestCase):
    def test_parse(self):
        chain = parse_chain(FAKE_JS)
        self.assertEqual(len(chain), 3)
        # 日期倒序
        self.assertEqual([c[0] for c in chain],
                         ["20260612", "20251015", "19000101"])
        self.assertAlmostEqual(chain[0][1], 1.0)


class TestFactorAt(unittest.TestCase):
    def setUp(self):
        self.chain = parse_chain(FAKE_JS)

    def test_between_events(self):
        # 20251015 ~ 20260611 之间用上一档因子
        self.assertAlmostEqual(factor_at(self.chain, "20260430"), 1.03290676)
        self.assertAlmostEqual(factor_at(self.chain, "20251015"), 1.03290676)

    def test_after_latest_event(self):
        self.assertAlmostEqual(factor_at(self.chain, "20260612"), 1.0)
        self.assertAlmostEqual(factor_at(self.chain, "20260915"), 1.0)

    def test_before_oldest(self):
        # 1900 哨兵之前的日期（不会发生，但逻辑应返回哨兵值）
        self.assertAlmostEqual(factor_at(self.chain, "19900101"), 1.03290676)


class TestSynthFactors(unittest.TestCase):
    def setUp(self):
        self.chain = parse_chain(FAKE_JS)

    def test_anchor_and_jump(self):
        """F(d) = F0 × f(d0)/f(d)：除权日因子跳变，此前不变。"""
        dates = ["20260506", "20260611", "20260612", "20260915"]
        rows = synth_factors(self.chain, dates, "20260430", 134.5794)
        got = dict(rows)
        # 除权日前：因子不变
        self.assertAlmostEqual(got["20260506"], 134.5794, places=4)
        self.assertAlmostEqual(got["20260611"], 134.5794, places=4)
        # 除权日及之后：跳变 1.03290676
        self.assertAlmostEqual(got["20260612"], 134.5794 * 1.03290676, places=4)
        self.assertAlmostEqual(got["20260915"], 134.5794 * 1.03290676, places=4)

    def test_no_gap(self):
        rows = synth_factors(self.chain, ["20260301", "20260430"], "20260430", 1.0)
        self.assertEqual(rows, [])

    def test_new_listing_anchor(self):
        """无 Tushare 锚点的新股：以上市日为 d0、F0=1.0，链只有 1900 哨兵。"""
        chain = [("19000101", 1.0)]
        dates = ["20260701", "20260801"]
        rows = synth_factors(chain, dates, "20260701", 1.0)
        got = dict(rows)
        # 上市日无因子行（ffill 从锚点继承 F0），之后的交易日因子 = 1.0
        self.assertNotIn("20260701", got)
        self.assertAlmostEqual(got["20260801"], 1.0, places=6)

    def test_new_listing_with_event(self):
        """新股上市后发生除权：锚点后因子跳变。"""
        chain = [("20260810", 1.0), ("19000101", 1.5)]
        dates = ["20260801", "20260811"]
        rows = synth_factors(chain, dates, "20260730", 1.0)
        got = dict(rows)
        # F(0801) = 1.0×1.5/1.5 = 1.0；除权后 F = 1.0×1.5/1.0 = 1.5
        self.assertAlmostEqual(got["20260801"], 1.0, places=6)
        self.assertAlmostEqual(got["20260811"], 1.5, places=6)


if __name__ == "__main__":
    unittest.main()

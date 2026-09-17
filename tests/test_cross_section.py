"""quant/cross_section 单元测试：横截面标准化与因子方向反转。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from quant.cross_section import direction_sign, rank_score, standardize, zscore
from quant.factors.base import HIGHER_BETTER, LOWER_BETTER


class TestZscore(unittest.TestCase):
    def test_known_values(self):
        """[1,2,3,4]：mean=2.5，总体 std=sqrt(1.25)。"""
        z = zscore(pd.Series([1.0, 2.0, 3.0, 4.0]))
        expected = (np.array([1.0, 2.0, 3.0, 4.0]) - 2.5) / np.sqrt(1.25)
        for got, want in zip(z, expected):
            self.assertAlmostEqual(got, want, places=6)

    def test_nan_preserved(self):
        z = zscore(pd.Series([1.0, 2.0, np.nan, 4.0]))
        self.assertTrue(pd.isna(z.iloc[2]))
        self.assertFalse(pd.isna(z.iloc[0]))

    def test_constant_series_zero(self):
        z = zscore(pd.Series([5.0, 5.0, 5.0]))
        self.assertTrue((z == 0.0).all())

    def test_all_nan_stays_nan(self):
        z = zscore(pd.Series([np.nan, np.nan]))
        self.assertTrue(z.isna().all())


class TestRankScore(unittest.TestCase):
    def test_percentile_mapped_to_neg1_pos1(self):
        r = rank_score(pd.Series([10.0, 20.0, 30.0, 40.0]))
        expected = pd.Series([-0.5, 0.0, 0.5, 1.0])
        pd.testing.assert_series_equal(r.reset_index(drop=True), expected)

    def test_nan_preserved(self):
        r = rank_score(pd.Series([1.0, np.nan, 2.0]))
        self.assertTrue(pd.isna(r.iloc[1]))


class TestStandardize(unittest.TestCase):
    def test_dispatches_to_zscore_and_rank(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0])
        pd.testing.assert_series_equal(standardize(s, "zscore"), zscore(s))
        pd.testing.assert_series_equal(standardize(s, "rank"), rank_score(s))
        pd.testing.assert_series_equal(standardize(s), zscore(s))  # 默认 zscore

    def test_unknown_method_raises(self):
        with self.assertRaises(ValueError):
            standardize(pd.Series([1.0]), "minmax")


class TestDirection(unittest.TestCase):
    def test_signs(self):
        self.assertEqual(direction_sign(HIGHER_BETTER), 1.0)
        self.assertEqual(direction_sign(LOWER_BETTER), -1.0)

    def test_unknown_direction_raises(self):
        with self.assertRaises(ValueError):
            direction_sign("sideways")

    def test_lower_better_reversal(self):
        """低波动率股票标准化后得分应为正：z * (-1)。"""
        raw = pd.Series([0.01, 0.02, 0.03, 0.04])   # 波动率
        z = zscore(raw)
        adjusted = z * direction_sign(LOWER_BETTER)
        # 最低波动率 → 最高得分
        self.assertEqual(adjusted.idxmax(), raw.idxmin())


if __name__ == "__main__":
    unittest.main()

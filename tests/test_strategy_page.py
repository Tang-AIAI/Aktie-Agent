"""多策略「量化策略」页面测试（streamlit.testing.v1.AppTest + 真实数据）。

覆盖：
- 策略选择器 6 项；切换策略后因子控件数量与默认值随策略定义变化
- A/D/E/F 点击「重新计算」全部正常出排名（无异常、Top 10 出现）
- B/C 显示数据不足原因 + 按钮禁用（不计算、不报错）
- 切换策略后旧结果不展示（提示重新计算）
- 回测页回归：选择器 6 项、B/C 同样禁用

注意：本文件依赖真实数据文件（项目根 parquet）与 streamlit testing 运行时；
不联网、不修改任何数据。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit.testing.v1 import AppTest

BASE = Path(__file__).resolve().parent.parent
PAGE_LIVE = BASE / "app" / "pages" / "2_量化策略.py"
PAGE_BACKTEST = BASE / "app" / "pages" / "4_回测.py"


def live_app() -> AppTest:
    return AppTest.from_file(str(PAGE_LIVE), default_timeout=120)


def pick_strategy(at: AppTest, name: str) -> AppTest:
    """按策略注册名选择（AppTest select() 接受原始值；options 显示的是标签）。"""
    at.sidebar.selectbox[0].select(name)
    return at.run()


class TestStrategySelector(unittest.TestCase):
    def test_selector_has_six_strategies(self):
        at = live_app().run()
        self.assertEqual(len(at.sidebar.selectbox), 1)
        options = at.sidebar.selectbox[0].options
        self.assertEqual(len(options), 6)
        self.assertEqual(options[0], "Strategy A")
        self.assertIn("Strategy F（Trend 趋势）", options)
        # B/C 标注数据不足
        self.assertIn("Strategy B（Value 价值）（数据不足）", options)
        self.assertIn("Strategy C（Quality 质量）（数据不足）", options)

    def test_default_is_strategy_a_with_its_factors(self):
        at = live_app().run()
        # A：4 个因子 → 权重 4 + 窗口 5（量能趋势双窗口）= 9 个数值输入
        self.assertEqual(len(at.sidebar.number_input), 9)
        labels = [ni.label for ni in at.sidebar.number_input]
        self.assertIn("动量 权重（%）", labels)
        self.assertIn("相对强度 权重（%）", labels)
        self.assertIn("短期窗口（日）", labels)   # 量能趋势

    def test_a_factor_defaults_from_definitions(self):
        at = live_app().run()
        by_label = {ni.label: ni.value for ni in at.sidebar.number_input}
        self.assertEqual(by_label.get("动量 权重（%）"), 25)
        self.assertEqual(by_label.get("窗口（日）", "sentinel"), 60)  # 动量窗口 60
        self.assertEqual(by_label.get("短期窗口（日）"), 20)
        self.assertEqual(by_label.get("长期窗口（日）"), 60)

    def test_switching_strategy_changes_factor_widgets(self):
        """D：1 因子（1 权重 + 1 窗口 = 2 个输入，权重默认 100）；E：2 个；
        F：3 个（双窗口 20/60 + 权重 100）——全部来自策略/因子定义，非硬编码。"""
        at = live_app().run()
        pick_strategy(at, "strategy_d")
        self.assertEqual(len(at.sidebar.number_input), 2)
        by_label = {ni.label: ni.value for ni in at.sidebar.number_input}
        self.assertEqual(by_label.get("短期反转 权重（%）"), 100)
        self.assertEqual(by_label.get("窗口（日）"), 5)

        pick_strategy(at, "strategy_e")
        self.assertEqual(len(at.sidebar.number_input), 2)
        by_label = {ni.label: ni.value for ni in at.sidebar.number_input}
        self.assertEqual(by_label.get("波动率 权重（%）"), 100)
        self.assertEqual(by_label.get("窗口（日）"), 20)

        pick_strategy(at, "strategy_f")
        self.assertEqual(len(at.sidebar.number_input), 3)
        by_label = {ni.label: ni.value for ni in at.sidebar.number_input}
        self.assertEqual(by_label.get("趋势 权重（%）"), 100)
        self.assertEqual(by_label.get("短期窗口（日）"), 20)
        self.assertEqual(by_label.get("长期窗口（日）"), 60)


class TestUnavailableStrategies(unittest.TestCase):
    def test_b_shows_reason_and_disables_run(self):
        at = pick_strategy(live_app().run(), "strategy_b")
        reasons = " ".join(e.value for e in at.error)
        self.assertIn("缺少历史 PIT 估值数据", reasons)
        self.assertIn("暂不能可靠实现", reasons)
        self.assertTrue(at.sidebar.button[0].disabled)
        self.assertEqual(at.exception, [])          # 不报错
        # 不产生任何排名输出
        self.assertFalse(any(s.value == "最新排名 Top 10" for s in at.subheader))

    def test_c_shows_reason_and_disables_run(self):
        at = pick_strategy(live_app().run(), "strategy_c")
        reasons = " ".join(e.value for e in at.error)
        self.assertIn("缺少历史 PIT 财务数据", reasons)
        self.assertTrue(at.sidebar.button[0].disabled)
        self.assertEqual(at.exception, [])


class TestLiveCompute(unittest.TestCase):
    """A/D/E/F 真实数据计算（每次约 2~3s），验证统一 Engine 接入。"""

    def _compute_and_assert(self, name: str):
        at = pick_strategy(live_app().run(), name)
        self.assertFalse(at.sidebar.button[0].disabled)
        at.sidebar.button[0].click().run()
        self.assertEqual(at.exception, [], f"{name} 计算出现异常")
        self.assertTrue(any(s.value == "最新排名 Top 10" for s in at.subheader),
                        f"{name} 未产出 Top 10")
        self.assertNotIn("股票池为空", " ".join(w.value for w in at.warning))
        # 指标行显示非零股票池
        metrics = [m.value for m in at.metric]
        self.assertGreater(int(metrics[1]), 0, f"{name} 股票池为空")

    def test_strategy_a_computes(self):
        self._compute_and_assert("strategy_a")

    def test_strategy_d_computes(self):
        self._compute_and_assert("strategy_d")

    def test_strategy_e_computes(self):
        self._compute_and_assert("strategy_e")

    def test_strategy_f_computes(self):
        self._compute_and_assert("strategy_f")

    def test_switching_strategy_discards_stale_result(self):
        """先算 A，再切到 D：旧结果不展示，提示重新计算。"""
        at = live_app().run()
        at.sidebar.button[0].click().run()      # 默认 A 计算
        self.assertTrue(any(s.value == "最新排名 Top 10" for s in at.subheader))
        pick_strategy(at, "strategy_d")
        self.assertFalse(any(s.value == "最新排名 Top 10" for s in at.subheader))
        self.assertTrue(any("点击「重新计算」" in i.value for i in at.info))


class TestBacktestPageRegression(unittest.TestCase):
    """回测页不受影响：选择器 6 项、B/C 禁用、可正常运行 A。"""

    def test_selector_and_unavailable(self):
        at = AppTest.from_file(str(PAGE_BACKTEST), default_timeout=120).run()
        self.assertEqual(len(at.sidebar.selectbox[0].options), 6)
        pick_strategy(at, "strategy_b")
        self.assertTrue(at.sidebar.button[0].disabled)
        self.assertIn("缺少历史 PIT 估值数据", " ".join(e.value for e in at.error))
        self.assertEqual(at.exception, [])

    def test_strategy_f_sidebar_present(self):
        at = AppTest.from_file(str(PAGE_BACKTEST), default_timeout=120).run()
        pick_strategy(at, "strategy_f")
        labels = [ni.label for ni in at.sidebar.number_input]
        self.assertIn("趋势 权重（%）", labels)
        self.assertIn("短期窗口（日）", labels)


if __name__ == "__main__":
    unittest.main()

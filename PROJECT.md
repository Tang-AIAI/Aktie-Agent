# PROJECT — 个人股票量化研究 Web App

## 定位

个人股票投资研究与量化分析 Web App（主要通过电脑浏览器使用）。
核心：利用历史股票数据进行量化研究、策略计算、条件选股，辅助个人投资研究。

不是：行情软件 / 账户管理 / 自动交易系统。

v1 明确不做：AI 推荐、自动交易、券商 API、新闻系统、手机 App、实时行情页、复杂 ML、付费数据、自然语言选股。

## 技术栈

- Python 3.13（`.venv`）
- Streamlit（默认多页模式；**不使用 st.navigation**——实测 1.55 上会破坏 URL 路由）
- 数据：Parquet 文件（项目根目录）+ 状态文件（positions.csv / screener_state.json）
- 数据源：Tushare Pro（个股日线/指数，主）+ AkShare（指数 fallback、新浪交易日历）+ 新浪 qfq.js（复权因子回补）
- 测试：标准库 unittest + headless Edge/Playwright 浏览器冒烟

## 目录结构

```
quant/
├── data/        数据访问层：paths / storage / adj_data / trade_calendar / sina_factor / index_data
├── scripts/     update_stock_data / update_index_data / rebuild_adj / check_data / validate_adj
│                backfill_adj_factor（Tushare官方回补，备用）/ backfill_adj_factor_sina（新浪回补）
├── app/         Web App：Home.py（首页 Dashboard）+ common.py（共享工具：计算缓存/持仓/更新流水线）
│                pages/：1_数据管理 / 2_量化策略（Strategy A）/ 3_条件选股 / 4_回测（历史回测）
├── quant/       量化引擎：market_data（区间+列裁剪读取带缓存 + 数据状态）/ cross_section（横截面标准化）
│                factors/（因子注册表 + 6 个因子，含 needs_index 标记）/ strategies/（A~F 策略注册表，
│                B/C 为数据不足设计壳）/ engine（统一计算流程）/ backtest/（metrics / portfolio /
│                runner 回测主循环，PIT 股票池防泄漏）/ screener（选股指标注册表，纯逻辑可单测）
├── tests/       单元测试（85 个用例）
├── old_code/    废弃历史代码（只作参考，不迁移）
├── backup_20260915/  2026-09-15 修复前数据全量备份
└── *.parquet    数据文件（项目根目录）
```

## Web App 页面

- **首页**：数据状态（是否最新+原因）· 量化系统（Strategy A Top 10）· 当前持仓
  （手工维护 + 估值）· 条件选股入口；主线"数据 → 量化 → 筛选 → 研究"
- **数据管理**：五类数据状态/来源/最新日行数 + 一键更新（子进程跑现有 scripts/，
  日志实时流式 + 完成后持久化展示，失败如实上报；沪深300 与完整性检查各设
  3 分钟超时监督，个股日线因断点续传不设限）
- **量化策略**：统一多策略实时排名——策略选择器（A~F；B/C 显示数据不足并禁用），
  因子参数/窗口/权重按所选策略动态渲染（默认值取自策略定义），Top 10 + 完整排名 +
  个股因子构成（与回测页共用同一 Engine 与侧边栏组件）
- **条件选股**：可视化条件构建器（12 个指标 × 6 种运算符 × 数值/指标右值 ×
  AND/OR/NOT，自上而下组合无优先级），结果含代码/名称/最新价格/相关指标值
- **回测**：策略历史回测（策略选择器 A~F）——区间/Top N/调仓周期/单边成本/权重窗口
  可调；调仓日收盘排名（PIT 股票池）→ 次日开盘成交（停牌不成交）→ 每日收盘估值
  （停牌 ffill）；显示累计/年化/最大回撤/胜率、沪深300 对比与超额收益、净值曲线、
  调仓记录、参数快照与数据版本。数据不足的策略（B/C）显示原因并禁用运行。
  防未来数据泄漏口径见 `quant/backtest/runner.py` 模块注释与 PROJECT_CONTEXT.md

## 策略库（A~F，统一引擎，Baseline 参数非最优）

| 策略 | 定义 | 状态 |
|---|---|---|
| A 多因子 | 动量 25% + 波动率 25% + 量能趋势 25% + 相对强度 25%（60/20/20-60/60 日） | ✅ 可回测（RS≡Momentum 见下） |
| B 价值 | 低 PE/PB/股息率（设计：PE_TTM 50% / PB 30% / 股息率 20%） | ⛔ 缺历史 PIT 估值数据，仅设计说明 |
| C 质量 | ROE/毛利率/盈利稳定性/负债率（设计：40/20/20/20%） | ⛔ 缺历史 PIT 财务数据，仅设计说明 |
| D 反转 | 5 日收益率越低越好（超跌反弹；与动量同口径反向） | ✅ 可回测 |
| E 低波动 | 20 日收益率标准差越低越好（复用 A 的 volatility 因子） | ✅ 可回测 |
| F 趋势 | MA20/MA60 − 1 越高越好（20 日均线在 60 日上方） | ✅ 可回测 |

全部策略统一走 engine → 排名 → backtest；数据可用性审计、B/C 设计说明与
数据依赖见 PROJECT_CONTEXT.md「策略库」一节。本阶段不做参数寻优，默认参数
仅为合理 Baseline。

## 量化引擎（Strategy A，baseline）

- 四因子等权 25%：Momentum（60 日收益）、Volatility（20 日收益标准差，越低越好）、
  Volume Trend（20/60 日均量比）、Relative Strength（个股 − 沪深300 的 60 日收益差）
- 流程：按窗口区间读取数据（不读全量历史）→ 逐因子原始值 → 股票池过滤
  （无当日行情 / 因子 NaN / 不在 stock_list 的股票排除）→ 池内横截面 z-score →
  "越低越好"因子乘 −1 → Score = Σ(标准化因子 × 权重) → 降序排名
- 权重（自动归一化）与窗口均可调，页面点「重新计算」生效；因子注册表支持扩展 Strategy B/C
- **未经过历史回测验证** → **已回测（2026-09-17）**：默认参数 5 年（2021-09~2026-09）
  组合累计 −96.1%、同期沪深300 −7.7%，大幅跑输基准（详见 PROJECT_CONTEXT.md
  "历史回测"一节）；结果仅供研究参考，不构成投资建议
- 已知设计特点：RS 与 Momentum 的横截面得分恒等（数学推论，Strategy A v2 可改为
  对沪深300回归的残差 alpha）——本阶段按用户给定口径保留，不修改；回测页固定提示
  "实际综合权重相当于 Momentum 50%、Volatility 25%、Volume Trend 25%"
- 回测股票池为 PIT（当日有行情即在池，`use_stock_list=False`），不用当前列表排除
  历史退市股（避免幸存者偏差）；实盘页面仍用 stock_list.csv 过滤

## 数据管线

```
Tushare daily ──→ market_data_raw.parquet（断点续传：download_progress.txt）
Tushare adj_factor + 新浪 qfq.js 回补 ──→ adj_factor.parquet（source 列标记来源）
raw × factor ──→ market_data_adj.parquet（前复权，公式 p × F_current / F_last）
Tushare index_daily ──→ index_data.parquet（沪深300）
新浪交易日历 ──→ trade_calendar.parquet（完整性检查基准）
```

## 常用命令

```bash
.venv/Scripts/python.exe -m streamlit run app/Home.py       # 启动 Web App（首页入口）
.venv/Scripts/python.exe scripts/update_stock_data.py      # 个股增量更新（断点续传）
.venv/Scripts/python.exe scripts/update_index_data.py      # 沪深300增量更新
.venv/Scripts/python.exe scripts/rebuild_adj.py            # 重建前复权数据（不下载）
.venv/Scripts/python.exe scripts/backfill_adj_factor_sina.py  # 新浪因子回补（限频下）
.venv/Scripts/python.exe scripts/check_data.py             # 数据完整性检查
.venv/Scripts/python.exe scripts/validate_adj.py           # 复权数据交叉验证
.venv/Scripts/python.exe -m unittest discover -s tests     # 单元测试
```

页面导航：首页（Home）/ 数据管理 / 量化策略 / 条件选股 / 回测（Streamlit 默认多页模式）。

## 关键背景（2026-09-15 调查结论）

- 用户 Tushare 账户始终 120 积分。2026-05-03 ~ 06-02 之间 Tushare 服务端对低积分档
  引入小时级限频（错误码 40203"1次/小时"，公开档位表无此档），导致 adj_factor
  只能下到每天第 1 页，产生 2026-05 起的因子缺口（已用新浪回补解决）。
- 详细状态与已知问题见 `PROJECT_CONTEXT.md`；变更历史见 `CHANGELOG.md`。

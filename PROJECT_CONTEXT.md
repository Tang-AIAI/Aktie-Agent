# PROJECT_CONTEXT — 个人股票量化研究 Web App

> 最后更新：2026-09-17（量化策略页改造为统一多策略实时排名页：A~F 可选、B/C 显示
> 数据不足并禁用；侧边栏抽为 app/common.strategy_sidebar 与回测页共用；
> 163 单元测试全过、双页浏览器冒烟 13 项全过）
> 2026-09-17（策略库建立：Strategy A~F 注册表统一接入引擎与回测；
> B/C 因缺数据只做设计说明，D/E/F 完整实现并回测验证；150 单元测试全过、
> 回测页策略选择器冒烟 12 项全过）
> 2026-09-17（Strategy A 历史回测 MVP 完成：quant/backtest/ + pages/4_回测.py，
> 133 单元测试全过、回测页浏览器冒烟 16 项全过；真实数据 5 年回测完成并经独立手工核算验证）
> 2026-09-16（Web App 主体 UI 完成：首页/数据管理/条件选股三页 + Strategy A 页，
> 85 单元测试全过、全站浏览器冒烟 28 项 + 更新流程 7 项全过；数据已更新至 20260916）

## 项目定位

个人股票投资研究与量化分析 Web App（主要电脑浏览器使用）。
核心：利用历史股票数据进行量化研究、策略计算、条件选股。

不是行情软件 / 账户管理 / 自动交易系统。v1 明确不做：AI 推荐、自动交易、券商 API、新闻、手机 App、实时行情页、复杂 ML、付费数据。

## 技术栈

- Python 3.13（`.venv` 虚拟环境）
- 数据：Parquet 文件（非数据库）+ txt/json 状态文件
- 数据源：Tushare Pro（主，token 在 `.env`）+ AkShare（备，仅指数）
- 已有包：pandas 2.3.3 / pyarrow 23.0.1 / tushare 1.4.29 / akshare 1.18.57 / streamlit 1.55.0 / openai 2.38.0 / numpy 2.4.3
- v1 Web App 已定 Streamlit（1.55.0），Strategy A 页面 `app/strategy_a.py` 已实现

## 目录结构（v1 新结构）

```
quant/
├── data/        # 数据访问层：paths / storage(原子写+去重追加) / adj_data(前复权构建) / trade_calendar(交易日历) / index_data(指数接口)
├── scripts/     # update_stock_data / update_index_data / backfill_adj_factor / rebuild_adj / check_data
├── app/         # Web App（默认多页模式）：
│                #   Home.py            首页 Dashboard（数据状态/持仓/Strategy A Top 10/选股入口）
│                #   common.py          共享：Strategy A 计算缓存、持仓读写+估值、更新流水线、选股状态持久化、
│                #                      strategy_sidebar（策略选择+动态因子参数侧边栏，量化策略/回测两页共用）
│                #   pages/1_数据管理.py  五类数据状态 + 一键更新（子进程跑 scripts/，日志流式+持久化）
│                #   pages/2_量化策略.py  统一多策略实时排名页（A~F 可选，B/C 显示数据不足并禁用）
│                #   pages/3_条件选股.py  可视化条件构建器（12 指标 × 6 运算符 × 数值/指标右值 × AND/OR/NOT）
│                #   pages/4_回测.py     策略历史回测页（区间/TopN/调仓周期/成本率/权重窗口，
│                #                       指标卡片 + 净值曲线 + 调仓记录 + 参数快照 + 数据版本）
├── quant/       # 量化引擎：
│                #   market_data.py     区间+列裁剪读取 parquet（内存缓存，key 含文件 mtime/size）+ data_status/calendar_status/load_latest_prices
│                #   cross_section.py   横截面 z-score / 百分位排名 / 因子方向符号
│                #   factors/           因子注册表 registry + base + momentum/volatility/volume_trend/
│                #                      relative_strength/short_term_reversal/trend（含 needs_index 标记）
│                #   strategies/        策略注册表 + base（权重归一化/窗口校验/use_stock_list/
│                #                      data_available 数据可用性声明）+ strategy_a~f（6 个）
│                #   engine.py          统一流程：切片→因子→过滤→标准化→方向→加权→排名（RankingResult）
│                #   backtest/          回测：metrics（纯函数指标）/ portfolio（现金+持仓账本）/
│                #                      runner（主循环，防未来数据泄漏口径见模块注释）
│                #   screener.py        选股指标注册表 + compute_indicators + evaluate（纯逻辑可单测）
├── tests/       # 单元测试（unittest，85 个用例全部通过）
├── old_code/    # 全部废弃旧代码（含旧 LLM Agent、旧策略、旧选股器）
├── positions.csv / screener_state.json   # Web App 本地状态（手工持仓 / 最近筛选条件）
└── *.parquet    # 数据文件保持项目根目录
```

## Web App（2026-09-16 完成）

### 页面与导航

默认多页模式（pages/ 目录），侧边栏：Home（首页）/ 数据管理 / 量化策略 / 条件选股。
**不用 st.navigation**：实测 1.55 上 st.navigation 会让所有子页 URL 回落到首页
（最小复现：st.navigation + goto /p1 → 主页内容）；默认 MPA 下中文页名 URL 正常。
入口页固定名 Home.py（MPA 强制），侧边栏显示 "Home" 属框架行为。

### 数据管理流程（一键更新）

点击「更新数据」→ 按序以子进程运行现有 scripts/（不重写下载逻辑）：
1. `update_stock_data.py`（个股日线+复权因子+前复权重建；断点续传，不设超时）
2. `update_index_data.py`（3 分钟超时监督——AkShare 降级路径无内建超时、实测可挂死）
3. `check_data.py`（3 分钟超时；纯本地完整性检查）
- 日志实时流式展示（write_stream）；完成后结论 + 完整日志持久化到 session_state
  再重渲染（st.rerun 会清除流式内容，必须持久化）
- 失败如实上报：退出码 ≠ 0 或日志含"未获取到任何数据"（index 脚本降级失败时
  退出 0 的已知行为，由 UI 层扫描日志修正判定）
- 更新完成后自动刷新页面数据状态

### 条件选股（quant/screener.py + pages/3_条件选股.py）

- 12 个指标与 Strategy A 同口径（前复权价；ret/vol_ratio/volatility/rs 直接复用
  quant/factors 的计算函数）；股票池 = 有当日行情 ∩ stock_list.csv
- 条件：左值指标，运算符 > >= < <= = !=（= / != 用 1e-9 相对容差），右值固定数值
  或另一指标；条件间 AND/OR 自上而下组合（无优先级，UI 注明）+ 行级 NOT
- NaN 语义：数据不足的比较结果为"不满足"，NOT 也不放行（Kleene 逻辑）
- 结果表：代码/名称/最新价格 + 条件涉及的指标值；最近条件存 screener_state.json，
  首页展示

### 持仓（辅助模块，手工维护）

positions.csv（ts_code/name/quantity/cost_price，UTF-8，原子写入）；现价取最新
交易日原始收盘价；展示市值/盈亏/盈亏%/权重；名称留空自动从 stock_list 补全。
不做券商 API / 自动同步。

### 已知问题 / 平台特性（实测确认）

1. 🟡 **RS ≡ Momentum 横截面得分**（数学推论，Strategy A v2 改进点：对沪深300
   回归的残差 alpha）——按用户给定口径保留，本阶段不修改
2. 🟡 Streamlit 1.55 特性：st.navigation 破坏 URL 路由；st.dataframe 为 canvas
   网格（DOM 表格是 0×0 隐藏测量表，行点击选择事件前端不发送）；子页 URL 下
   框架自身产生 2 条 _stcore 404（功能不受影响）；st.rerun 清除 write_stream 内容
3. 🟡 股票池暂不过滤 ST（数据层无可靠字段，按需求暂不做）
4. 🟡 Tushare 限频仍在：index_daily 1次/小时（更新时自动降级 AkShare）；
   adj_factor 限频下日常更新提示跑新浪回补
5. 🟢 20260916 当日复权因子 5205 行 < 日线 5550 行属正常（无除权日股票 ffill 覆盖；
   新浪回补已处理当日缺口，1 只失败自动重试）


## 量化引擎与 Strategy A（2026-09-16 实现）

### 架构（策略与页面解耦，便于扩展 Strategy B/C）

- 因子 = `Factor` 元数据（名称/方向/默认窗口/说明）+ compute 函数，注册进 `factors/registry`；
  新增因子只需新建模块并在 `factors/__init__.py` 导入
- 策略只声明配置：`factor_names` / `default_weights`（自动归一化到 1）/ `default_windows`；
  新增策略继承 `Strategy` 并在 `strategies/__init__.py` 注册
- 所有策略共用 `engine.run_strategy()` 流程；Streamlit 页面只做参数输入/触发计算/结果展示

### Strategy A 定义（baseline，未经历史回测验证）

| 因子 | 口径 | 默认窗口 | 权重 | 方向 |
|---|---|---|---|---|
| Momentum | close_adj_T / close_adj_{T-W} − 1 | 60 | 25% | 越高越好 |
| Volatility | 日收益率样本标准差（ddof=1） | 20 | 25% | 越低越好（标准化后 ×−1） |
| Volume Trend | 短窗均量 / 长窗均量 | 20 / 60 | 25% | 越高越好 |
| Relative Strength | 个股 W 日收益 − 沪深300 W 日收益 | 60 | 25% | 越高越好 |

计算要求全部落实：不做原始值加权（池内横截面 z-score 后加权）；股票池先过滤
（无当日行情 / 任一因子 NaN / 不在 stock_list.csv），再在池内标准化；
权重校验非负、归一化和为 1；页面权重合计 ≠100% 时禁用「重新计算」。

### 已知特点 / 问题（实现时确认）

1. 🟡 **RS 与 Momentum 的横截面得分恒等**：RS = 个股收益 − 指数收益，指数收益对横截面
   是常数，z-score 平移不变 → `momentum_score ≡ relative_strength_score`。
   这是用户给定定义的数学推论，实现未改动口径；如需区分，未来可改为
   对指数回归的残差 alpha 等定义。
2. 🟡 **Streamlit 1.55 的 st.dataframe 选择事件实测不触发**：canvas 网格点击仅客户端
   高亮，浏览器不发 ws 事件（单击/双击/Ctrl+A 均验证），Top 10 点击联动的代码保留
   但实际选股请用页面 selectbox（已验证可用）。
3. 🟡 **股票池暂不过滤 ST**：当前 5460 只含 *ST 股票（如 Top 1 *ST艾艾），按需求
   "暂不做复杂 ST 过滤"，数据层无可靠 ST 字段，留待后续。
4. 🟢 性能：首算约 4.2s（18.2M 行 parquet 只读 4 列 + 日期过滤，实测 0.6s/年），
   loader 内存缓存 + 页面 st.cache_data 后同参数重算近瞬时。


## 策略库（2026-09-17 建立，Strategy A~F）

统一接口：strategy → factors → 横截面打分 → 排名 → 回测（全部走 engine.run_strategy
与 backtest.run_backtest，无每策略独立回测系统）。新增机制：

- `Strategy.data_available / unavailable_reason / data_requirements`：
  设计就绪但依赖数据不可用的策略（B/C）被引擎拒绝运行、页面显示原因，
  **不产生虚假回测结果**
- `Factor.needs_index`：只有依赖指数的因子（relative_strength）要求指数数据；
  D/E/F 可在指数覆盖范围（2002 年）之前的历史区间运行

### 数据可用性审计结论（2026-09-17 实测）

| 类别 | 现状 | PIT 可用？ |
|---|---|---|
| 行情 OHLCV + amount（raw/adj） | 1990-12-19 ~ 2026-09-16，18.2M 行，逐日逐股完整 | ✅ 天然 PIT（逐日写入） |
| 复权因子（含前复权价） | 同上，缺口已回补 | ✅ 比值口径与最新因子无关 |
| 沪深300 指数 | 2002-01-04 起完整 | ✅ |
| 交易日历 | 至 2026-12-31 | ✅ |
| stock_list.csv | 仅代码+名称，**当前**列表 | ⚠️ 只用于实盘页过滤（回测已 PIT 化） |
| PE/PB/市值/股息率等估值字段 | **不存在**（字段并集仅行情类；"pe"命中来自 "open" 的字符串误匹配） | ❌ |
| ROE/毛利率/负债率等财务字段 | **不存在** | ❌ |

**结论：Value（B）与 Quality（C）暂时不能可靠实现**——缺少历史 PIT 估值/财务数据；
按用户要求不伪造、不用当前值回填历史（那等价于未来数据泄漏）、不产生虚假回测结果。

### 策略清单（Baseline 默认参数，非最优；本阶段不做参数寻优）

| 策略 | 定义 | 因子/权重 | 默认窗口 | 状态 |
|---|---|---|---|---|
| A 多因子 | 动量+波动+量能+相对强度 | 各 25% | 60/20/20-60/60 | ✅ 可回测（注意 RS≡Momentum） |
| B 价值 | 低 PE/PB/股息率 | 设计：PE_TTM 50% / PB 30% / 股息率 20% | — | ⛔ 缺数据，仅设计说明 |
| C 质量 | ROE/毛利率/盈利稳定性/负债率 | 设计：40/20/20/20% | — | ⛔ 缺数据，仅设计说明 |
| D 反转 | 5 日收益率越低越好（超跌反弹） | short_term_reversal 100% | 5 | ✅ 可回测 |
| E 低波动 | 20 日收益率标准差越低越好 | volatility 100%（复用 A 因子） | 20 | ✅ 可回测 |
| F 趋势 | MA20/MA60 − 1 越高越好 | trend 100% | 20/60 | ✅ 可回测 |

实现要点：
- D 的因子**复用 momentum 的计算函数**（同一 W 日收益口径，仅方向相反），
  有测试断言两者原始值完全一致
- E **直接复用 volatility 因子**，无重复实现
- F 的均线比值为口径：最新复权因子在比值中抵消，无未来数据泄漏（与收益率因子同理）
- B/C 为 `data_available=False` 的设计壳（strategy_b.py / strategy_c.py）：
  接口已接入注册表与页面，设计定义与数据依赖（含 PIT 要求）写在类 docstring
  与 data_requirements 字段，未来接入可靠数据后填 factor_names 即可运行

### 两个页面共用同一 Engine（页面职责划分）

- **量化策略页（pages/2_量化策略.py）**：当前截面排名——"按照这个策略，今天当前
  股票池中哪些股票排名靠前？"（Top 10 / 完整排名 / 个股因子构成，与 Strategy A 时代
  同布局）
- **回测页（pages/4_回测.py）**：历史模拟——"如果按照这个策略在历史上进行交易，
  结果如何？"
- 两页共用 `app/common.strategy_sidebar(prefix)`：策略选择器（A~F，B/C 标注
  "数据不足"）+ 按策略动态渲染的因子参数侧边栏；**权重/窗口默认值直接读取策略/
  因子定义（default_weights/default_windows），UI 不硬编码第二套默认值**；
  widget key 按 prefix 隔离
- 选 B/C：两页均显示 unavailable_reason + 运行按钮禁用 + 设计说明指引，不报错不误导
- 选 A 时两页均显示 RS≡Momentum 警示（A 专属）
- 量化策略页：切换策略后旧结果不展示（提示重新计算）；计算缓存键含策略名与数据版本；
  实盘页仍用 stock_list 过滤（live 口径），回测页用 PIT 股票池

### 新增策略的真实数据快检（2024-01 ~ 2025-12，Top10/20日/0.1%成本，如实记录）

| 策略 | 累计 | 年化 | 回撤 | 胜率 | 超额 vs 沪深300(+36.7%) |
|---|---|---|---|---|---|
| A | −45.4% | −27.1% | 71.0% | 44.0% | −82.2% |
| D | −70.6% | −47.1% | 70.6% | 28.0% | −107.3% |
| E | −7.6% | −4.1% | 27.3% | 60.0% | −44.4% |
| F | +20.0% | +10.0% | 59.4% | 64.0% | −16.7% |

（2 年短区间快检仅为验证策略可用，不代表任何结论；不据此调整定义或参数。
D 的"接飞刀"亏损与无 ST 过滤一致；F 净值重建与成交价独立核算精确一致。）

## 历史回测（2026-09-17 完成，Strategy A 回测 MVP）

### 架构（quant/backtest/，全部可单测）

- `metrics.py`：净值/收益序列纯函数——累计收益 / 年化（252 日）/ 最大回撤（正数）/ 胜率 / 超额收益；空/短序列返回 NaN（回撤例外 0.0）
- `portfolio.py`：现金 + 持仓账本——买入/卖出（**整数股**，向下取整）、单边成本
  （买入多付、卖出少收 cost_rate×成交额）、现金/持仓约束自动缩减、停牌估值 ffill、
  逐笔 Trade 记录
- `runner.py`：主循环 `run_backtest(strategy, start, end, top_n, rebalance_every,
  cost_rate, ...)` → `BacktestResult`（nav 日频净值+基准 / rebalances 调仓摘要 /
  trades 逐笔 / metrics / params 快照 / data_version 指纹 / warnings）

### 防未来数据泄漏口径（设计保证，见 runner 模块注释，勿改）

1. 调仓日 d **收盘后**调用现有 `run_strategy(as_of=d)`——排名只用 ≤ d 的数据（引擎内部切片保证）
2. 成交在**次一交易日 d+1 开盘价**（默认 next_open）：选股决策不依赖 d+1 任何数据，只有成交价依赖（成交时刻才可知）
3. 停牌（执行日无行情行）→ 不假装成交：买入跳过（现金保留）、卖出跳过（继续持有），均有警告与调仓记录列
4. 持仓每日按 close_adj 收盘估值；停牌期间 ffill 最后可用价
5. 前复权口径：close_adj = p × F_t/F_last，收益只取**复权价比值**，与 F_last（当前最新因子）无关——"以今天的最新因子重算历史价格"不改变历史收益率，不引入泄漏（代码注释与页面口径说明均已写明）
6. 交易日序列 = 数据中实际存在的日期（不依赖日历/网络）

### 股票池与幸存者偏差（PIT）

- `Strategy` 新增 `use_stock_list` 开关（默认 True，实盘页面行为不变）：False 时跳过
  stock_list.csv 过滤，以"当日有行情"为在场条件——历史退市股（实测 412 只不在当前列表）
  可以进入历史排名。回测固定使用 `use_stock_list=False`
- 专测：退市股在 PIT 模式进入排名且排第 1；默认模式被排除

### 简化口径（MVP，页面有注明）

- 整数股成交，不模拟 100 股整手；不模拟涨停买不进/跌停卖不出（成交总按开盘价）
- 退市/长期停牌股按最后可用价继续估值（不模拟退市清算）
- 基准 = 沪深300 **价格指数**（不含分红再投资），区间首日归一化到 1
- 胜率 = 调仓期收益 > 0 的期数占比（期收益 = 相邻调仓执行日收盘净值之比 − 1，首期对期初）

### 真实数据回测结果（2026-09-17，默认参数：5 年 / Top 10 / 20 交易日调仓 / 单边 0.1% / 次日开盘）

- 区间 2021-09-17 ~ 2026-09-16，61 次调仓、1,006 笔成交、15 条警告（停牌跳卖/跳买、现金不足）
- 组合：累计 **−96.1%**、年化 −49.1%、最大回撤 97.4%、胜率 31.2%
- 沪深300 同期：累计 −7.7%、年化 −1.7%、最大回撤 37.9% → 超额 **−88.4%**
- 结果性质（已核实，非计算错误）：独立手工核算全部吻合——5 个抽查日净值重建
  （≤ 当日成交 × parquet 收盘价，停牌 ffill）差异 ≤1e-16；成交价 = parquet 次日 open_adj；
  期收益 = 个股 open→open 加权平均（如 2024-01-12 期：6 新买股 −24.5% + 4 持有股
  −15.4% → 组合 −20.9%，与净值曲线一致）；基准 = 指数收盘归一化
- 亏损原因（如实记录）：RS ≡ Momentum 横截面 score 恒等 → 动量实际占 50% 权重；
  策略持续买入全市场 60 日动量顶部（妖股/北交所/ST——首期即 2021-09 锂电泡沫顶部；
  2024 年北交所持仓开盘即跌 10~17%）；无 ST 过滤。**Strategy A 现行定义在历史上
  大幅跑输基准，这正是回测存在的意义**：后续 v2 方向 = RS 残差 alpha、ST 过滤、
  指数成分/市值限制等
- 回测页固定显示警示：「当前 Strategy A 的 Momentum 与 Relative Strength 横截面
  score 恒等，因此实际综合权重相当于 Momentum 50%、Volatility 25%、Volume Trend 25%。」

### 验证与测试

- 新增 48 个单元测试（共 133）：metrics 24 / portfolio 13 / backtest 核心 10
  （PIT 股票池 2、runner 数学手工核算、停牌 ffill+不卖出、未来股票绝不提前成交、
  成本双向、无泄漏专门断言、与真实引擎端到端、参数校验）+ 日历编码 1
- 回测页浏览器冒烟 16 项全过（headless Edge + Playwright）：页面渲染、RS 警示、
  短区间（2025 年）真实回测跑通、指标/曲线/调仓记录/参数快照、无应用级 JS 错误
  （2 条 _stcore 404 为已知框架特性）
- 修复：data/trade_calendar.py 增加 stdout/stderr UTF-8 重配置（默认 GBK 控制台
  下打印 ⚠️ 不再 UnicodeEncodeError），测试在两种编码环境均全过

## 数据基础设施（v1 保留复用）

| 文件 | 内容 | 范围 |
|---|---|---|
| `market_data_raw.parquet` | 个股日线（Tushare daily 全字段） | 5903 只，1990-12-19 ~ 2026-09-15，18.2M 行 ✅ 无缺日 |
| `adj_factor.parquet` | 复权因子（逐日逐股）+ **source 列（tushare/sina/tencent）** | 18.6M 行 ✅ 缺口已回补（tushare 18.52M / sina 12.5万 / tencent 37） |
| `market_data_adj.parquet` | 前复权数据（`*_adj` 列，**公式已修正为 `p × 当日因子/最新因子`**） | 18.2M 行 ✅ 全部验证通过 |
| `index_data.parquet` | 沪深300 日线（000300.SH），vol 列已统一 | 2002-01-04 ~ 2026-09-15，5993 行 ✅ |
| `trade_calendar.parquet` | 交易日历缓存（**新浪列表为主源**，校验后原子写入） | 1990-12-19 ~ 2026-12-31，8797 行 ✅ |
| `stock_list.csv` | 股票代码+名称 | 5493 只 |
| `download_progress.txt` | 断点续传：已完成交易日集合（8722 天） | — |
| `failed_dates.txt` | 失败日期记录（历史节假日误报，仅作日志） | — |
| `backup_20260915/` | **修复前全量备份**（adj_factor/market_data_adj/trade_calendar/index_data/进度/失败记录） | — |

### 断点续传机制（`new_update_daily_data.py`）

1. `download_progress.txt` 存已完成交易日集合
2. 起始日 = max(progress)+1；已有日期跳过
3. `pro.daily(trade_date=...)` 逐日下载（limit=5000 + offset 分页，重试 3 次，间隔 0.35s）
4. 每 30 天一批 `batch_append_daily`：concat → drop_duplicates([ts_code, trade_date]) → sort → 原子写（tempfile + os.replace）
5. 复权因子按日期范围一次性分页下载 → `update_factors` 增量合并
6. 每次运行最后用 raw+factor 全量重算 `market_data_adj.parquet`

### 指数更新（`update_daily_300_data.py` + `data_manager.py`）

- 增量：读已有最早日期 → 向前补一年 → 合并去重
- Tushare `index_daily` 失败时降级 AkShare `stock_zh_index_daily`，统一列名 ts_code/trade_date/open/high/low/close/vol

### 运行方式（v1 现状）

- 手动 CLI：`python scripts/update_stock_data.py`（个股）、`python scripts/update_index_data.py`（指数）
- `python scripts/check_data.py`：完整性检查（日历比对 + 每股因子滞后）
- `python scripts/rebuild_adj.py`：不下载、用 raw+因子重建前复权数据
- `python scripts/backfill_adj_factor.py --start --end`：因子缺口回补（限频感知+断点续传）
- v1 将把 update 流程搬进 Web App 内触发 + 进度显示，下载逻辑本身不改

## 已废弃 / 不保留（已移入 old_code/ 或待清理）

- 旧 LLM Agent（llm/main/memory/tools/memory.json）、`update_daily_300_data_tushare.py` → 已移入 `old_code/`
- `old_code/` 其余旧策略/选股器——策略重新设计，不迁移
- `market_data.parquet`（2015~2026-04 旧快照）、`*.parquet.backup`（约 1.5GB）、`data_cache/*.csv`——待确认后可删除

## 已知问题（2026-09-15 修复后状态）

1. 🟢 **复权因子缺口 —— 已解决**：2026-05~09 缺口用新浪因子链合成补齐（125,031 行，锚定 Tushare 因子，跳变一致性 ≤0.03%）；689009.SH（CDR，新浪无链）用腾讯数据定位除权日 + Tushare 官方锚点补齐 37 行。
2. 🟢 **前复权公式 —— 已修复**：`data/adj_data.py` 改为 `p × 当日因子/最新因子`，全表重建，6 项交叉验证全部通过。
3. 🟢 **日历缓存 —— 已修复**：新浪交易日列表为主源（axtrade 全量一次请求），写入前强校验（覆盖范围 + 与 raw 实际交易日交叉一致 + 缓存近 90 天 ≥50 交易日），不完整绝不落盘。
4. 🟡 **残留**：5 只股票的因子落后于日线（均为 2026-05 之前的 Tushare 历史边缘案例：3 只 2007-2008 退市股因子少 ~6 周、2 只 2026-04 初缺 2-3 周），ffill 已覆盖、数值影响可忽略，不在本次任务范围。
5. 🔴 **Tushare 限频仍在**：adj_factor/trade_cal 对 120 积分账户仍约 1 次/小时（40203）。日常更新脚本的因子部分会提示运行 `backfill_adj_factor_sina.py`；`backfill_adj_factor.py`（Tushare 官方回补，权限恢复后可用，自动覆盖同键新浪行）。
6. 🔴 **Token 泄露**：Tushare token 曾硬编码并提交进 git 历史，且与 `.env` 中当前 token 相同，建议在 Tushare 后台重置。
7. 🟡 旧 `market_data.parquet`、`*.parquet.backup`、`data_cache/` 等待用户确认后删除。

## v1 目标架构（规划中，未实现部分）

- ✅ 量化引擎：数据 → 因子计算 → 因子标准化 → 权重 → 综合评分 → 排名（2026-09-16 完成）
- ✅ Strategy A 页面：参数/窗口/权重可改，点「重新计算」出新排名（移入 pages/2_量化策略.py）
- ✅ 首页：数据状态 + 简单持仓（手工维护）+ 量化策略入口 + 选股入口（2026-09-16 完成）
- ✅ 条件选股：可视化 AND/OR/NOT 条件组合（指标 vs 数值/指标），不做自然语言（2026-09-16 完成）
- ✅ 持仓：股票/数量/成本/当前价/盈亏/仓位，手工维护（首页内嵌，positions.csv）
- ✅ 数据更新触发搬进 Web App：数据管理页/首页均有「更新数据」按钮（子进程调用现有 scripts/）
- ✅ Strategy A 历史回测 MVP：quant/backtest/ + pages/4_回测.py（2026-09-17 完成，见上文）
- ✅ 策略库 A~F：D/E/F 完整实现、B/C 设计壳（缺 PIT 财务数据）、回测页策略选择器
  （2026-09-17 完成，见"策略库"一节）
- ✅ 量化策略页统一多策略：A~F 可选（B/C 显示数据不足并禁用）、侧边栏抽为共享
  helper 与回测页共用（2026-09-17 完成）
- ⬜ 后续：Strategy A v2（RS 残差 alpha / ST 过滤 / 股票池限制）、接入 PIT 估值/财务
  数据后实现 B/C、统一回测与参数实验（固定基线，非寻优）

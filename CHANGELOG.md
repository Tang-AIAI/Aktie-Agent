# CHANGELOG

## 2026-09-17（晚间）— 策略库：Strategy A~F 统一接入引擎与回测

### 数据可用性审计（先审计后实现，结论）
- 数据字段并集仅行情类：OHLCV + amount + 复权因子 + 交易日历 + stock_list（代码/名称）
- **无任何历史 PIT 估值/财务数据**（无逐日 PE/PB/市值、无 ROE/毛利率等财报字段；
  "pe"命中来自 "open" 的字符串误匹配）→ **Value（B）与 Quality（C）本阶段不实现**，
  不伪造、不用当前值回填历史（=未来数据泄漏）、不产生虚假回测结果

### 新增策略（quant/strategies/，统一注册表）
- `StrategyD（反转）`：short_term_reversal 因子（5 日收益越低越好）——计算函数
  **复用 momentum**（同口径反向，测试断言两因子原始值全等）
- `StrategyE（低波动）`：**直接复用 volatility 因子**（20 日收益标准差越低越好），
  无重复实现
- `StrategyF（趋势）`：新 trend 因子（MA20/MA60 − 1 越高越好；均线比值与最新复权
  因子无关，无泄漏）；窗口校验 short < long
- `StrategyB/C`：设计壳（data_available=False）——设计定义（候选因子/基线权重）与
  PIT 数据依赖写在类 docstring 与 data_requirements；接口已入注册表，未来数据
  就绪后填 factor_names 即可运行
- 策略基类新增 `data_available / unavailable_reason / data_requirements`
- 因子元数据新增 `needs_index`：引擎只对依赖指数的因子加载/校验指数 →
  D/E/F 可在沪深300 覆盖范围（2002 年）之前的历史区间运行

### 引擎与回测兼容
- `engine.run_strategy`：data_available=False 拒绝运行并给出原因；
  指数按因子依赖按需加载（Strategy A 行为不变）
- `run_backtest` 与页面直接支持全部策略（无每策略独立回测系统）；
  参数快照含策略名与权重窗口

### 回测页（pages/4_回测.py）
- 侧边栏策略选择器（A~F；B/C 标注"数据不足"）；因子侧边栏按策略动态渲染，
  默认权重/窗口取策略声明值；缓存键含策略名
- 选 B/C：显示原因 + 运行按钮禁用 + 设计说明指引（不报错、不误导）
- Strategy A 的 RS≡Momentum 警示仍为 A 专属

### 测试与验证（全部通过）
- 单元测试 133 → **150**（tests/test_strategies.py 新增 17：注册表 6 策略、因子
  手工核算、排名方向 D/E/F、NaN 排除、PIT 开关对新策略生效、needs_index（指数
  为空 D/E/F 可跑、A 必报错）、B/C 引擎拒绝+回测警告不崩溃、F 策略真实引擎回测）
- 真实数据快检（2024-01~2025-12，Top10/20日/0.1%成本，如实记录于
  PROJECT_CONTEXT.md）：A −45.4% / D −70.6% / E −7.6% / F +20.0%
  （同期沪深300 +36.7%）；F 成交价=parquet 次日开盘、中间日净值独立重建一致
- 回测页浏览器冒烟 12 项全过（headless Edge + Playwright）：策略选择器 6 项、
  F 因子侧边栏动态渲染、B 原因显示+按钮禁用、F 2025 年真实回测跑通、
  参数快照含策略名、无应用级 JS 错误（2 条 404 确认为 _stcore 框架特性）

## 2026-09-17 — Strategy A 历史回测 MVP

### 回测核心（quant/backtest/，先测后写）
- `metrics.py`：纯函数指标（累计/年化 252 日/最大回撤/胜率/超额收益，NaN 边界明确）
- `portfolio.py`：现金+持仓账本（整数股、单边成本、现金/持仓约束自动缩减、停牌 ffill 估值、逐笔 Trade）
- `runner.py`：主循环 `run_backtest()` —— 调仓日收盘 `run_strategy(as_of=d)` 排名 →
  Top N 等权计划 → 次一交易日开盘价成交（停牌不成交，现金不足买入未成交如实记录）→
  每日收盘估值（停牌 ffill）→ BacktestResult（净值+基准/调仓记录/逐笔/指标/参数快照/数据版本）
- 防未来数据泄漏口径六条写在模块注释与 PROJECT_CONTEXT.md；前复权只取比值（与最新
  因子无关）的说明随代码注释与页面口径一起落地

### 幸存者偏差（PIT 股票池）
- `Strategy` 新增 `use_stock_list` 开关（默认 True，实盘页面行为不变）；
  `engine.py` 过滤条件一行适配。回测固定 `use_stock_list=False`：当日有行情即在池，
  历史退市股（实测 412 只不在当前列表）可进入历史排名
- 专测：退市股 PIT 模式进入排名（排第 1）vs 默认模式被排除

### 顺手修复
- `data/trade_calendar.py`：stdout/stderr UTF-8 重配置（默认 GBK 控制台下打印 ⚠️
  不再 UnicodeEncodeError）；测试在带/不带 PYTHONIOENCODING 两种环境均全过

### Web 页面（app/pages/4_回测.py）
- 参数：起止日期（默认近 5 年，最早 2002-05 受指数数据约束）/ Top N / 调仓周期 /
  单边成本 / Strategy A 权重窗口（复用 2 页交互模式）；`st.cache_data` 键含数据版本
- 展示：指标卡片（累计/年化/最大回撤/胜率 + 沪深300 三项 + 超额收益）、净值曲线
  （组合蓝/基准橙，明暗模式均通过可访问性校验，线尾直接标注）、调仓记录、
  逐笔成交、参数快照、数据版本、口径说明
- 固定显示警示：RS 与 Momentum 横截面 score 恒等 → 实际综合权重相当于
  Momentum 50%、Volatility 25%、Volume Trend 25%（已记录为 Strategy A v2 问题）

### 测试与验证（全部通过）
- 单元测试 85 → **133**（metrics 24 / portfolio 13 / backtest 核心 10 / 日历编码 1）；
  核心测试含：runner 组合数学手工核算、停牌 ffill+不卖出、未来股票绝不提前成交、
  成本双向、无泄漏专门断言、真实引擎端到端、参数校验
- 真实数据回测 + **独立手工核算验证**：2024 年（68.5s）与默认 5 年（319s）两个区间；
  5 个抽查日净值用"≤ 当日成交 × parquet 收盘价"重建，差异 ≤1e-16；成交价 =
  parquet 次日 open_adj；期收益 = 个股 open→open 加权平均（2024-01-12 期：
  6 新买股 −24.5% + 4 持有股 −15.4% = 组合 −20.9% 一致）；基准 = 指数收盘归一化
- 回测页浏览器冒烟（headless Edge + Playwright）16 项全过：页面渲染、RS 警示、
  短区间（2025 年）真实回测跑通、指标/曲线/调仓记录/参数快照、无应用级 JS 错误
  （仅 2 条已知 _stcore 框架 404）

### 真实数据回测结果（默认参数：5 年 / Top 10 / 20 交易日 / 单边 0.1% / 次日开盘）
- 2021-09-17 ~ 2026-09-16：组合累计 **−96.1%**（年化 −49.1%、回撤 97.4%、胜率 31.2%，
  61 次调仓 1,006 笔），同期沪深300 −7.7%，超额 −88.4%
- 已核实为策略真实历史表现：动量实际占 50% 权重（RS≡Momentum），持续买入全市场
  60 日动量顶部（首期即 2021-09 锂电泡沫顶部；2024 年北交所持仓开盘即跌 10~17%），
  且无 ST 过滤。结论如实记录：Strategy A 现行定义历史上大幅跑输基准，v2 方向 =
  RS 残差 alpha、ST 过滤、指数成分/市值限制等
- 简化口径（页面注明）：整数股不模拟整手；不模拟涨跌停成交限制；退市股按最后价
  持有；基准为价格指数（无分红）

### 新增开发依赖
- venv 新增 `playwright`（仅冒烟测试用；浏览器用系统 Edge channel，未下载内核）

## 2026-09-16（晚间）— Web App 主体 UI：首页 + 数据管理 + 条件选股

### 页面结构（Streamlit 默认多页模式，pages/ 目录）
- `app/Home.py`：Dashboard 四区——数据状态（各数据最新交易日 + 是否最新及原因 +
  一键更新）、量化系统（Strategy A 最近计算日 + Top 10 + 入口链接）、当前持仓
  （本地 positions.csv 手工维护，现价=最新原始收盘价，市值/盈亏/盈亏%/权重）、
  条件选股（入口 + 最近使用条件）
- `app/pages/1_数据管理.py`：五类数据（个股日线/复权因子/前复权数据/沪深300/
  交易日历）的最新交易日、最新日行数、来源、状态 + 一键更新（子进程调用现有
  scripts/，日志实时流式展示，完成后持久化展示结论与完整日志，失败如实上报）
- `app/pages/2_量化策略.py`：原 Strategy A 页面原样移入（仅路径调整），
  核心逻辑未改动
- `app/pages/3_条件选股.py`：可视化条件构建器——12 个指标（收盘价/MA5/20/60/120/
  20 日收益率/60 日收益率/20 日均量/60 日均量/成交量比/波动率/相对强度），
  运算符 > >= < <= = !=，右值支持固定数值或另一指标，条件间 AND/OR（自上而下、
  无优先级，UI 注明）+ 行级 NOT；结果表含代码/名称/最新价格/条件相关指标值

### 基础设施（复用已有数据层与量化引擎，未重写下载逻辑）
- `app/common.py`：Strategy A 计算缓存（键含数据文件指纹）、持仓读写与估值、
  更新流水线（子进程 + 每步超时监督：沪深300/完整性检查 3 分钟，个股日线
  断点续传不设限）、选股条件持久化（screener_state.json，首页展示最近条件）
- `quant/market_data.py`（增量）：data_status()（元数据统计量取各文件最新交易日，
  不扫全表）、calendar_status()（最近开盘日/今日是否开盘）、load_latest_prices()
- `quant/screener.py`（新增）：指标注册表 + compute_indicators（与 Strategy A
  同口径：前复权价、股票池=有当日行情 ∩ stock_list.csv）+ evaluate 条件求值
  （NaN 语义：数据不足视为不满足，NOT 不放行；= / != 用 1e-9 相对容差）
- `data/paths.py`（增量）：POSITIONS_FILE / SCREENER_STATE_FILE

### 测试与验证（全部通过）
- 单元测试新增 21 个（共 85 个）：条件求值 AND/OR/NOT/指标对比/容差/NaN 排除、
  指标计算（MA 手算验证、close_raw 与复权区分、ret60 与 momentum 同口径等）
- 浏览器冒烟（headless Edge + Playwright，真实数据）：全站 28 项全过——
  首页 Top 10 与引擎逐项一致、持仓估值与引擎一致、四页导航、
  条件选股 6 种场景（单条件/AND/OR/指标对比/无结果/大量结果）计数与引擎一致、
  无应用级 console 错误
- 数据管理「更新数据」冒烟 7 项全过：真实跑完 个股日线→沪深300→完整性检查
  三步（0.4 分钟），日志流式展示 + 完成后持久化，结论如实显示
- 冒烟中修复的真实问题：st.rerun() 会清除 write_stream 流式日志（改为
  session_state 持久化后重渲染）；index 脚本"未取得数据仍退出 0"（UI 层扫描
  日志标记失败）；AkShare 降级路径可能无超时挂死（UI 层 3 分钟监督终止）

### 已知问题（保留记录，不阻塞）
- Strategy A 的 RS 与 Momentum 横截面得分恒等（数学推论，见 PROJECT_CONTEXT.md），
  标记为未来 Strategy A v2 改进点（可改为对沪深300回归的残差 alpha）
- Streamlit 1.55 平台特性：st.navigation 会破坏 URL 路由（子页全部回落到首页，
  已实测复现）→ 使用默认多页模式；入口页固定显示 "Home"（MPA 强制 Home.py）；
  子页 URL 下框架自身产生 2 条 _stcore 404（功能不受影响）；st.dataframe 为
  canvas 网格，DOM 表格是隐藏测量表；行点击选择事件前端不发送
- 复权因子 20260916 当日行数（5205）少于日线（5550）属正常：无除权日的股票
  由 ffill 覆盖；新浪回补脚本已处理当日缺口（207 只除权股票，1 只失败自动重试）

## 2026-09-16 — 量化引擎 + Strategy A（baseline）

### 新增：量化引擎（`quant/` 包）
- `market_data.py`：按日期区间 + 列裁剪读取 parquet（不读全量历史，实测 0.6s/年），
  内存缓存 key 含文件 mtime/size，更新脚本替换数据文件后自动失效；最新交易日从
  parquet 元数据统计量读取（不扫数据）
- `factors/`：因子注册表 + 4 个因子——momentum（60 日收益）、volatility
  （20 日收益标准差，越低越好）、volume_trend（20/60 日均量比）、relative_strength
  （个股 − 沪深300 的 60 日收益差）
- `cross_section.py`：横截面 z-score（默认）/ 百分位排名 + 因子方向符号（低优因子 ×−1）
- `strategies/`：Strategy 基类（权重非负校验 + 自动归一化 + 窗口校验）+ StrategyA
  （四因子等权 25%）+ 策略注册表
- `engine.py`：统一流程 切片 → 因子 → 股票池过滤（无当日行情 / 因子 NaN / 不在
  stock_list）→ 池内横截面标准化 → 方向调整 → 加权 → 排名；返回 RankingResult

### 新增：Strategy A 页面（`app/strategy_a.py`）
- 侧边栏参数：计算日期、四因子窗口（Volume Trend 双窗口短<长校验）、权重
  （合计 ≠100% 禁用「重新计算」）、因子方向展示
- 主区：Top 10（排名/代码/名称/综合得分/四因子得分，可选原始值）、策略参数、
  完整排名、个股因子构成（表格 + 发散色柱图，selectbox 选择股票）
- 页面只做参数输入/触发计算/展示，无策略逻辑；标注"baseline 策略，未经历史回测验证"

### 测试与验证（全部通过）
- 单元测试新增 40 个（共 64 个）：四因子口径、方向反转、横截面标准化、权重合成、
  缺失数据/停牌排除、权重与窗口参数变化后结果确实变化、权重与窗口校验、as_of 兜底
- 真实数据冒烟：2026-09-15 计算 4.2s，股票池 5460 只（排除 115 只），Top 10 正常
- Streamlit 页面冒烟（headless Edge + Playwright，12 项检查全过）：页面渲染、
  Top 10 数据与引擎一致、selectbox 选股联动、窗口 60→10 重算后第 1 名变化
  （603580.SH → 601086.SH）、权重 101% 禁用按钮、无 console 错误

### 已知特点（按需求口径实现，未改动）
- RS 与 Momentum 的横截面 z-score 恒等（指数收益对横截面是常数，平移不变），
  见 PROJECT_CONTEXT.md
- Streamlit 1.55 st.dataframe 选择事件实测不触发（前端不发 ws 事件），
  选股请用页面 selectbox
- 暂不过滤 ST / 停牌高级规则，股票池 = stock_list.csv 且有完整 60 日数据


## 2026-09-15 — v1 重建：目录重构 + 数据层修复

### 目录重构
- 新建 `app/ quant/ data/ scripts/ tests/` 结构；旧上层代码（LLM Agent 等）移入 `old_code/`
- `data/`：paths（路径集中）、storage（原子写 + 去重追加，新增 keep 参数）、
  adj_data（前复权构建）、trade_calendar（日历）、sina_factor（新浪因子链）、index_data（指数接口）
- `scripts/`：update_stock_data、update_index_data、rebuild_adj、check_data、validate_adj、
  backfill_adj_factor（Tushare，备用）、backfill_adj_factor_sina（新浪回补）
- 单元测试 24 个（storage/adj_data/sina_factor/trade_calendar），全部通过

### 数据补齐
- 个股日线补齐 2026-08-14 → 2026-09-15（22 个交易日，断点续传机制实测正常）
- 沪深300 补齐至 2026-09-15；volume/vol 双列合并为 vol

### 三项修复
1. **前复权公式修正**：`p × 最新因子/当日因子`（旧，错误，除权日幻影跳空 12% 偏差）
   → `p × 当日因子/最新因子`（Tushare 官方，经腾讯 qfq 基准验证）。全表重建。
2. **复权因子缺口回补**：2026-05 起因 Tushare 小时级限频（40203）产生的缺口，
   用新浪 qfq.js 因子链合成补齐（125,031 行，锚定 Tushare 因子，跳变一致性 ≤0.03%；
   689009.SH 用腾讯数据定位除权日 + Tushare 官方锚点，37 行）。
   adj_factor.parquet 新增 source 列（tushare/sina/tencent）。
3. **交易日历修复**：新浪交易日列表为主源（全量一次请求），写入前强校验
   （覆盖范围 + 与 raw 交叉一致 + 缓存可用性），不完整绝不落盘。缓存重建 8797 行。

### 验证（全部通过）
- 交叉验证（validate_adj.py）：6 只样本因子跳变 ≤0.03%、除权日连续性、
  方向基准 0.47%、最新日不变式 100%、随机 20 只历史一致性、来源分布
- 完整性检查：4 个数据文件 0 缺日；因子滞后 561 → 5 只（均为 2026-05 前历史边缘案例）
- 冒烟测试：个股更新（"数据已是最新"）、指数更新（原子保存、0 NaN）、重建（2 次成功）

### 备份
- 修复前全量备份：`backup_20260915/`（adj_factor、market_data_adj、trade_calendar、
  index_data、download_progress.txt、failed_dates.txt）

### 遗留
- Tushare adj_factor/trade_cal 对 120 积分账户仍约 1 次/小时；日常更新因子部分会提示用新浪回补
- 5 只股票历史因子边缘缺口（2026-05 前，ffill 覆盖，影响可忽略）
- Tushare token 泄露进 git 历史，建议重置

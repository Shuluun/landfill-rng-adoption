# STATUS — rng_mainline_strengthening_v1

## 当前交付 2026-11-10

| 交付 | 状态与入口 |
| --- | --- |
| 核定范围 | 已定，主文 1995–2024，2020 互补。 [mainline_scope](mainline_scope.md) |
| 原分析复现 | 已实跑三个冻结脚本。原 T2 121 事件、1,502 场、43,593 场址年和 100 km Conley SE 0.07668 对上。旧基线准分离及新版桥接已解释。 [基线报告](baseline_reproduction_report.md) |
| 事件与来源账本 | 已生成 215 个原登记项目行及 103 条来源或查核记录。项目原表行、年份、范围和未定标签齐列。新增关键裁定待独立人工复核。 [事件](results/mainline/run_006/event_ledger.csv) · [来源](results/mainline/run_006/source_ledger.csv) |
| 部署比较 | 已完成固定资格下计数、共同州四格、配对空间推断、晚端日期和共享项目敏感性。2024 宽登记 46，核正 18。共同州 OR 0.907。 [结果](results/mainline/run_006/deployment_comparisons.csv) |
| 2020 互补 | 完成全框五期追踪、固定终点和两图层实际估计。45 个混合结局，基准规模规格 OR 0.919，完整真实正负结局仍待验证。 [2020 报告](temporal_complement_2020.md) |
| 图形与主张 | 三张部署主图和一张 GHGRP 补图均有实际输入。旧 GHGRP 空图映射已在补图修复。 [图与主张](claims_to_evidence.md) |
| 稿件修订 | 已给新版英文摘要结果和按章节修订内容。 [提纲](manuscript_revision_outline.md) |

实际可定位的交接 Word 是 `RNG论文收尾交接与技术补强方案.docx`，已提取正文。目录中未定位到独立的 `RNG_Paper_Upgrade_Plan.docx` 和 `RNG_Q2_TARGET_PLAN.md`。升级方案正文见 `RNG_AI_HANDOFF.md` B 部分。按照本轮指示使用新仓库和原主线。

核定使用 `results/mainline/run_007`、`results/temporal/run_007`、`results/figures/run_004` 与 `results/checks/run_004`（改标 confirmed_post_cutoff 后的冻结版本）。初次历史队列读图在空 polyline 处报错，修复后核对了两图层各 12 个穷举距离。旧输出、未采用的中间运行和并行分析保留在各自目录。主稿数字只引用本节锁定的版本。

最早的本地提交也纳入三份同期并行脚本。后续提交按显式文件路径记录。并行的 119 事件结果和核定的 115／114 使用不同日期处置与样本资格，分歧和 Alliance 单场敏感性见基线报告。

**下一步（已完成）** 四条旧 2024 归属未定记录已独立复核，并把 838/1469/2001 账本标签由 unknown_cutoff 改标 confirmed_post_cutoff 完成：[记录](independent_review_4_withheld_2024_events.md)。838 Lemons、1469 J.C. Elliott 与 2001 Bethlehem 收紧为 confirmed_post_cutoff（Elliott 的窗内事件是 Cefe 11862；Bethlehem 的 2021 首发实为破土），12144 Quad Cities 维持未定（首发约 2024 Q4 但无 dated first-gas）。主口径 114 计数与系数不变；`scenario_unknown_at_registered_year` 敏感场景未定条数 7→4（n_events 124→121）。temporal 侧同步新增 post-cutoff 覆盖，避免 1469 按登记日期被误计为窗内事件。作者版事件表据此冻结。剩余可选项：找 Quad Cities dated first-gas。

## 并行过程状态存档

最后更新：2026-11-10

## 本轮目标（依新 prompt，主线不变）

在核实真实投运事件后，回答：美国填埋场管道注入 RNG 的部署与管网接近程度有什么关系；部署数量、时间与距离关联对登记状态、投运日期和暴露时点处理有多敏感。2020 基准队列为互补的时间顺序证据；既有能源利用状态仅为解释性补充；GHGRP 运行线为有边界的补充。

## 交付物状态（新 prompt 的 8 项）

| # | 交付物 | 状态 | 证据/位置 |
|---|---|---|---|
| 1 | mainline_scope.md | **completed** | 已有，范围与主线一致 |
| 2 | baseline_reproduction_report.md | **completed** | 三个冻结脚本重跑逐位对上基线（−0.1687/121 事件/43593/Conley 100km 0.07668 p 0.0278） |
| 3 | event_ledger.csv + source_ledger.csv | **completed** | 全量事件账本 + 21 条裁定（targeted_adjudications.csv 20 条 + A36 审计分支）已生成并冻结于 run_007 |
| 4 | deployment_comparisons.csv | **completed** | 固定资格计数、共同州四格、配对空间推断、晚端日期与共享项目敏感性已跑；共同州 OR 0.907 |
| 5 | temporal_complement_2020.md | **completed** | 全框五期追踪、固定终点与两图层实际估计；45 混合结局，基准规模规格 OR 0.919 |
| 6 | figures/ + claims_to_evidence.md | **completed** | 三张部署主图 + 一张 GHGRP 补图均有实际输入 |
| 7 | manuscript_revision_outline.md | **completed** | 新版英文摘要结果 + 按章节修订内容已给 |
| 8 | STATUS.md | **completed**（本文件） | 独立复核 + confirmed_post_cutoff 改标已并入 |

## 工作包状态（映射 RNG_AI_HANDOFF W0–W6）

| 工作包 | 状态 | 关键结论 | 阻塞/下一步 |
|---|---|---|---|
| W0 恢复基线 | **completed** | 复现一致；ridge≠MLE 边界已如实记录 | 无阻塞；开放项见报告第 5 节 |
| W1 统一事件 | **in_progress** | 棘手 11 场已裁定（prewindow/unknown_cutoff/confirmed_year/retain_registry）；30+36=56 场已核 | 缺：全量事件账本 + 四层 ID crosswalk |
| W2 分解与模型审查 | **in_progress** | model.py 三关对账通过（结构 1821/52905/121→剔 18 州 1502/43593/121；Newton≈BFGS 1e-7；日历组 −0.1656/Conley 0.0749） | 依赖 W1 账本；四格 + 共同州 + paired difference |
| W3 2020 基准队列 | **not_started** | 快照在本地；7 消失 ID 待追 | 依赖 W1 账本 |
| W4 AI 与概率审核 | **not_started**（可选） | 145 场框可考虑全量核验 | 先核算成本 |
| W5 运行诊断 | **not_started**（可选小试点） | 浓度 +4pp 但同一上游计量边界未闭合 | 仅补充 |
| W6 成稿与复现 | **not_started** | — | 依赖以上 |

## 关键数字（已复现，非"待核"）

- 纠正后 T2：−0.1687（SE 0.0653, p 0.0098），121 事件 / 1,502 场 / 43,593 场址年；Conley 100 km SE 0.07668（p 0.0278）。
- 未纠正全状态：−0.1837（144 事件）；ev_opshut 原版 −0.1715（108 事件）。
- 条件数 2.64e9；未惩罚模型奇异；ridge 1e-6；剔除 18 无事件州。

## 下一步（单个优先）

1. ~~验证 src/model.py 独立实现~~ **完成**（`src/reconcile_model.py`，三关全过）。
2. ~~建全量 event_ledger.csv + 全裁定 + W2 四格 + W3 2020 互补~~ **完成**（run_007 冻结，114 事件 OR 0.907[0.814, 1.011]）。
3. ~~独立复核四条旧 2024 + 改标 confirmed_post_cutoff~~ **完成**（838/1469/2001 确认在窗外，12144 未定；scenario_unknown 未定 7→4）。
4. **进入正文定稿**（按 manuscript_revision_outline.md 逐段改写全文）。

## 环境与约定

- 解释器：`python3.13`（numpy 2.4.4 / pandas 3.0.2）。
- 主工程非 git；本目录有独立 `.git` 但无提交。按约定记 SHA-256，不虚构 commit，仅用户要求时提交。
- 新增运行放 `results/<task>/run_NNN/`，不覆盖 `results/legacy/`。

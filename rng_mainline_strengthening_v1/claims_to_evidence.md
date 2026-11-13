# 论文主张与证据索引

| 主张 | 可复核证据 | 稿件中的范围 |
| --- | --- | --- |
| 宽登记代理使分析框的 2024 年计数达到 46，严格登记是 10，核正是 18。累计分别为 142、106、115 | [年度与累计表](results/mainline/run_006/annual_deployments.csv) · [图 1](figures/mainline_fig01_deployments.svg) | 1,819 场的固定描述框，2024 年 9 月登记与定向事后核验。区分计划代理、实际证据及全年覆盖边界 |
| 两场窗前已运行，四场旧 2024 事件的截止归属未解决 | [逐项目事件表](results/mainline/run_006/event_ledger.csv) · [来源表](results/mainline/run_006/source_ledger.csv) · [变化表](results/mainline/run_006/changed_landfill_events.csv) | 两场改变入组资格，四场属于未定的事件身份或时点。另存原登记年份情景 |
| 同口径主模型 OR 0.907，95% 空间区间 [0.814, 1.012]，114 事件 | [模型对照](results/mainline/run_006/deployment_comparisons.csv) · [图 2](figures/mainline_fig02_distance.svg) | 1,317 场、29 州、38,071 场址年。条件年度优势。距离是最近图示线段 |
| 联合核正与严格原登记的 ln 距离差 +0.016，区间 [−0.022, 0.055] | [配对推断](results/mainline/run_006/paired_deployment_differences.csv) · [州表](results/mainline/run_006/state_support.csv) | 同一场址使用配对得分及空间权重。系数点值变化有限，仍有可观的不确定性 |
| 窗前、截止、共用设施和地理支持影响估计幅度 | [桥接和规格](results/mainline/run_006/deployment_comparisons.csv) · [共享项目](results/mainline/run_006/shared_parent_sensitivity.csv) · [影响分析](results/mainline/run_006/site_influence.csv) | 共用父编号是关系筛查，已有 Assai 和 Corpus Christi 公共证据支持其项目与场址映射。因果解释需要另有证据 |
| 2020 证据筛查模型 45 个固定窗事件，EIA 基准 WIP 规格 OR 0.919［0.790, 1.069］ | [2020 报告](temporal_complement_2020.md) · [模型](results/temporal/run_005/landmark2020_models.csv) · [图 3](figures/mainline_fig03_landmark.svg) | 注册和部分外部证据混合结局。对照的物理状态未独立核实。与主结果共享 45 个事件 |
| 两套图层在 2020 同坐标上大多给出接近的距离 | [配对图层模型](results/temporal/run_005/landmark2020_layer_contrasts.csv) · [同样本距离核查](results/checks/run_003/baseline_checks.json) | 对照共同来源和暴露范围。缺实际管道建成日和逐年地图 |
| 基准前能源利用可能并存或已停止 | [2020 场址标签](results/temporal/run_005/landmark2020_cohort.csv) · [来源表](results/mainline/run_006/source_ledger.csv) | 档案标签只来自基准快照。Keller Canyon 和 Coastal Plains 供解释，未经全面逐场重建 |
| 报告收集气 CH₄ 浓度在登记时间前后高约 4 个百分点 | [分期比较](../outputs/2026-11-09_rng_cs_did/run_001/additionality_cs_did_summary.json) · [计量复核](../workspaces/rng_advanced_stats_001/run_006/MANUSCRIPT_UPDATE.md) · [补图](figures/mainline_figS01_reported_outcomes.svg) | 次要报告指标。+3.97 pp 来自分期比较，补图为旧登记 TWFE 事件窗。回收量与气量的趋势调整区间跨零，计量边界仍待证 |

对运行线旧图 2，原绘图函数寻找 `k0` 等字段，保存 JSON 的键实际为 `ev_k0` 等。三个面板原匹配点均为 0。修正版逐面板画出 9 个点，含 ≤−5 和 ≥4 的合并箱，使用原输出设施聚类标准误乘 1.96。原数据和原图在旧目录。 [图形对账](results/figures/run_003/figure_checks.json) · [27 个图点](results/figures/run_003/ghgrp_figure_data.csv)

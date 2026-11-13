# 主稿修订提纲

## Title

*Pipeline proximity and landfill renewable natural gas deployment in the United States*

## Abstract results draft

> In a common eligibility frame of 1,819 landfills, treating all eligible project status entries as events yielded 46 recorded starts in 2024. Restricting the registry to operating or shut-down projects yielded 10, and reconciliation against available public records yielded 18. Across 1,317 landfills in 29 states with event support under all compared rules, the reconciled specification included 114 events. The estimated annual odds ratio per doubling of mapped pipeline distance was 0.91 (95% spatial interval 0.81–1.01). The paired change in the log-distance coefficient from the original operating or shut-down specification was 0.016 (95% spatial interval −0.022 to 0.055). A separate August 2020 landmark analysis gave a directionally similar association using contemporaneously available mapped distance and baseline waste in place, with wider uncertainty. The registry definition had a substantial influence on the apparent 2024 deployment count.

上段的「common eligibility frame」指三种描述计数的共同 1,819 场。第二段落的州支持另从中限制。首次事件有外部记录、部分核对和登记支持几种证据等级。正式摘要可再减字。

## Introduction

- 以实际投运识别和基础设施邻近度为主问题。明尼苏达 Hoffman 等使用项目规模、融资、实体与虚拟管线比较技术经济可行性。本文分析有历史项目状态的填埋场实际部署记录，并区分日期、状态与样本对历史部署监测的影响。 [Hoffman 等，PDF 第 4–5 页](../inputs/public/rng_adoption_review_2026-11-04/Minnesota_RNG_2024_NSF.pdf)
- Li 等已有 1991–2010 年填埋气能源项目与政策的采纳分析。Wehner 等 2025 年会议稿在奶牛场消化器样本用管线距离与规模的 logit 和交互。本文增量是对现代管道 RNG 首次持续供气的证据处理及其可量化后果。 [Li 正式版](https://doi.org/10.1016/j.eneco.2015.03.022) · [Li 工作稿，PDF 第 9 页](../inputs/public/rng_adoption_review_2026-11-04/RFF_DP_14_17.pdf) · [Wehner 等，PDF 第 3、10–11、16 页](../inputs/public/rng_adoption_review_2026-11-04/Wehner2025_conference_access_attempt.pdf)

## Methods

1. 交代 2024 年 9 月登记快照、1995–2024 历史窗口与全年外部资料核查边界。主要单位为首次向处理与注入链供气的填埋场。另留 LMOP 完整项目编号、父编号、GHGRP ID 和已知处理系统，来源与裁定分开保存。
2. 列登记严格与宽代理、状态与日期四格和相同共同支持。共同资格下按每场事件年重新计算风险时间。日历用六个固定时期，配州效应、快照 WIP 及空间得分区间。用桥接表说明为何旧 ridge 模型仍可复现，但新版采用可有限估计的基线。
3. 2020 年作为互补分析，分别报告冻结可用协变量、终点登记与外部筛查，以及地域事件支持。明确最近管线是映射邻近度。

## Results

- **第一节　核正改变 2024 年部署曲线。** 主文图 1 放同描述框下的 46／10／18，并报告 1995–2024 累计 142／106／115。表例用 Fresh Kills 和 McCarty 展示窗前投运，用 Prairie View 展示移年，用 Elliott 和 Cefe 展示同厂不同供气事件。Lemons、Quad Cities 和 North Country 解释为什么部分 2024 归属进入未知情景。 [年度表](results/mainline/run_006/annual_deployments.csv) · [事件变化表](results/mainline/run_006/changed_landfill_events.csv)
- **第二节　关联在统一样本中保持同向。** 主文表展示 1,317 场共同支持的四格和宽代理。配对 ln 距离差 +0.016 的区间容许小幅双向变化。将全地理无州效应、共享项目、测量年份、截止年份和高影响点检查放补充材料。全地理筛查和共州模型使用不同分母。 [模型](results/mainline/run_006/deployment_comparisons.csv) · [配对差值](results/mainline/run_006/paired_deployment_differences.csv)
- **第三节　当时可获得信息给出互补但有限的证据。** 2020 图用同坐标比较 EIA 与 HIFLD。解释 48 候选如何变成 44 个登记结局及 45 个证据筛查结局，标出 17 未定与 7 失访。保留共用场址、图层相似与固定终点区别。 [2020 报告](temporal_complement_2020.md)

## Discussion and supplement

**能源利用仅作解释。** Keller Canyon 的运营方材料显示 RNG 厂用同一填埋场的既有发电厂供电。Coastal Plains 的上市披露显示发电在 2019 年 5 月结束，商业 RNG 于 2020 年 9 月开始。这两个场址说明发电与 RNG 可并存，也可能先停发电再投运。基准表分别标记在运发电、在运直接利用、并存、已停止、未登记和未知。未登记标签不代表实际没有利用。全文维持距离与部署主线。 [Keller Canyon 运营方](https://www.ameresco.com/portfolio-item/keller-canyon-rng-plant-ca/) · [Coastal Plains 10-K Item 1](https://www.sec.gov/Archives/edgar/data/1826600/000119312521102560/d103808d10k.htm)

**GHGRP 放补充材料。** 旧分期结果为登记年 0 至 +4 的报告收集气甲烷比例 +3.97 pp，原设施 bootstrap 区间 2.75–5.44。另述气量和回收量的趋势调整区间跨零。旧稿的图 2 已在补图中修复键映射，补图刻画登记时点周围的原事件研究估计，设施趋势调整的数字另列。24 个设施年仅对上公开汇总，底层仪表的同一计量范围未能核实。现稿的 `121 events`、`0.89` 和「所有带宽均显著」应改为旧规格回放，再并列新版估计。Scarpelli 等 §3.3 及补图 S7–S8 已区分报告浓度、回收与独立航空排放观测。 [计量稿](../workspaces/rng_advanced_stats_001/run_006/MANUSCRIPT_UPDATE.md) · [Scarpelli 等原文](https://doi.org/10.1021/acs.est.4c07572)

## 投稿贡献与尚需证据

论文现在能具体量化把计划和建设登记当作投运会怎样改变末年部署图，也能把这种计数变化与共同地理支持上的距离关联分开。这个贡献支持按生物能源部署研究准备 *Biomass and Bioenergy* 稿件。若独立复核和日期覆盖能支撑明确的资源化监测用途，再评估 *Waste Management*。中科院大类分区需按学校采纳的当年版本核对，本轮没有锁定分区。 [Biomass and Bioenergy 范围](https://shop.elsevier.com/journals/biomass-and-bioenergy/0961-9534) · [Waste Management 范围](https://shop.elsevier.com/journals/waste-management/0956-053X)

距离点估计仍有信息，空间区间和规模调整变化限制主张力度。114 个共同州事件中有 29 个来自外部支持或继承的年度核对类别，余 85 个依赖登记日期或保留冲突的登记代理。四条被移出的旧 2024 事件已完成独立复核：838 Lemons、1469 J.C. Elliott 与 2001 Bethlehem 收紧为确认在窗外（Elliott 的窗内事件是 Cefe 11862；Bethlehem 的 2021 首发实为破土），12144 Quad Cities 维持未定（首发约 2024 Q4 但无 dated first-gas）。复核不改变 114 计数，作者版事件表据此冻结。细节见 [独立复核记录](independent_review_4_withheld_2024_events.md)。

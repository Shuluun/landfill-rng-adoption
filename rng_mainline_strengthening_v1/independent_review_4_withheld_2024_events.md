# 四条旧 2024 归属未定记录的独立复核

日期：2026-11-10。对象：events.py 标为 `unknown_cutoff` 的四条被暂缓计入的旧 2024 事件（838 / 1469 / 2001 / 12144）——即主稿要点所点的"四条被移出的旧 2024 事件"。目的：重新读决定性公开来源，把「未知」收紧为「确认在窗外」或维持「未定」。**复核不改变 114 事件的共同核正计数**（四条均已暂缓），只提高账本的透明度与措辞精度。

> 范围说明：run_006 事件账本里 `unknown_cutoff` 共 7 行。本复核覆盖其中被主稿点名的 4 条（838/1469/2001/12144）。另 3 条（1080 East Carolina、1150 Wayne County、1539 Bayview）是早前 never_operational 审计中已记录为"不确定"的场址，各自已有裁决备注，不在本轮范围；其状态同样为暂缓、不影响 114 计数。

## 方法

对四条的决定性来源逐一重新抓取（WebFetch）。businesswire 一处返回 HTTP 403，改用同内容行业转载（Rigzone / Hydrocarbon Engineering）+ SEC 10-K 原文 + WebSearch 补查。抓取成功与否如实记录。

## 逐条结论

### 838 Lemons East/West（MO）→ 确认在窗外（2024-08-31 之后）

- [LEMONS_NOV](https://www.kbsi23.com/news/a-new-natural-gas-plant-in-dexter-is-set-to-begin-operations-in-the-coming-weeks/)（2024-11-13，重新抓取确认）：工厂"set to begin operations in the coming weeks"，**未给具体日期、未称已在注气**。
- [LEMONS_PSC](https://efis.psc.mo.gov/Document/Display/851695)（2025-09-30 备案）：描述 Lemons East → Enbridge 的运行线与州际注气，属 2025 年备案。
- **裁定**：2024-11 剪彩、运行"数周内"，最早也在 2024 年 8 月 31 日截止之后。原 `unknown_cutoff` 可收紧为 **confirmed_post_cutoff**（登记 2024-12-31 Planned 本就非运行状态）。

### 1469 J.C. Elliott（TX）→ 确认在窗外（Elliott 自身供气线）

- [CORPUS_APR](https://www.corpuschristitx.gov/news/posts/landfill-gas-to-energy-plant-exceeds-expected-annual-revenue-in-its-inaugural-year/)（2025-04-09，重新抓取确认）：Cefe Valenzuela 厂"opened one year ago this week"（≈2024-04 初，**在窗内**）；J.C. Elliott 供气线"completing a pipeline connecting the J.C. Elliott Landfill to the Cefé Valenzuela Landfill"（**近期完成，未给日期**）。
- **裁定**：登记 2024-04-10 的"Combination Project"日期反映的是 Cefe（11862）的投运，不是 Elliott 的首次供气。Elliott 线约 2025 初完成 → Elliott（1469）为 **confirmed_post_cutoff**；在窗内事件是 Cefe（11862），二者是共用系统（`corpus_christi`）。

### 2001 North Country / Bethlehem（NH）→ 确认在窗外（2021 仅为破土，投运 2025）

- [Casella/Rudarpa 破土新闻稿](https://ir.casella.com/news-releases/news-release-details/casella-and-rudarpa-break-ground-renewable-natural-gas)（2021-05-20，钉源成功）：先前浮现的"2021 首发"实为 **2021-05-19 破土动工（groundbreaking）**，非投运；工期约 13 个月，属建设启动。
- [NY Green Bank 交易档案](https://greenbank.ny.gov/-/media/greenbanknew/files/NYGB-Transaction-Profile-RUDARPA.pdf)：2021-01 提供 2,950 万美元"construction-to-term"贷款——同样指向建设阶段，非投运。
- [NCES_SEC（Casella 10-K，财年止 2024-12-31）](https://www.sec.gov/Archives/edgar/data/911177/000091117725000010/cwst-20241231.htm)（重新抓取确认）："We are party to an agreement for the construction of a landfill renewable natural gas (RNG) facility … which will be constructed, owned and operated by a third party"——**财年结束（2024-12-31）仍为未来/拟建，未投运**。
- [Viridi–Énergir offtake（2024-07-24）](https://www.rigzone.com/news/viridi_inks_20year_deal_to_deliver_rng_to_energir-25-jul-2024-177524-article/)（businesswire 403，经 Rigzone/Hydrocarbon Engineering 复核）：20 年协议，**交付自 2025 年起**；覆盖 Bethlehem/Brunswick/Marathon 三厂。Viridi 2023 Q4 收购的该项目在 [portfolio 页](https://www.viridirng.com/portfolio-info?ID=76154)仍写作"once fully operational"（尚未完全投运）。
- **裁定**：收紧为 **confirmed_post_cutoff**。"2021 首发"已钉为破土（非投运）；2023 Q4 仍"in-progress"、2024 财年备案仍"未建"、Énergir 交付 2025 起——多源一致，窗内（≤2024-08-31）无投运事件。附带记录：因当地无管道互联，该项目用 CNG 卡车"虚拟管道"外运，严格说未必算"管道注气"事件（此处仅按日期裁定，不影响 cutoff 判定）。

### 12144 Quad Cities / Milan（IL）→ 维持未定（首发约 2024 Q4，但无 dated first-gas）

- [QUAD_PINE](https://www.pinecreekrng.com/projects/quad-cities)（重新抓取确认）："currently flowing 1,400 SCFM" 注入 Kinder Morgan 州际管道，**但无 first-gas / commercial operation 日期**。
- [QUAD_AVISTA](https://www.pinecreekrng.com/pr/avista-signs-new-renewable-natural-gas-contract)（2024-01-29）：2024 协议描述 Milan 的"future production"（尚未产出）；同批报道称建设"expected complete by end of 2024"、Avista IRP 载交付预计 2024 Q4。2026-05 的 [Constellation 发布](https://investors.constellationenergy.com/node/10041/pdf)已把 Quad Cities 列为五座在运 Pine Creek 厂之一（现已在流）。
- **裁定**：维持 **unknown_cutoff（暂缓）**，但措辞更精确：首发极可能落在 2024 Q4（截止 2024-08-31 之后），唯缺 dated first-gas 无法百分百排除 2024 年 8 月早投运。
- **身份核对**：账本中另有一场 511「Upper Rock Island County LF」（East Moline，Ameresco/Republic Services，reg_year 2025）与 12144「Quad Cities Landfill Phase IV」（Milan，Pine Creek/Millennium Waste，reg_year 2024）是**两场不同设施**，账本已正确分列、无身份混淆。[Ameresco/Republic Services 稿](https://www.ameresco.com/our-quad-cities-renewable-natural-gas-facility-operates-at-upper-rock-island-county-landfill-east-moline/) 描述的是 511（East Moline），非 12144。
- **检索结论**：经多轮检索（Pine Creek 项目页、Avista 2024-01 稿、Constellation 2026-05、当地/行业转载），12144 的 dated first-gas **无公开来源**；所有来源只给"2024 年底投产/交付"的预期或"现已在流"的无日期现状。故维持 unknown_cutoff，此为公开信息可及范围下的**最终结论**（非待续查）；仅当未来出现 Kinder Morgan 互联记录或当地首发报道时才可改判。

## 净结论

| 场 | 原状态 | 复核后 | 依据 |
| --- | --- | --- | --- |
| 838 Lemons | unknown_cutoff | **confirmed_post_cutoff** | 2024-11 剪彩 + "数周内"运行 |
| 1469 Elliott | unknown_cutoff | **confirmed_post_cutoff** | 供气线 2025 初完成；窗内是 Cefe(11862) |
| 2001 Bethlehem | unknown_cutoff | **confirmed_post_cutoff** | 2021 仅为破土；2024 财年备案未建；Énergir 交付 2025 起 |
| 12144 Quad Cities | unknown_cutoff | **仍未知**（首发约 2024 Q4） | 在流但无 dated first-gas |

- **事件计数不变（114）**：四条均已暂缓，复核把其中三条（838/1469/2001）的标签从"未知"收紧为"确认在窗外"，12144 维持"未定"但已把首发定位到约 2024 Q4。
- **一处抓取失败**（businesswire 403）与**一处仍未钉源**（Quad Cities dated first-gas）均已如实记录，未据此改判。
- 账本 `evidence_status` 已新增 `confirmed_post_cutoff` 取值并改标完成（2026-11-10，见下方"已完成"）：events.py 新增分支（revised_year=NA、updated_status_qualified=False、milestone=documented_post_cutoff_operation），ambiguous 集合（第 203 行）**不含**它。主口径 114 计数与系数不变；`scenario_unknown_at_registered_year` 敏感场景未定条数 7→4（n_events 124→121）。temporal 侧同步新增 post-cutoff 覆盖（否则 1469 会按登记"Operational 2024-04-10"被误计为窗内事件）。全量再生成 + 验证套件通过。

## 已完成（2026-11-10）

1. ~~三条（838/1469/2001）改标 `confirmed_post_cutoff`~~ **完成**：events.py 新增第 185 行分支（revised_year=NA、updated_status_qualified=False、milestone=documented_post_cutoff_operation），第 203 行 ambiguous 集合**不含**它。主口径 114 计数与系数不变；`scenario_unknown_at_registered_year` 敏感场景未定条数 7→4（n_events 124→121）。temporal.py 同步新增 post-cutoff 覆盖（否则 1469 会按登记"Operational 2024-04-10"被误计为窗内事件）。全量再生成 + 验证套件通过（mainline run_007 / temporal run_007 / figures run_004 / checks run_004）。
2. 12144 Quad Cities 已穷尽公开检索、无 dated first-gas，维持 unknown_cutoff（**最终结论，非待续查**）；仅当未来出现 Kinder Morgan 互联记录或本地首发报道时才可改判。
3. 附带：Bethlehem 用 CNG 卡车"虚拟管道"外运（无管道互联），严格说未必属"管道注气"事件——若未来细化事件定义可单列审查。
4. 若继续扩大复核，可覆盖另 3 条 `unknown_cutoff`（1080 East Carolina / 1150 Wayne County / 1539 Bayview），其现裁决备注均为"未定/预测未观测"，不影响 114 计数。

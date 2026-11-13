# Pipeline Proximity and the Deployment of Landfill Renewable Natural Gas in the United States

*Research manuscript for review | 10 November 2026*

## Abstract

Landfill renewable natural gas (RNG) projects can inject upgraded gas into existing pipelines. Project registries record start dates and current status, but these fields do not consistently identify when injection began. We combined the September 2024 US Environmental Protection Agency landfill registry with mapped natural gas pipelines, reviewed public records for projects listed only as planned or under construction, and estimated the association between distance and pipeline-injection deployment in a retrospective landfill-year panel. Of 36 sites in that status group, 13 were assigned an operating year within 1995–2024, nine began operating after the window, 11 lacked evidence of an eligible operating event or had a verified reason to exclude it, and three remained unresolved. The reconciled state-adjusted model included 121 events at 1,502 landfills. Doubling distance to the nearest mapped pipeline was associated with 0.89 times the conditional annual odds of a deployment event (95% spatial interval, 0.80 to 0.99, using a 100 km cutoff). In a secondary analysis of facility reports, the methane fraction of collected landfill gas was 3.97 percentage points higher around registered starts relative to the comparison trend. Audits of two pairs of sites could not establish a common measurement boundary, and the within-site change at Coastal Plains reversed sign when the transition year was excluded from the baseline. These findings quantify how operating evidence changes the registry event count while documenting the limits of what the linked records can establish about landfill gas after deployment.

**Keywords:** landfill gas, renewable natural gas, pipeline injection, project registry, spatial dependence

## Introduction

Landfill gas can be flared, used to generate electricity or heat, or upgraded to renewable natural gas for delivery by pipeline or another route. These uses share a source of gas but involve different equipment and connections. Distance to a mapped natural gas line provides a way to characterize the geography of potential pipeline access. The costs and feasibility of interconnection also depend on the actual delivery point, route, pressure, capacity, and arrangements with the network operator. Work on US dairy digesters has already considered distance to pipelines alongside farm size and geography [1]. The question here is how much the landfill association depends on whether registry entries correspond to operating events within the study window.

The US Environmental Protection Agency (EPA) Landfill Methane Outreach Program (LMOP) database reports landfill characteristics and projects at different stages of development [2,3]. A start year attached to a project still listed as planned can describe an anticipated date or a date that precedes a status update. A project recorded as shut down may have operated earlier. Grouping those records by status alone can omit projects that began operating and include projects that did not. We quantify how a targeted reconciliation changes the deployment event set and examine whether the distance association persists under the revised labels.

As a separate question, we examine facility-reported methane concentration around registered starts. Scarpelli et al. [4] reported higher methane fractions in collected landfill gas in years with RNG at a subset of high-emitting Texas facilities and found variation in methane recovered. They also studied airborne emissions, which measure a different quantity. Our analysis uses a larger reporting panel and a registry-based comparison, then examines whether operating dates and the underlying measurements support its interpretation.

## Data and Methods

### Landfill registry and mapped pipelines

We used the September 2024 LMOP composite workbook and the Homeland Infrastructure Foundation-Level Data map of interstate and intrastate natural gas pipelines [2,5]. We treated the landfill as the deployment unit and aggregated project records by Landfill ID. We retained mapped sites in the contiguous United States with valid coordinates, a usable pipeline distance, positive waste in place, and a recorded opening year. We excluded sites whose dated pipeline-injection projects all preceded 1995. After these filters, 1,821 sites qualified for the retrospective panel before any model-specific state exclusions.

The distance measure is the spherical distance in kilometres from the LMOP site coordinate to the nearest mapped pipeline segment identified by a geographic candidate search. The spherical and local projection calculations used the same candidate search. We used the spherical measure in the reported model. Distance and waste in place were log transformed and held constant across years using their respective snapshots. The exposure measures proximity to mapped infrastructure. Connections through a lateral, gathering or distribution lines, and gas delivered by truck may follow different routes or be absent from the map.

### Event definitions and external records

The two original definitions took the earliest valid 1995–2024 start year for a pipeline-injection project under each status rule. One admitted Operational and Shutdown records. The broader rule also admitted Planned and Construction records. We audited project records using publicly available regulatory filings, operator statements and other dated records. For each review, the evidence table distinguishes the operating event described by the source from the analysis year assigned to the landfill. Evidence of a planned date, construction or a later expansion is kept separate from evidence of operation.

The first audit was a stratified draw of 30 out of 145 landfills with a valid registered pipeline-injection start year. Strata combined three eras with status and prior energy use, and the sampling scheme gave some strata higher inclusion probabilities. We report unweighted counts within this audit. A second review covered the 36 landfills in the audit frame with no pipeline-injection record listed as Operational or Shutdown. The two reviews share 10 Landfill IDs. The second review supplied the corrections to the model. The unverified operating year was retained as 2024 for Lemons and Quad Cities, both of which had evidence of operation by the time of review. Unresolved records were excluded from the event set and treated as event-free through the study window in this specification.

### Deployment model and spatial uncertainty

We constructed landfill-years from the later of opening and 1995 through the assigned event year or administrative censoring in 2024. A landfill with an assigned event before entry supplied no at-risk observations under the implemented rule. The discrete-time logit estimated the conditional annual odds of the recorded or reconciled pipeline-injection event among landfills still at risk under these rules. The specification included log distance, log waste in place, state indicators, and calendar-year indicators for years with events, with other years pooled as the reference. States without outcome variation were omitted. This construction means that changing the event definition can change state inclusion as well as the timing of risk-set exits.

We report landfill-clustered standard errors and spatial standard errors calculated from the landfill-level sums of logit scores. The spatial covariance uses a Bartlett kernel with weights declining linearly to zero at cutoffs of 25, 50, 100, 200 and 400 km [6]. We show the 100 km interval in the text and report the range across the five cutoffs. The odds ratio for a doubling of distance is exp(β × ln 2). These uncertainty estimates address the specified spatial dependence. The distance association also depends on the adequacy of the model and its snapshot covariates.

The logit was fit by iteratively reweighted least squares with a small ridge penalty (λ = 10⁻⁶) for numerical stability; the final gradient norm was 1.4 × 10⁻¹¹, indicating convergence. The intercept and the calendar-year coefficients, whose reference category pools all at-risk years without an event, are nearly collinear with one another (information-matrix condition number ≈ 2.6 × 10⁹, and the unpenalized Hessian is numerically singular); their individual values are not separately identified and are used only to absorb baseline hazard heterogeneity, not interpreted. The log-distance coefficient and its clustered and spatial standard errors are computed from the score contributions and are unaffected by this nuisance collinearity.

### Secondary analysis of reported methane concentration

We linked LMOP to the frozen 2010–2023 Greenhouse Gas Reporting Program (GHGRP) Subpart HH gas collection panel using GHGRP facility IDs [7]. The panel contained 12,176 unique facility-years for 1,040 facilities, of which 1,038 matched LMOP. This is an administrative link. A landfill, an energy project, a GHGRP facility and the gas stream covered by a reporting point can have different boundaries. LMOP also draws on GHGRP for some fields [3].

We used the earliest valid registered pipeline-injection start year linked to a facility as event time. Eligibility separately required a linked pipeline-injection record classified as Operational or Shutdown and at least one usable concentration observation before and at or after the event. The comparator pool had no linked LMOP RNG record. We used a group-time comparison in the style of Callaway and Sant’Anna [8]. Within each event cohort we compared the change from year −1 among RNG facilities with the contemporaneous change among comparators observed in both years. The aggregate across event years 0 to +4 weights periods by the number of contributing RNG facilities. The interval is based on 999 facility-level bootstrap draws (seed 12345).

Two purposively selected pairs, Coastal Plains and Camelot in Texas and Roosevelt and LRI 304th Street in Washington, were reviewed to assess comparability. We compared public facility-year summaries with the frozen panel, recorded dated changes in equipment and downstream use, and searched for historical analyzer and branch diagrams and the inputs to annual averages. We used separate evidence for commercial operation, earlier shutdown or conversion, and the point where methane concentration was measured.

## Results

### Reconciliation of pipeline injection events

In the stratified sample of 30 landfills, 19 records were classified as consistent with external evidence, ten had a status or operating-event discrepancy, and one remained uncertain. All ten discrepancies occurred among the sampled sites without an Operational or Shutdown pipeline-injection record. Four had no qualifying operating event in the relevant classification, and six were in operation despite the earlier status. The 10 of 29 figure is the observed fraction among resolved cases in this sample. Unequal inclusion probabilities and the unresolved record limit its use as a population estimate.

The review of all 36 sites in the targeted registry group produced 22 late operating cases, 11 without an eligible event or with affirmative evidence for exclusion, and three unresolved. Of the 22 late operating cases, 13 entered the event set by 2024 and nine began after the window. The revised labels brought the two original event definitions to the same 121 events. This convergence reflects the use of the same reconciliation in both definitions. It does not independently confirm all 121 dates.

**Table 1. Deployment estimates by event definition**

| Event definition | Landfill-years | Events | Log-distance coefficient | Landfill-clustered p |
| --- | ---: | ---: | ---: | ---: |
| Original broad status rule | 47,076 | 144 | −0.184 | 0.004 |
| Original Operational or Shutdown rule | 38,107 | 108 | −0.171 | 0.018 |
| Reconciled event labels | 43,593 | 121 | −0.169 | 0.016 |

All rows use the state-adjusted model. Because states without outcome variation are omitted separately, these are comparisons across specifications and their available samples.

### Pipeline proximity and deployment

The reconciled specification included 1,502 landfills and yielded a log-distance coefficient of −0.169. With the 100 km spatial cutoff, the standard error was 0.077 (p = 0.028), corresponding to an odds ratio of 0.89 (95% interval, 0.80 to 0.99) for a doubling of distance. Across the five cutoffs, p ranged from 0.015 to 0.028. The original Operational or Shutdown model contained 1,319 landfills and estimated a similar coefficient of −0.171. The revised specification included an additional state with outcome variation. The two point estimates indicate a similar directional association under these specifications. They do not isolate the change due solely to event labels on a fixed sample.

### Reported concentration around registered starts

The group-time comparison included 69 RNG facilities and a comparator pool of 823 facilities. The estimated difference in changes in reported collected-gas methane concentration was **+3.97 percentage points** for event years 0 to +4 (original 95% facility-bootstrap interval, +2.75 to +5.44). Support across these periods declined from 69 to 51, 43, 36 and 31 RNG facilities. The year −2 contrast relative to year −1 was −1.25 percentage points (pointwise 95% interval, −2.45 to −0.10), indicating that a pre-event difference is plausible. The post-registration coefficients do not follow a fixed set of sites.

The separate facility-trend specification gave a concentration estimate of +3.98 percentage points. In that specification, reported methane recovery was estimated to be +0.76% higher (approximate 95% interval, −8.47% to +10.91%) and reported collected-gas volume was +14.2% higher (−20.8% to +64.6%). These models have different estimating samples and estimands. Recovery and flow intervals are compatible with a range of changes, including decreases. The three reporting fields also share measurement inputs [7].

### Baseline sensitivity at Coastal Plains

Electricity generation at Coastal Plains stopped in May 2019, and commercial RNG production began in September 2020 [9]. With 2021–2022 fixed as the follow-up, the facility’s mean reported concentration was 53.140%. Relative to the 2017–2019 mean of 52.683%, the change was **+0.457 percentage points**. Relative to the 2017–2018 mean of 53.565%, it was **−0.425 percentage points**. The first baseline includes the year in which power generation ended. The reversal demonstrates that this single-facility description depends on how the operating transition is placed in the window. It is a separate diagnostic from the 69-facility comparison.

![Coastal Plains annual reported methane concentration](coastal_baseline.png)

**Figure 1. Coastal Plains annual reported methane concentration.** Shading identifies 2019, the year electricity generation ended. The commercial RNG start year (2020) is excluded from both baseline calculations and from follow-up. Points are public annual values for collected landfill gas.

### Measurement comparability across years

Public summaries agreed with the frozen data for all 24 audited facility-years. The available underlying records did not permit reconstruction of the reported annual concentration for any of them. At Roosevelt, label ML 3 was associated with the former power plant in 2018 and with the RNG branch in 2019 [10,11]. The available permit and later flow diagram describe gas management and downstream routes, but do not connect the label to the physical analyzer and upstream gas stream across both years [12]. For LRI, county permits identify a gas management plan and an operating plan, and annual reports document measurements from subsurface migration probes and the installation of extraction wells. The available records do not connect those observations to the collected-gas measurements entering the federal annual average [13]. Differences in measured gas streams or in how annual concentrations were compiled could therefore contribute to an apparent change.

## Discussion

Closer proximity to mapped gas pipelines was associated with higher conditional annual odds of pipeline-injection deployment in the eligible registry panel. The reconciliation materially changed the event count while leaving the distance coefficient similar to that from the original Operational or Shutdown rule. A registry used to study deployment benefits from distinct fields for planned start, operating milestones and status as of the snapshot date, with links to the evidence behind each. For this study, documenting the event rule and its consequences is as important as estimating the proximity coefficient.

The retrospective panel uses the 2024 registry, rather than a sequence of historically frozen risk sets. An August 2020 snapshot yielded 48 candidate changes in registered operating status by 2024 in a separate comparison. These candidates were not adjudicated as a cohort of new deployments. The static pipeline and waste measures can differ from conditions at the time projects were planned. State effects and spatial covariance leave local market conditions, the history of the gas network, and project siting decisions as possible explanations for the association. We also lack a direct measure of the physical interconnection route. The result characterizes the association for the specified registry sample and event definitions.

The secondary comparison describes the methane fraction reported for collected landfill gas. Its bootstrap interval reflects variation under the fitted registration-based specification. It leaves uncertainty about actual commissioning dates, pre-event trends, and measurement comparability unquantified. The timing of conversion at Coastal Plains and the incomplete measurement records illustrate two reasons a reported difference may not represent a change in the same gas stream. The case audits were purposive and do not estimate the prevalence of these problems. We did not estimate HonestDiD sensitivity intervals because the audited records and independent comparator support did not meet the study criteria. Reported collected-gas concentration, methane recovered, and site-wide methane emissions are different quantities. The analysis leaves the effects of deployment on total emissions and net mitigation unresolved.

## Conclusion

Landfills closer to mapped gas pipelines had higher conditional annual odds of pipeline-injection deployment in the reconciled registry panel. External records changed which projects counted as events without materially changing the estimated distance coefficient across the reported specifications. In a separate panel, reported methane concentration was higher around registered starts, but the case audits identified uncertainty in both the operating baseline and the measurements contributing to the annual average. The deployment result is the principal finding. The concentration comparison documents an association in reporting data and identifies what would need to be measured to interpret a physical change.

## Data and Code Availability

The source data are the EPA LMOP September 2024 composite file, the public HIFLD pipeline layer and the EPA GHGRP Subpart HH reporting table [2,5,7]. The archived inputs, exact commands, model outputs and evidence ledgers used to prepare this draft are indexed in the accompanying provenance note. The current archive is local.

## References

[1] Wehner J, Wolf C, Zhang W. Farm level drivers of anaerobic digester installations on dairy farms across the US. AAEA and WAEA Joint Annual Meeting, Denver, 2025. https://ageconsearch.umn.edu/record/360639

[2] US Environmental Protection Agency. LMOP Landfill and Project Database. September 2024 composite workbook. https://www.epa.gov/lmop/lmop-landfill-and-project-database

[3] US Environmental Protection Agency. Frequent Questions about Landfill Gas. https://www.epa.gov/lmop/frequent-questions-about-landfill-gas

[4] Scarpelli TR, Cusworth DH, Duren RM, et al. Investigating major sources of methane emissions at US landfills. Environmental Science & Technology. 2024, 58(49), 21545–21556. https://doi.org/10.1021/acs.est.4c07572

[5] US Department of Homeland Security. Natural Gas Pipelines. Homeland Infrastructure Foundation-Level Data. https://catalog.data.gov/dataset/natural-gas-pipelines

[6] Conley TG. GMM estimation with cross sectional dependence. Journal of Econometrics. 1999, 92(1), 1–45. https://www.sciencedirect.com/science/article/pii/S0304407698000840

[7] US Environmental Protection Agency. Subpart HH Information Sheet and GHGRP Reported Data. https://www.epa.gov/ghgreporting/subpart-hh-information-sheet

[8] Callaway B, Sant’Anna PHC. Difference-in-Differences with multiple time periods. Journal of Econometrics. 2021, 225(2), 200–230. https://doi.org/10.1016/j.jeconom.2020.12.001

[9] Montauk Renewables, Inc. Form 10-K for the year ended December 31, 2020. Item 1, Coastal Plains. https://www.sec.gov/Archives/edgar/data/1826600/000119312521102560/d103808d10k.htm

[10] US Environmental Protection Agency. Roosevelt Regional Landfill, GHGRP 1003676, reporting year 2018. https://ghgdata.epa.gov/ghgp/html/2018.do?et=undefined&id=1003676

[11] US Environmental Protection Agency. Roosevelt Regional Landfill, GHGRP 1003676, reporting year 2019. https://ghgdata.epa.gov/ghgp/html/2019.do?et=undefined&id=1003676

[12] Washington State Department of Ecology. Roosevelt Regional Landfill Notice of Construction revision application DE90-C153. Appendix C, 2023. https://ecology.wa.gov/getattachment/8b06acfa-7543-44dc-9712-5aa33cadaf84/20230628RLFExpanNOCApp.pdf

[13] Tacoma-Pierce County Health Department. LRI Landfill Permits and Reports. Solid Waste Permit 27-650 and annual monitoring reports. https://tpchd.org/environment/lri-landfill/permits-and-reports/

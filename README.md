# Landfill renewable natural gas (RNG) adoption — analysis code

Research code for the study of **pipeline proximity and landfill RNG (renewable natural gas) deployment in the United States**, and of the association between **RNG adoption and facility-reported methane gas collection**.

> Status: research in progress; manuscript under preparation. This repository contains the analysis code, the manuscript draft, and the auditable evidence tables. Raw public datasets are not committed — see [DATA.md](DATA.md).

## Study in brief

Two connected lines of analysis:

1. **Driver (deployment).** Reconciling the EPA LMOP registry's project status/dates against public records to build a first-injection event ledger, then estimating the conditional annual odds ratio of deployment per doubling of mapped pipeline distance, with spatially clustered (Conley HAC) inference. A 2020 landmark cohort checks that baseline information precedes the outcome.

2. **Additionality (reported methane collection).** Event-study / difference-in-differences of facility-reported landfill-gas methane concentration, gas flow, and recovered methane around first RNG injection, with robustness checks: placebo adoption year, wild cluster bootstrap, Romano–Wolf multi-outcome adjustment, Callaway–Sant'Anna staggered DiD, and Rambachan–Roth (HonestDiD) sensitivity to parallel-trends violations.

These are associations of deployment/reporting, **not causal policy effects**. Registry-defined events carry measurement error that is quantified by audit (see the never-operational verification below).

## Repository layout

```
src/                          Reusable library (LMOP/GHGRP linkage, evidence, quantitative helpers)
rng_mainline_strengthening_v1/  Mainline deployment (driver) analysis: self-contained, reproducible
  ├── src/                      mainline scripts (run_main, reproduce_legacy, temporal, figures, verify)
  ├── event_ledger.csv          per-project first-injection event ledger
  ├── source_ledger.csv         source locations + audit status
  ├── deployment_comparisons.csv  counts & distance estimates across event-definition rules
  ├── figures/                  main figures (PNG + SVG)
  └── *.md                      scope, claims→evidence index, reproduction & revision notes
analysis/                     Additionality / inference scripts (versioned by date)
manuscript/                   Manuscript draft (Markdown)
inputs/  outputs/             Staging placeholders for data and outputs (not committed)
```

## Key results map

**Driver (deployment)** — see `rng_mainline_strengthening_v1/claims_to_evidence.md` for the full claims→evidence index.

| Result | Where |
| --- | --- |
| Reconciled main model: ~114 events, common-state annual odds ratio ≈ 0.91 per distance doubling (spatial interval ≈ 0.81–1.01) | `rng_mainline_strengthening_v1/src/run_main.py`, `deployment_comparisons.csv` |
| Original corrected spec: 1,502 sites, 43,593 site-years, 121 events, ln-distance −0.169 (100 km Conley SE 0.077) | `rng_mainline_strengthening_v1/src/reproduce_legacy.py`, `baseline_reproduction_report.md` |
| 2020 landmark cohort: OR ≈ 0.92 (interval ≈ 0.79–1.07), 45 events | `rng_mainline_strengthening_v1/src/temporal.py`, `temporal_complement_2020.md` |
| Trunk-vs-intrastate pipeline decomposition (signal carried by interstate trunk lines) | `analysis/driver_pipeline_endogeneity_20261110.py` |

**Additionality (reported collection)** — see `manuscript/MANUSCRIPT.md`.

| Result | Script |
| --- | --- |
| Methane concentration DiD ≈ +3.97 pp (facility bootstrap 2.75–5.44) | `analysis/additionality_concentration_stable_20261109.py`, `analysis/additionality_cs_did_20261109.py` |
| Wild cluster bootstrap: +3.98 pp (2.66–5.27); Romano–Wolf: concentration survives, recovery/flow null | `analysis/wild_cluster_bootstrap_romano_wolf_20261109.py` |
| HonestDiD / Rambachan–Roth breakdown: M̄* ≈ 1.27 (all) / 1.16 (new) / 0.52 (switch) | `analysis/honest_did_relative_magnitudes_20261109.py` |
| Placebo adoption year: 0/999 permutations exceed the observed statistic | `analysis/placebo_adoption_year_20261109.py` |
| Mechanism channels: well count +0.14 log (p≈0.005), collection capacity +0.12 log (p≈0.028), efficiency flat | `analysis/additionality_mechanism_consistency_20261109.py` |
| Physical identity residual (recovered ≈ flow × concentration): no jump at adoption | `analysis/additionality_identity_residual_20261109.py` |
| 36-facility never-operational audit: 33.3% false adoption (11/33) | `analysis/merge_never_operational_36_20261109.py` |

## Honest limitations

- Distance → adoption is an **association**; the pipeline layer lacks build-year data, so temporal precedence is not established (the 2020 landmark analysis is the time-ordering complement).
- The concentration "quality additionality" is robust at the all/new level but **fragile for the switch subgroup** (HonestDiD M̄* ≈ 0.52).
- Reported gas fields (flow / concentration / recovered CH4) are **three independent measurements** that do not reconcile tightly at the facility-year level (within-facility std ≈ 0.65 log in the identity residual).
- Registry-defined deployment events are measured with error; the 36-facility audit found 33.3% false adoption among never-operational records.

## Reproduction

1. Stage public inputs per [DATA.md](DATA.md) and set `<PROJECT_ROOT>` where redacted.
2. Reproduce the mainline first (see `rng_mainline_strengthening_v1/README.md` for the exact run recipe).
3. Run additionality scripts from the repository root (`OPENBLAS_NUM_THREADS=1`); scripts are versioned by date — later dates supersede earlier ones.

## Provenance note

This repository was extracted from a larger private research workspace on 2026-11-12. Machine-specific absolute paths were redacted to `<PROJECT_ROOT>`. Session notes, internal handoff documents, unrelated project scripts, and non-public correspondence were excluded.

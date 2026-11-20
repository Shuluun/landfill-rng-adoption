# Landfill renewable natural gas (RNG) adoption — analysis code

Research code for the study of **pipeline proximity and landfill RNG (renewable natural gas) deployment in the United States**, and of the association between **RNG adoption and facility-reported methane gas collection**.

> Status: research in progress; manuscript under preparation. This repository contains the analysis code, the manuscript draft, and the auditable evidence tables. Raw public datasets are not committed — see [DATA.md](DATA.md).

## Study in brief

Two connected lines of analysis:

1. **Driver (deployment).** Reconciling the EPA LMOP registry's project status/dates against public records to build a first-injection event ledger, then estimating the conditional annual odds ratio of deployment per doubling of mapped pipeline distance, with spatially clustered (Conley HAC) inference. A 2020 landmark cohort checks that baseline information precedes the outcome.

2. **Reported methane collection.** Using the reconciled start years, we compare changes in reported landfill-gas methane concentration, volume, and recovered methane over the same years and facilities. We repeat the group-time comparison among facilities with stable reporting flags and use the authors' HonestDiD implementation to assess sensitivity to differential trends.

The deployment and reporting estimates describe associations. Targeted audits document differences between registry dates, operating records, and the gas streams covered by annual reports.

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

**Reported methane collection** — see the [manuscript](manuscript/MANUSCRIPT.md).

| Average difference in changes | 40 facilities, common window | 31 facilities, stable reporting flags |
| --- | ---: | ---: |
| Reported methane concentration, percentage points | +3.77 (2.63 to 5.07) | +3.51 (2.16 to 5.09) |
| Reported methane recovery, % | +28.08 (15.27 to 44.48) | +23.65 (10.14 to 41.63) |
| Reported gas volume, % | +39.70 (−4.49 to 106.04) | −2.92 (−19.68 to 13.03) |

Parentheses show 95% facility bootstrap intervals for the common-window comparison. In the expanded 39-facility sensitivity window, the HonestDiD intervals for concentration and recovery both span zero at a relative-magnitude bound of 1.

## Honest limitations

- Distance → adoption is an **association**; the pipeline layer lacks build-year data, so temporal precedence is not established (the 2020 landmark analysis is the time-ordering complement).
- The estimated concentration difference is similar across the two common-window samples. The recovery difference remains sensitive to pre-start trends.
- The reported gas volume, methane concentration, and recovered methane share measurement inputs. The decomposition uses annual report fields and is sensitive to how those fields were compiled.
- Registry-defined deployment events are measured with error; the 36-facility audit found 33.3% false adoption among never-operational records.

## Reproduction

1. Stage public inputs per [DATA.md](DATA.md) and set `<PROJECT_ROOT>` where redacted.
2. Reproduce the mainline first (see `rng_mainline_strengthening_v1/README.md` for the exact run recipe).
3. The scripts in `analysis/` include the earlier registration-based estimates. The provenance index in the local research workspace identifies the frozen inputs, commands, and outputs for the common-window results in manuscript v1.1.

## Provenance note

This repository was extracted from a larger private research workspace on 2026-11-12. Machine-specific absolute paths were redacted to `<PROJECT_ROOT>`. Session notes, internal handoff documents, unrelated project scripts, and non-public correspondence were excluded.

# Landfill renewable natural gas deployment

This repository follows the first commercial pipeline-injection events recorded for U.S. landfills. It combines the EPA LMOP project registry with public operating records and mapped natural gas pipelines. The [manuscript draft](manuscript/MANUSCRIPT.md) also examines facility-reported gas collection around the reconciled start years.

## Locked deployment results

| Event definition and geographic support | Events | Landfills | Annual odds ratio per doubling of mapped distance (95% spatial interval) |
|---|---:|---:|---:|
| Reconciled status and dates, common state support | 114 | 1,317 | 0.907 [0.814, 1.012] |
| Reconciled status and dates, expanded state support | 115 | 1,500 | 0.904 [0.812, 1.007] |
| Broad registry proxy, common state support | 134 | 1,317 | 0.896 [0.816, 0.984] |

The primary estimate uses the distance to the nearest segment in the full pipeline layer and a 100 km Conley interval. The point estimate indicates lower annual deployment odds at greater mapped distances. The interval includes one. The [complete model table](rng_mainline_strengthening_v1/results/mainline/run_007/deployment_comparisons.csv) and [evidence index](rng_mainline_strengthening_v1/claims_to_evidence.md) document the sample and comparisons.

A targeted audit examined 36 sites with a 2024 registry start and only Planned or Construction pipeline-injection records. Of the 33 resolved sites, 11 had no qualifying evidence of RNG operation. The [audit table](evidence/never_operational_full_36_final.csv) and [evidence catalog](evidence/README.md) document the cases.

## Reproduce the locked model

Stage the two public inputs in [DATA.md](DATA.md) and install the packages in [ENVIRONMENT.md](ENVIRONMENT.md).

```sh
python run_all.py verify
python run_all.py mainline
python run_all.py figures
```

The launcher writes numbered outputs to `data/derived/`. The [archive guide](rng_mainline_strengthening_v1/STATUS.md) locates the frozen tables, figures and checks. Code for the original estimator remains in [the deployment source directory](rng_mainline_strengthening_v1/src/). The [numbered pipeline](scripts/pipeline/) rebuilds its public-data inputs.

## Reported methane outcomes

The manuscript uses a common event window to compare reported methane concentration, gas volume and recovered methane with contemporaneous comparison facilities. The [reporting results and measurement audits](manuscript/MANUSCRIPT.md#measurement-comparability) document the outcome definitions and the reporting boundaries.

The earlier Python implementation has been withdrawn. A recomputation with the official R HonestDiD package (v0.2.8) was run on 2026-11-18 and will be reviewed with the advisor before results are reported. [Methods and archived receipts](honestdid_r/README.md)

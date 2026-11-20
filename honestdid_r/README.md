# Archived HonestDiD recomputation

The official R HonestDiD v0.2.8 package was used with R 4.4.1 on 2026-11-18 (Pacific time). This directory preserves the original T2 scripts, coefficient and covariance input, outputs, and environment receipts. The archive is to be reviewed jointly with Chesley before results are reported.

| Setting | Archived T2 run | Guo review, Section 3 |
|---|---|---|
| Input | Screened six-year window from event year −3 through +2. Event year −1 is the reference. | The earlier event-study coefficients and covariance include a pooled first pre-period for event years ≤−5. |
| Ordered periods | Two pre-period coefficients, −3 and −2, and three post-period coefficients, 0, +1 and +2. | Four pre-period and five post-period coefficients. |
| Target | `l_vec = c(0, 0.5, 0.5)` averages the first two years after startup. The startup-year coefficient remains in the sensitivity problem with zero target weight. | `l_vec = rep(1/5, 5)` gives equal weight to the five post-period coefficients. |
| Inference | Relative-magnitude restriction using `createSensitivityResults_relativeMagnitudes()` and the conditional least-favorable method. | The same package entry point with the longer event-study window. The pooled pre-period complicates interpreting adjacent changes as annual differences. |

The archived T2 run uses the covariance from the facility bootstrap and analyzes reported methane concentration in percentage points and reported HH-4 recovery in log units. The separate grid check records the wider endpoint search for concentration.

- [Original computation script](rng_b_t2_honestdid_20261118.R) and [original grid check](rng_b_t2_grid_check_20261118.R)
- [Coefficient and covariance input](honestdid_input.csv)
- [Concentration receipt](concentration_pp/R_RECEIPT.csv) and [session info](concentration_pp/sessionInfo.txt)
- [Recovery receipt](log_recovery/R_RECEIPT.csv) and [session info](log_recovery/sessionInfo.txt)
- [Grid check receipt](grid_check/R_CHECK_RECEIPT.csv)

The locked deployment workflow has no R stage.

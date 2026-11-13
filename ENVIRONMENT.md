# Environment

Analyses were run on Windows with:

- **Python 3.13.5**, NumPy 2.4.4, pandas 3.0.2, matplotlib 3.11.1, openpyxl 3.1.5.
  - No statsmodels / scikit-learn dependency: OLS, logistic (IRLS), cluster-robust and spatial (Conley HAC) standard errors are implemented by hand inside the scripts.
  - Set `OPENBLAS_NUM_THREADS=1` before running for deterministic single-threaded linear algebra.
- **R 4.4.1** was the intended host for the Rambachan–Roth HonestDiD reference implementation; the `HonestDiD` package was *not* installed in the local R environment, so the relative-magnitudes (M̄) sensitivity is implemented in Python
  (`analysis/honest_did_relative_magnitudes_20261109.py`), with a built-in self-consistency check (critical value at M̄=0 ≈ 1.96) and pending cross-validation against the R package.

Scripts are versioned by date (`YYYYMMDD`). Earlier versions are retained as an audit trail; the final/canonical scripts are called out in the results map in `README.md`.

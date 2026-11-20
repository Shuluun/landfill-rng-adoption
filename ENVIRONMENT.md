# Reproduction environment

Use Python 3.12 or newer. The clone repair and primary pipeline checks use Windows and Python 3.12.14. The original locked November 10 run record describes a separate Windows environment. The exact replay environment, input hashes and results are recorded at execution time.

| Package | Version used | Role |
|---|---|---|
| NumPy | 2.3.5 | Geometry, grouped risk rows and numerical estimation |
| pandas | 3.0.1 | Registry, audits, results and route keys |
| SciPy | 1.16.3 | Distribution functions and numerical diagnostics |
| openpyxl | 3.1.5 | Excel input via pandas |
| matplotlib | 3.10.7 | Deployment figures |
| statsmodels | 0.15.0 | Independent synthetic comparison in Guo's original validation script |

[requirements.txt](requirements.txt) pins the versions used for the pipeline, figures and independent comparison. The synthetic comparison used an isolated statsmodels install with patsy 1.0.3, formulaic 1.2.2, interface-meta 2.0.1, narwhals 2.29.0 and wrapt 2.5.2. The launcher sets one BLAS thread for deterministic replay. Supply public data according to [DATA.md](DATA.md).

```sh
python -m pip install -r requirements.txt
python run_all.py verify
python run_all.py mainline
python run_all.py figures
```

`make verify`, `make mainline` and `make figures` provide the same entry points for macOS and Linux. The figures command uses the locked archive by default. Use `--from-run run_NNN` to plot an explicitly named replay.

R 4.4.1 and the official R HonestDiD output from the existing November 18 analysis are reserved for joint review with the advisor. No R step is required for the locked deployment reproduction.

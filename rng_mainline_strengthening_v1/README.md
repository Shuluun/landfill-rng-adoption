# Deployment analysis

The deployment outcome is the first documented commercial pipeline-injection event at a landfill. The main model compares conditional annual deployment odds across mapped distances. Event definitions, geographic support and the supporting archives are described in the [archive guide](STATUS.md) and the [evidence index](claims_to_evidence.md).

Run these commands from the repository root after staging the public inputs in [DATA.md](../DATA.md) and installing the versions in [ENVIRONMENT.md](../ENVIRONMENT.md).

```sh
python run_all.py verify
python run_all.py mainline
python run_all.py figures
```

The new results use a fresh numbered directory beneath `data/derived/`. The [model comparison archive](results/mainline/run_007/deployment_comparisons.csv) provides the reference for a replay. Use the same event definition and geographic support when comparing estimates.

The [event ledger](results/mainline/run_007/event_ledger.csv) retains the registered date and the available public-record date bounds. The [source ledger](results/mainline/run_007/source_ledger.csv) identifies the supporting records. The [evidence catalog](../evidence/README.md) documents the independent origins of the audit inputs.

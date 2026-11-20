"""Verify and reproduce the locked landfill RNG deployment result."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from rng_paths import DERIVED, EVIDENCE, PUBLIC, ROOT
from scripts.download_public_data import MANIFEST, check

RESEARCH = ROOT / "rng_mainline_strengthening_v1"
PIPELINE = ROOT / "scripts/pipeline"
RESULTS = DERIVED / "results"
RUN_NAME = re.compile(r"run_[0-9]{3,}")


def verify():
    sources = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key, entry in sources.items():
        if entry["required_for_mainline"]:
            if not PUBLIC[key].is_file():
                raise FileNotFoundError(f"Missing {key}: {PUBLIC[key]}. See DATA.md.")
            check(PUBLIC[key], entry["sha256"])
            print(f"PASS {key} {entry['sha256']}", flush=True)
    evidence = json.loads((EVIDENCE / "provenance.json").read_text(encoding="utf-8"))
    for entry in evidence:
        check(ROOT / entry["artifact"], entry["committed_sha256"])
    print(f"PASS {len(evidence)} evidence and archived reference files", flush=True)


def reserve(parent, requested):
    parent.mkdir(parents=True, exist_ok=True)
    if requested is not None:
        if RUN_NAME.fullmatch(requested) is None:
            raise ValueError("Use a new run_NNN label.")
        chosen = parent / requested
        chosen.mkdir()
        return chosen
    number = 1
    while True:
        chosen = parent / f"run_{number:03d}"
        try:
            chosen.mkdir()
            return chosen
        except FileExistsError:
            number += 1


def mainline(run):
    verify()
    build = reserve(DERIVED / "build", run)
    if (RESULTS / "mainline" / build.name).exists():
        raise FileExistsError(f"The result run already exists: {build.name}")
    env = {**os.environ, "RNG_DERIVATION_DIR": str(build), "OPENBLAS_NUM_THREADS": "1",
           "OMP_NUM_THREADS": "1", "GIT_OPTIONAL_LOCKS": "0", "PYTHONUTF8": "1"}
    for stage in sorted(PIPELINE.glob("[0-9][0-9]_*.py")):
        subprocess.run([sys.executable, "-B", str(stage)], cwd=ROOT, env=env, check=True)
    engine = RESEARCH / "src/run_main.py"
    subprocess.run([sys.executable, "-B", str(engine), "--run", build.name, "--results-dir", str(RESULTS)],
                   cwd=ROOT, env=env, check=True)
    print(RESULTS / "mainline" / build.name)


def figures(run, from_run):
    if from_run and RUN_NAME.fullmatch(from_run) is None:
        raise ValueError("Use a run_NNN label for --from-run.")
    plot_data = RESULTS / "mainline" / from_run if from_run else RESEARCH / "results/mainline/run_007"
    out = reserve(DERIVED / "figures", run)
    os.environ.setdefault("MPLCONFIGDIR", str(DERIVED / "matplotlib_cache"))
    sys.path.insert(0, str(RESEARCH / "src"))
    import pandas as pd
    from make_mainline_figures import annual, forest

    annual(pd.read_csv(plot_data / "annual_deployments.csv"), out)
    forest(pd.read_csv(plot_data / "deployment_comparisons.csv"), out)
    print(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("mainline").add_argument("--run")
    figure_args = sub.add_parser("figures")
    figure_args.add_argument("--run")
    figure_args.add_argument("--from-run")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify()
        elif args.command == "mainline":
            mainline(args.run)
        else:
            figures(args.run, args.from_run)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()

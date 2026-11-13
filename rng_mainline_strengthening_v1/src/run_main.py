"""Build the evidence ledger and refit the fixed-frame deployment comparisons."""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import pandas as pd

from common import AUDIT30, AUDIT36, DISTANCES, HIFLD, LANDFILLS, LMOP, REPO, ROOT, SITE
from common import csv, read_book, sha, write_json
from compare import compare
from events import get_maps, ledger, sites_and_exclusions


def run_provenance(out, started, elapsed, inputs):
    def git(args):
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout.strip()
    code = sorted((REPO / "src").glob("*.py"))
    paths = dict.fromkeys([*inputs, *code])
    write_json({
        "actual_command": [sys.executable, *sys.argv],
        "started_utc": started.isoformat(), "wall_seconds": elapsed,
        "python": sys.version, "platform": platform.platform(),
        "packages": {k: importlib.metadata.version(k) for k in ["numpy", "pandas", "scipy", "openpyxl", "matplotlib"]},
        "git_head_at_run": git(["rev-parse", "HEAD"]) or None,
        "git_status_at_run": git(["status", "--short", "--untracked-files=normal"]),
        "openblas_num_threads": os.getenv("OPENBLAS_NUM_THREADS"),
        "seed": None, "random_split": None, "paid_services": False,
        "sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
        "output_dir": out.relative_to(REPO).as_posix(),
    }, out, "run_record")


def fresh_dir(argument, group):
    if not argument.startswith("run_") or not argument[4:].isdecimal():
        raise ValueError("use a new run_NNN directory")
    out = REPO / "results" / group / argument
    out.mkdir(parents=True, exist_ok=False)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    out = fresh_dir(args.run, "mainline")
    started = datetime.now(timezone.utc)
    tick = time.monotonic()
    book = read_book(LMOP)
    projects, sources, audits = ledger(book)
    eligible, all_sites = sites_and_exclusions(projects)
    sets = {name: set(d[SITE]) for name, d in audits.items()}
    assert projects["event_key"].is_unique
    assert sources["source_id"].is_unique
    assert set(s for value in projects["source_ids"] for s in value.split(";") if s).issubset(sources["source_id"])
    csv(projects, out, "event_ledger")
    csv(sources, out, "source_ledger")
    write_json({
        "audit30": len(sets["A30"]), "audit36": len(sets["A36"]),
        "overlap": len(sets["A30"] & sets["A36"]), "union": len(sets["A30"] | sets["A36"]),
        "registry_project_rows": len(projects), "landfill_ids_in_pipe_rows": int(projects[SITE].nunique()),
    }, out, "audit_scope")
    legacy_trace = REPO / "results/legacy/run_001/backfill/facility_trace.csv"
    compare(eligible, all_sites, projects, get_maps(projects), pd.read_csv(legacy_trace), out)
    run_provenance(out, started, time.monotonic() - tick,
                   [LMOP, LANDFILLS, DISTANCES, HIFLD, AUDIT30, AUDIT36, legacy_trace,
                    REPO / "evidence/targeted_adjudications.csv", REPO / "evidence/targeted_sources.csv"])
    print(f"{out}: {time.monotonic() - tick:.2f} seconds")


if __name__ == "__main__":
    main()

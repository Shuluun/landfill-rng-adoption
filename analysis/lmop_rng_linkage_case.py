"""Run the existing RNG pilot; inputs and decisions live in config/rng_pilot.json."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
# Re-export existing helpers so prior validation scripts keep working.
from rng.linkage import candidate_features, coordinates, haversine, retrieve, joint_tier
from rng.evidence import load, sha, source_rows
from rng.analysis import month_interval, windows
from rng.pipeline import run

IDENT = ROOT / 'reports/identity_preflight_2026-10-25_001'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=int, default=1479)
    parser.add_argument('--config', default='config/rng_pilot.json')
    parser.add_argument('--run-dir', help='New workspace-relative outputs path; omitted creates a unique UTC run id')
    args = parser.parse_args()
    run(ROOT, args.case, args.config, args.run_dir)


if __name__ == '__main__':
    main()

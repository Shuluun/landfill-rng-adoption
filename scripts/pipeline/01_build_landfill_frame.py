"""Invoke the original LMOP denominator and facility aggregation."""

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rng_paths import LANDFILLS, ROOT

if __name__ == "__main__":
    subprocess.run([sys.executable, "-B", str(ROOT / "analysis/denominator_gate_rng_20261104.py"),
                    "--output", str(LANDFILLS.parent)], check=True)

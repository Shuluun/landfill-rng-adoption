"""Invoke the original projected pipeline-distance stage."""

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rng_paths import RAW_DISTANCES, ROOT

if __name__ == "__main__":
    subprocess.run([sys.executable, "-B", str(ROOT / "analysis/compute_pipeline_distance_20261104.py"),
                    "--output", str(RAW_DISTANCES.parent)], check=True)

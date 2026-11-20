"""Invoke the spherical distance verification used by the locked model."""

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rng_paths import DISTANCES, ROOT

if __name__ == "__main__":
    subprocess.run([sys.executable, "-B", str(ROOT / "analysis/verify_distance_geodesic_20261106.py"),
                    "--output", str(DISTANCES.parent)], check=True)

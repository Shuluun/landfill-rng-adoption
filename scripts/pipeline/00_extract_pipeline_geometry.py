"""Extract the one frozen polyline member used by the locked model."""

from hashlib import sha256
from pathlib import Path
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rng_paths import HIFLD, HIFLD_ARCHIVE


def main():
    with ZipFile(HIFLD_ARCHIVE) as archive:
        geometry = archive.read(HIFLD.name)
    if sha256(geometry).hexdigest() != "de6c0c45fe33b4bc1ae033f13059d8514245e30604bf1c5d9df90466aeb92e6a":
        raise ValueError(f"Upstream data updated or invalid shapefile: {HIFLD_ARCHIVE}")
    HIFLD.parent.mkdir(parents=True, exist_ok=True)
    with HIFLD.open("xb") as file:
        file.write(geometry)


if __name__ == "__main__":
    main()

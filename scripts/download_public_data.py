"""Stage a public input only when its contents match the locked digest."""

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rng_paths import RAW, ROOT

MANIFEST = ROOT / "config/public_inputs.json"


def check(path, expected):
    with path.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"Upstream data updated (上游数据已更新): SHA-256 mismatch for {path}; "
                         f"expected {expected}; got {actual}")


def stage(record, data_dir, local_file=None):
    path = data_dir / record["filename"]
    if path.is_file():
        check(path, record["sha256"])
        return path
    url = record["url"]
    if local_file is None and not url:
        raise ValueError("The original download URL is unrecorded. Supply the frozen archive with --from-local.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".download-", dir=path.parent, delete=False) as temporary:
        intermediate = Path(temporary.name)
        try:
            source = local_file.open("rb") if local_file else urlopen(url, timeout=60)
            with source:
                shutil.copyfileobj(source, temporary)
            temporary.flush()
        except BaseException:
            temporary.close()
            intermediate.unlink(missing_ok=True)
            raise
    try:
        check(intermediate, record["sha256"])
        try:
            os.link(intermediate, path)
        except FileExistsError:
            check(path, record["sha256"])
    finally:
        intermediate.unlink(missing_ok=True)
    return path


def main():
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=records)
    parser.add_argument("--data-dir", type=Path, default=RAW)
    parser.add_argument("--from-local", type=Path)
    args = parser.parse_args()
    try:
        result = stage(records[args.source], args.data_dir, args.from_local)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(result)


if __name__ == "__main__":
    main()

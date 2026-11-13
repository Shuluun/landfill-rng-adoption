"""Execute the frozen model scripts with their output guard routed to this repository."""

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
SCRIPTS = {
    "backfill": "driver_consequence_backfill_20261109.py",
    "spatial": "spatial_conley_hac_20261110.py",
    "diagnostics": "driver_logit_diagnostics_20261110.py",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=SCRIPTS)
    parser.add_argument("--batch", default="run_001")
    args = parser.parse_args()
    if not args.batch.startswith("run_") or not args.batch[4:].isdecimal():
        parser.error("use a new run_NNN batch label")

    source = ROOT / "scripts" / SCRIPTS[args.model]
    original = source.read_text(encoding="utf-8")
    old_guard = "if not out.is_relative_to(ROOT / 'outputs'):"
    if original.count(old_guard) != 1:
        raise RuntimeError("Original output guard changed")
    adjusted = original.replace(old_guard, "if not out.is_relative_to(ISOLATED_OUTPUT_ROOT):")
    run_root = REPO / "results" / "legacy" / args.batch
    output = run_root / args.model
    if output.exists():
        raise FileExistsError(output)
    run_root.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, *sys.argv]
    started = datetime.now(timezone.utc).isoformat()
    tick = time.monotonic()
    sys.argv = [str(source), "--output", str(output)]
    with (run_root / f"{args.model}.log").open("x", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            namespace = {
                "__name__": "__main__",
                "__file__": str(source),
                "ISOLATED_OUTPUT_ROOT": run_root,
            }
            exec(compile(adjusted, str(source), "exec"), namespace)

    record = {
        "command": command,
        "started_utc": started,
        "wall_seconds": time.monotonic() - tick,
        "original_script": source.relative_to(ROOT).as_posix(),
        "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "interpreter": sys.executable,
        "only_source_change": "Route the output safety guard to the isolated repository.",
        "output": output.relative_to(REPO).as_posix(),
    }
    (output / "execution.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"{args.model}: {record['wall_seconds']:.2f} seconds")


if __name__ == "__main__":
    main()

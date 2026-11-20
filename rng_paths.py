"""Resolve frozen reproduction inputs, evidence, and derived output locations."""

import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent


def config():
    folder = ROOT / "config"
    with (folder / "paths.toml").open("rb") as stream:
        defaults = tomllib.load(stream)
    local = folder / "paths.local.toml"
    if local.is_file():
        with local.open("rb") as stream:
            for section, values in tomllib.load(stream).items():
                defaults.setdefault(section, {}).update(values)
    return defaults


SETTINGS = config()
RAW = (ROOT / os.environ.get("RNG_DATA_DIR", SETTINGS["paths"]["raw"])).resolve()
DERIVED = (ROOT / SETTINGS["paths"]["derived"]).resolve()
EVIDENCE = ROOT / "evidence"
REFERENCE = EVIDENCE / "reproduction_reference"
DERIVATION = Path(os.environ.get("RNG_DERIVATION_DIR", DERIVED / "mainline_inputs")).resolve()


def input_path(name):
    return (RAW / SETTINGS["inputs"][name]).resolve()


LMOP = input_path("lmop")
HIFLD_ARCHIVE = input_path("hifld_archive")
HISTORY = input_path("lmop_history")
EIA = input_path("eia_landmark")
HIFLD = DERIVATION / "hifld" / "natural-gas-interstate-and-intrastate-pipelines.shp"
LANDFILLS = DERIVATION / "denominator" / "landfill_level.csv"
RAW_DISTANCES = DERIVATION / "distances" / "nearest_pipeline_distance.csv"
DISTANCES = DERIVATION / "verified_distances" / "nearest_pipeline_distance_verified.csv"
AUDIT30 = EVIDENCE / "full_verification_30.csv"
AUDIT36 = EVIDENCE / "never_operational_full_36_final.csv"
HIST_SCREEN = REFERENCE / "SNAPSHOT_NEW_OPERATIONAL_CANDIDATES.csv"

PUBLIC = {"lmop": LMOP, "hifld_archive": HIFLD_ARCHIVE, "lmop_history": HISTORY, "eia_landmark": EIA}


def path_label(path):
    """Use a relative archive path or an input key in provenance tables."""
    p = Path(path).resolve()
    if p.is_relative_to(ROOT):
        return p.relative_to(ROOT).as_posix()
    for key, source in PUBLIC.items():
        if p == source:
            return f"configured-input:{key}"
    return p.as_posix()

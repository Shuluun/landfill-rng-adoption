"""Frozen inputs and shared definitions."""

import hashlib
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
LMOP = ROOT / "data/raw/2026-10-06_public_inputs/lmopdata.xlsx"
HISTORY = ROOT / "inputs/public/topic_selection_2026-10-20/root_sources/national_lmopdata_files_2001-2023.zip"
EIA = ROOT / "inputs/public/rng_adoption_review_2026-11-04/NaturalGas_InterIntrastate_Pipelines_US_EIA.zip"
HIFLD = ROOT / "inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.shp"
LANDFILLS = ROOT / "outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv"
DISTANCES = ROOT / "outputs/2026-11-06_rng_distance_geodesic_verify/run_001/nearest_pipeline_distance_verified.csv"
AUDIT30 = ROOT / "outputs/2026-11-09_rng_adoption_date_validation_sample/run_001/full_verification_30.csv"
AUDIT36 = ROOT / "outputs/2026-11-09_rng_never_operational_verify/run_003/never_operational_full_36_final.csv"
HIST_SCREEN = ROOT / "outputs/2026-11-04_rng_pipeline_signal_audit_002/SNAPSHOT_NEW_OPERATIONAL_CANDIDATES.csv"
EARLY = 1995
END = 2024
SITE = "Landfill ID"
OP = {"Operational", "Shutdown"}
BROAD = OP | {"Planned", "Construction"}
CONUS = set(
    "AL AZ AR CA CO CT DE FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
PERIODS = ((1995, 2004), (2005, 2009), (2010, 2014), (2015, 2019), (2020, 2021), (2022, 2024))


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_book(source):
    df = pd.read_excel(source, sheet_name="LMOP Database")
    df["excel_row"] = df.index + 2
    df["Project ID"] = df["Project ID"].astype("string").str.strip()
    df["parent_project_id"] = df["Project ID"].str.extract(r"^(\d+)-\d+$", expand=False)
    df["Project Start Date"] = pd.to_datetime(df["Project Start Date"], errors="coerce")
    df["Project Shutdown Date"] = pd.to_datetime(df["Project Shutdown Date"], errors="coerce")
    df["Current Project Status"] = df["Current Project Status"].astype("string").str.strip()
    return df


def pipeline_rows(df):
    return df[df["RNG Delivery Method"].eq("Pipeline Injection")].copy()


def csv(df, out, name):
    df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")


def write_json(obj, out, name):
    (out / f"{name}.json").write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )

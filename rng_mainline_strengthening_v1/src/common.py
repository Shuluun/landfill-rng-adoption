"""Frozen inputs and shared definitions."""

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rng_paths import (AUDIT30, AUDIT36, DISTANCES, EIA, HIFLD, HISTORY, HIST_SCREEN,
                       LANDFILLS, LMOP, REFERENCE, ROOT, path_label)

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

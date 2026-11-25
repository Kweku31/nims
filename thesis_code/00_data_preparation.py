"""
00_data_preparation.py

Generic raw-dataset preparation utilities -- works on ANY tabular
dataset, not just MIMIC-III/eICU. This is the ETL step that must run
before FIDDLE (01_fiddle_interface.py) can be invoked at all, since
raw clinical databases do not natively come in FIDDLE's expected
4-column format [ID, t, variable_name, variable_value].

This module provides THREE separate output pathways, corresponding to
the three-way comparison the thesis now runs (see 05_run_experiment.py):

    (1) raw_bytes_for_gzip()        -- serialize the raw table as-is,
                                        for the "raw file + gzip, no
                                        feature engineering at all"
                                        baseline.
    (2) minimal_feature_extraction() -- a lightweight, non-FIDDLE
                                        aggregation (mean/min/max/last
                                        per ID per variable), for the
                                        "PCA without FIDDLE" baseline.
    (3) to_fiddle_format()          -- reshape into FIDDLE's exact
                                        4-column input, for the full
                                        proposed method (FIDDLE + PCA).

Design goal: a user should be able to point this module at ANY raw
dataset that has *some* notion of (entity, time, measurement name,
measurement value) -- whether that's already long-format, or a wide
table with one row per entity and many measurement columns -- and get
all three pathways out.
"""

from __future__ import annotations
import gzip
import io
import pickle
import argparse
import os
from dataclasses import dataclass
from datetime import datetime




import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Step 1: get ANY raw dataset into a common long format
# (entity_id, t, variable_name, variable_value)
# --------------------------------------------------------------------------

def wide_to_long(df: pd.DataFrame, id_col: str, value_cols: list[str],
                  time_col: str | None = None) -> pd.DataFrame:
    """
    Convert a WIDE raw table (one row per entity, one column per
    measurement -- the most common shape for arbitrary tabular
    datasets, e.g. a CSV export) into the LONG format needed downstream.

    If `time_col` is None, all value_cols are treated as time-invariant
    (t = NaN), matching FIDDLE's convention for static variables.
    """
    keep = [id_col] + ([time_col] if time_col else []) + value_cols
    long_df = df[keep].melt(
        id_vars=[id_col] + ([time_col] if time_col else []),
        value_vars=value_cols,
        var_name="variable_name",
        value_name="variable_value",
    )
    long_df = long_df.rename(columns={id_col: "ID"})
    if time_col:
        long_df = long_df.rename(columns={time_col: "t"})
    else:
        long_df["t"] = np.nan
    long_df = long_df.dropna(subset=["variable_value"])
    return long_df[["ID", "t", "variable_name", "variable_value"]]


def compute_relative_time(df: pd.DataFrame, id_col: str, timestamp_col: str,
                           reference_times: pd.Series, unit: str = "h") -> pd.DataFrame:
    """
    Convert absolute timestamps into t = elapsed time since each
    entity's own reference point (e.g., admission time), matching
    FIDDLE's convention (t=0 at the fiducial marker).

    `reference_times` is indexed by id_col's values -> reference timestamp.
    """
    df = df.copy()
    ref = df[id_col].map(reference_times)
    delta = pd.to_datetime(df[timestamp_col]) - pd.to_datetime(ref)
    df["t"] = delta / pd.Timedelta(1, unit=unit)
    return df


# --------------------------------------------------------------------------
# Pathway 1: raw bytes, for the "no feature engineering, just gzip" baseline
# --------------------------------------------------------------------------

def raw_bytes_for_gzip(df: pd.DataFrame) -> bytes:
    """Serialize a raw (long- or wide-format) table exactly as it would
    be exported/sent with NO feature engineering applied at all."""
    buf = io.BytesIO()
    df.to_pickle(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Pathway 1.1: raw bytes, for the "no feature engineering, just gzip" baseline
# --------------------------------------------------------------------------

def raw_csv_for_gzip(df: pd.DataFrame, output_path: str) -> int:
    """
    Export the raw dataset as CSV and gzip-compress it.
    No feature engineering is performed.
    """
    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        df.to_csv(f, index=False)

    return os.path.getsize(output_path)

# --------------------------------------------------------------------------
# Pathway 2: minimal aggregation, for the "PCA without FIDDLE" baseline
# --------------------------------------------------------------------------

def minimal_feature_extraction(long_df: pd.DataFrame,
                                agg_funcs: tuple[str, ...] = ("mean", "min", "max", "last")
                                ) -> tuple[np.ndarray, list[str]]:
    """
    A lightweight, non-FIDDLE alternative: for each entity, aggregate
    each variable with a handful of simple summary statistics. This
    skips everything FIDDLE does beyond basic aggregation -- no
    frequent/non-frequent variable distinction, no presence masks, no
    delta-time, no quintile discretization.

    Returns a dense (N, d) numeric matrix and its feature names,
    ready to feed directly into PCA (03_pca_node_transfer.py) without
    ever running FIDDLE.
    """
    long_df = long_df.copy()
    long_df["variable_value"] = pd.to_numeric(long_df["variable_value"], errors="coerce")
    long_df = long_df.dropna(subset=["variable_value"])

    pieces = []
    names = []
    for func in agg_funcs:
        if func == "last":
            piece = (long_df.sort_values("t")
                             .groupby(["ID", "variable_name"])["variable_value"]
                             .last().unstack("variable_name"))
        else:
            piece = (long_df.groupby(["ID", "variable_name"])["variable_value"]
                             .agg(func).unstack("variable_name"))
        piece.columns = [f"{c}_{func}" for c in piece.columns]
        pieces.append(piece)
        names.extend(piece.columns.tolist())

    wide = pd.concat(pieces, axis=1).sort_index()
    wide = wide.fillna(wide.mean())  # simple mean-imputation; FIDDLE's carry-forward+mask is more principled
    return wide.to_numpy(), wide.columns.tolist()


# --------------------------------------------------------------------------
# Pathway 3: FIDDLE's exact expected input format
# --------------------------------------------------------------------------

def to_fiddle_format(long_df: pd.DataFrame, output_data_path: str,
                      output_population_path: str) -> None:
    """
    Write the long-format table and population file exactly as
    01_fiddle_interface.py / the real FIDDLE CLI expect. This is the
    final step of the raw-data-preparation pipeline before handing off
    to FIDDLE itself.
    """
    long_df = long_df[["ID", "t", "variable_name", "variable_value"]]
    long_df.to_csv(output_data_path, index=False)

    population = pd.DataFrame({"ID": sorted(long_df["ID"].unique())})
    population.to_csv(output_population_path, index=False)


# --------------------------------------------------------------------------
# Pathway 4: Load an external raw tabular dataset
# --------------------------------------------------------------------------

def load_raw_dataset(file_path: str) -> pd.DataFrame:
    """
    Load an external raw tabular dataset.

    Currently supports CSV files.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Dataset not found: {file_path}")

    if file_path.lower().endswith(".csv"):
        return pd.read_csv(file_path)

    raise ValueError(
        f"Unsupported file format: {file_path}. "
        "Currently only CSV files are supported."
    )


def get_value_columns(
    df: pd.DataFrame,
    id_col: str,
    time_col: str | None = None
) -> list[str]:

    excluded = {id_col}

    if time_col:
        excluded.add(time_col)

    return [
        col for col in df.columns
        if col not in excluded
    ]

# --------------------------------------------------------------------------
# Self-test with a synthetic, generic "raw dataset" (NOT MIMIC-specific)
# --------------------------------------------------------------------------

# if __name__ == "__main__":
#     rng = np.random.default_rng(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prepare a raw tabular dataset for gzip, PCA, and FIDDLE."
    )

    parser.add_argument(
        "input_file",
        nargs="?",
        help="Path to the raw CSV dataset."
    )

    parser.add_argument(
        "--id-col",
        default="patient_id",
        help="Column containing the entity/patient ID."
    )

    parser.add_argument(
        "--time-col",
        default=None,
        help="Column containing timestamps. Leave unset for time-invariant data."
    )

    parser.add_argument(
        "--value-cols",
        nargs="+",
        default=None,
        help="Columns to treat as clinical variables."
    )

    args = parser.parse_args()
    
    # ---------------------------------------------------------------
    # Load either an external dataset or generate synthetic data
    # ---------------------------------------------------------------

    if args.input_file:
        print(f"Reading external dataset: {args.input_file}")

        raw_wide = load_raw_dataset(args.input_file)

    else:
        print("No external dataset supplied.")
        print("Running synthetic self-test dataset.")

        rng = np.random.default_rng(0)

        n = 50

        raw_wide = pd.DataFrame({
            "patient_id": np.arange(n),
            "recorded_at": pd.date_range(
                "2024-01-01",
                periods=n,
                freq="h"
            ),
            "heart_rate": rng.normal(80, 10, n),
            "sbp": rng.normal(120, 15, n),
            "age": rng.integers(20, 90, n),
        })
        reference_times = pd.Series(pd.Timestamp("2024-01-01"), index=raw_wide["patient_id"])


    print("\nRaw dataset:")
    print(f"Rows: {len(raw_wide)}")
    print(f"Columns: {len(raw_wide.columns)}")
    print("\nColumns:")
    print(raw_wide.columns.tolist())

    if args.value_cols:
                value_cols = args.value_cols
    else:
        value_cols = get_value_columns(
            raw_wide,
            id_col=args.id_col,
            time_col=args.time_col
            )
    

    # Simulate an arbitrary WIDE raw dataset, e.g. an export from some
    # unknown clinical system: one row per patient, mixed timestamped
    # and static columns.
    # n = 50
    # raw_wide = pd.DataFrame({
    #     "patient_id": np.arange(n),
    #     "recorded_at": pd.date_range("2024-01-01", periods=n, freq="h"),
    #     "heart_rate": rng.normal(80, 10, n),
    #     "sbp": rng.normal(120, 15, n),
    #     "age": rng.integers(20, 90, n),
    # })
    # reference_times = pd.Series(pd.Timestamp("2024-01-01"), index=raw_wide["patient_id"])

    # # --- Pathway 1: raw bytes for gzip baseline ---
    # raw_bytes = raw_bytes_for_gzip(raw_wide)
    # print(f"Raw serialized size: {len(raw_bytes)} bytes")

    # # --- Pathway 1: raw data + gzip baseline ---
    # script_dir = os.path.dirname(os.path.abspath(__file__))

    # gzip_path = os.path.join(script_dir, "raw_dataset.pkl.gz")

    # compressed_size = raw_bytes_for_gzip(raw_wide, gzip_path)

    # print(f"\nRaw + gzip output:")
    # print(f"  File: {gzip_path}")
    # print(f"  Size: {compressed_size} bytes")


    # # Directory containing this script
    # script_dir = os.path.dirname(os.path.abspath(__file__))

    # # Create a unique timestamp for this experiment
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # # Create an output directory for this run
    # output_dir = os.path.join(script_dir, "output", timestamp)
    # os.makedirs(output_dir, exist_ok=True)

    # print(f"\nOutput directory: {output_dir}")

    # --- Pathway 1: raw CSV + gzip baseline ---
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Create a unique timestamp for this experiment
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create an output directory for this run
    output_dir = os.path.join(script_dir, "output", timestamp)
    os.makedirs(output_dir, exist_ok=True)

    gzip_path = os.path.join(output_dir, "raw_dataset.csv.gz")

    compressed_size = raw_csv_for_gzip(raw_wide, gzip_path)

    print("\nRaw + gzip output:")
    print(f"  File: {gzip_path}")
    print(f"  Size: {compressed_size} bytes")

    # --- Convert to long format (shared starting point for pathways 2 & 3) ---
    # long_df = wide_to_long(raw_wide, id_col="patient_id",
    #                         value_cols=["heart_rate", "sbp", "age"],
    #                         time_col="recorded_at")
    # long_df = compute_relative_time(long_df, id_col="ID", timestamp_col="t",
    #                                  reference_times=reference_times)
    # print(f"Long-format table: {long_df.shape}")
    # print(long_df.head(3).to_string(index=False))

    value_cols = get_value_columns(
    raw_wide,
    id_col=args.id_col,
    time_col=args.time_col
    )

    print("\nValue columns:")
    print(value_cols)

    long_df = wide_to_long(
        raw_wide,
        id_col=args.id_col,
        value_cols=value_cols,
        time_col=args.time_col
    )
    print(f"Long-format table: {long_df.shape}")
    print(long_df.head(3).to_string(index=False))


    # --- Pathway 2: minimal features, no FIDDLE ---
    X_minimal, names_minimal = minimal_feature_extraction(long_df)
    print(f"\nMinimal (no-FIDDLE) features: {X_minimal.shape}")
    print(f"Feature names: {names_minimal}")


    # # --- Pathway 3: FIDDLE-ready output files ---
    # import tempfile, os
    # with tempfile.TemporaryDirectory() as tmp:
    #     data_path = os.path.join(tmp, "formatted_data.csv")
    #     pop_path = os.path.join(tmp, "population.csv")
    #     to_fiddle_format(long_df, data_path, pop_path)
    #     print(f"\nWrote FIDDLE-ready files to: {tmp}")
    #     print(f"  {os.path.basename(data_path)}: {os.path.getsize(data_path)} bytes")
    #     print(f"  {os.path.basename(pop_path)}: {os.path.getsize(pop_path)} bytes")

    # print("\nOK: all three pathways (gzip-raw, minimal-features, FIDDLE-ready) produced.")

    # --- Pathway 3: FIDDLE-ready output files ---
    import os

    # Directory containing this Python script
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Create a unique timestamp for this experiment
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create an output directory for this run
    output_dir = os.path.join(script_dir, "output", timestamp)
    os.makedirs(output_dir, exist_ok=True)

    data_path = os.path.join(output_dir, "formatted_data.csv")
    pop_path = os.path.join(output_dir, "population.csv")

    to_fiddle_format(long_df, data_path, pop_path)

    print(f"\nWrote FIDDLE-ready files to: {output_dir}")
    print(f"  {os.path.basename(data_path)}: {os.path.getsize(data_path)} bytes")
    print(f"  {os.path.basename(pop_path)}: {os.path.getsize(pop_path)} bytes")

    print("\nOK: all three pathways (gzip-raw, minimal-features, FIDDLE-ready) produced.")
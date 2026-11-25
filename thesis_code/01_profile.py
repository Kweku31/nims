"""

01_profiling.py

Phase 1 -- Baseline Dataset Profiling

Thesis:

Efficient Dimensionality Reduction and Compression Strategies

for Large-Scale Clinical Data Transfer Between Hospitals and

University Data Centers.

Research Question 1:

Which variables or dimensions contribute most to dataset size

and transfer cost?

Scientific design

-----------------

1. The dataset is read from disk ONCE.

2. The resulting DataFrame remains in memory during Phase 1.

3. All profiling operations reuse the same DataFrame.

4. The original dataset is never modified.

5. Actual input-file size is measured directly from disk.

6. Computational time is recorded.

7. Potentially expensive operations have safeguards for very

   high-dimensional datasets.

Supported formats

-----------------

.csv

.csv.gz

.parquet

.xlsx

.xls

Examples

--------

python 01_profiling.py all_stays.csv

python 01_profiling.py raw_dataset.csv.gz

python 01_profiling.py input/mimic_data.csv \\

    --output-dir output/profiling/mimic

python 01_profiling.py input/mimic_data.csv \\

    --threshold 0.95 \\

    --top-n 20

"""

from __future__ import annotations

from datetime import datetime

import argparse

import hashlib

import json

import platform

import re

import sys

import time

from dataclasses import dataclass, field

from datetime import datetime, timezone

from pathlib import Path

import numpy as np

import pandas as pd

# ============================================================

# Data structures

# ============================================================

@dataclass

class ColumnProfile:

    name: str

    dtype: str

    n_missing: int

    pct_missing: float

    n_unique: int

    cardinality_ratio: float

    n_zero: int

    pct_zero: float

    estimated_bytes: int

    pct_dataset_memory: float

@dataclass

class DatasetProfile:

    source_file: str

    n_rows: int

    n_cols: int

    input_file_bytes: int

    total_bytes_in_memory: int

    load_time_seconds: float

    profiling_time_seconds: float

    columns: list[ColumnProfile] = field(

        default_factory=list

    )

    duplicate_column_groups: list[list[str]] = field(

        default_factory=list

    )

    redundant_pairs: list[tuple[str, str, float]] = field(

        default_factory=list

    )

# ============================================================

# Utility functions

# ============================================================

def human_size(size_bytes: int) -> str:

    """Convert bytes into a human-readable representation."""

    size = float(size_bytes)

    for unit in ["B", "KB", "MB", "GB", "TB"]:

        if size < 1024:

            return f"{size:.2f} {unit}"

        size /= 1024

    return f"{size:.2f} PB"

def percentage(part: int | float, whole: int | float) -> float:

    """Safely calculate a percentage."""

    if whole == 0:

        return 0.0

    return float(part / whole * 100.0)

# ============================================================

# Dataset loading

# ============================================================

def load_dataset(

    file_path: str

) -> tuple[pd.DataFrame, float, int]:

    """

    Load the dataset exactly once.

    Returns

    -------

    df

        DataFrame kept in memory and reused throughout Phase 1.

    load_time

        Wall-clock time required to read the dataset.

    file_size

        Actual number of bytes occupied by the source file on disk.

    """

    path = Path(file_path)

    if not path.exists():

        raise FileNotFoundError(

            f"Dataset not found: {path.resolve()}"

        )

    if not path.is_file():

        raise ValueError(

            f"Input path is not a file: {path.resolve()}"

        )

    file_size = path.stat().st_size

    filename = path.name.lower()

    print("=" * 72)

    print("PHASE 1 -- BASELINE DATASET PROFILING")

    print("=" * 72)

    print(f"\nDataset:")

    print(f"  {path.resolve()}")

    print(

        f"\nSource file size:"

        f" {human_size(file_size)}"

        f" ({file_size:,} bytes)"

    )

    print("\nReading dataset into memory once...")

    start = time.perf_counter()

    if filename.endswith(".csv") or filename.endswith(".csv.gz"):

        df = pd.read_csv(

            path,

            low_memory=False

        )

    elif filename.endswith(".parquet"):

        df = pd.read_parquet(path)

    elif (

        filename.endswith(".xlsx")

        or filename.endswith(".xls")

    ):

        df = pd.read_excel(path)

    else:

        raise ValueError(

            "Unsupported file format.\n"

            "Supported formats: "

            ".csv, .csv.gz, .parquet, .xlsx, .xls"

        )

    load_time = time.perf_counter() - start

    print("\nDataset loaded successfully.")

    print(f"Rows       : {len(df):,}")

    print(f"Columns    : {len(df.columns):,}")

    print(f"Load time  : {load_time:.4f} seconds")

    return df, load_time, file_size

# ============================================================

# Column profiling

# ============================================================

def profile_column(

    df: pd.DataFrame,

    column: str,

    total_memory: int

) -> ColumnProfile:

    """

    Calculate descriptive characteristics for one column.

    The original column is never modified.

    """

    series = df[column]

    n_rows = len(series)

    # --------------------------------------------------------

    # Missingness

    # --------------------------------------------------------

    n_missing = int(

        series.isna().sum()

    )

    pct_missing = percentage(

        n_missing,

        n_rows

    )

    # --------------------------------------------------------

    # Cardinality

    # --------------------------------------------------------

    n_unique = int(

        series.nunique(

            dropna=True

        )

    )

    cardinality_ratio = (

        n_unique / n_rows

        if n_rows

        else 0.0

    )

    # --------------------------------------------------------

    # Zero sparsity

    # --------------------------------------------------------

    if pd.api.types.is_numeric_dtype(series):

        n_zero = int(

            series.eq(0).sum()

        )

        pct_zero = percentage(

            n_zero,

            n_rows

        )

    else:

        n_zero = 0

        pct_zero = 0.0

    # --------------------------------------------------------

    # Memory footprint

    # --------------------------------------------------------

    estimated_bytes = int(

        series.memory_usage(

            index=False,

            deep=True

        )

    )

    pct_dataset_memory = percentage(

        estimated_bytes,

        total_memory

    )

    return ColumnProfile(

        name=str(column),

        dtype=str(series.dtype),

        n_missing=n_missing,

        pct_missing=pct_missing,

        n_unique=n_unique,

        cardinality_ratio=cardinality_ratio,

        n_zero=n_zero,

        pct_zero=pct_zero,

        estimated_bytes=estimated_bytes,

        pct_dataset_memory=pct_dataset_memory,

    )

# ============================================================

# Exact duplicate column detection

# ============================================================

def column_fingerprint(

    series: pd.Series

) -> str:

    """

    Produce a hash fingerprint for a column.

    Why?

    ----

    Comparing every column against every other column directly

    can become expensive.

    Instead:

        column

          |

          v

        hash

          |

          v

    compare hashes first

    Only columns sharing the same hash are subsequently verified

    using Series.equals().

    Hashing is used only as a candidate-generation mechanism.

    Equality is always verified afterwards.

    """

    hashed_values = pd.util.hash_pandas_object(

        series,

        index=False

    ).values

    digest = hashlib.sha256(

        hashed_values.tobytes()

    ).hexdigest()

    return digest

def find_duplicate_columns(

    df: pd.DataFrame

) -> list[list[str]]:

    """

    Detect exact duplicate columns.

    Hashes reduce unnecessary pairwise comparisons, while

    Series.equals() provides final verification.

    """

    print("\nChecking exact duplicate columns...")

    hash_groups: dict[str, list[str]] = {}

    for column in df.columns:

        fingerprint = column_fingerprint(

            df[column]

        )

        hash_groups.setdefault(

            fingerprint,

            []

        ).append(column)

    duplicate_groups = []

    for candidates in hash_groups.values():

        if len(candidates) < 2:

            continue

        verified_groups: list[list[str]] = []

        for candidate in candidates:

            matched = False

            for group in verified_groups:

                representative = group[0]

                if df[candidate].equals(

                    df[representative]

                ):

                    group.append(candidate)

                    matched = True

                    break

            if not matched:

                verified_groups.append(

                    [candidate]

                )

        for group in verified_groups:

            if len(group) > 1:

                duplicate_groups.append(group)

    return duplicate_groups

# ============================================================

# Correlation analysis

# ============================================================

def find_redundant_pairs(

    df: pd.DataFrame,

    threshold: float = 0.95,

    max_correlation_columns: int = 2000

) -> tuple[list[tuple[str, str, float]], bool]:

    """

    Find highly correlated numeric variables.

    Pearson correlation is used for numerical features.

    Scientific/computational consideration

    ---------------------------------------

    A full correlation matrix for p variables requires O(p^2)

    matrix storage.

    For example:

        p = 100       ->       10,000 correlations

        p = 1,000     ->    1,000,000 correlations

        p = 10,000    ->  100,000,000 correlations

    Therefore, an explicit safeguard is used.

    If the number of numeric variables exceeds

    max_correlation_columns, the full correlation calculation

    is skipped rather than silently sampling variables.

    This is important scientifically: automatic sampling could

    cause genuinely redundant variables to be missed.

    Returns

    -------

    pairs

        Highly correlated column pairs.

    skipped

        True if correlation analysis was skipped.

    """

    numeric_df = df.select_dtypes(

        include=[np.number]

    )

    n_numeric = numeric_df.shape[1]

    print(

        f"\nNumeric variables available for correlation: "

        f"{n_numeric:,}"

    )

    if n_numeric < 2:

        return [], False

    if n_numeric > max_correlation_columns:

        print(

            "\nWARNING:"

            "\nFull correlation analysis was skipped."

            f"\nNumeric columns = {n_numeric:,}"

            f"\nConfigured maximum = "

            f"{max_correlation_columns:,}"

        )

        print(

            "\nReason: constructing a full correlation matrix "

            "would require quadratic O(p^2) storage."

        )

        return [], True

    print(

        "Calculating Pearson correlation matrix..."

    )

    corr = numeric_df.corr(

        method="pearson"

    ).abs()

    columns = corr.columns.to_list()

    pairs = []

    # Only inspect the upper triangular portion.

    # There is no reason to examine both (A,B) and (B,A).

    for i in range(len(columns)):

        for j in range(i + 1, len(columns)):

            value = corr.iat[i, j]

            if (

                pd.notna(value)

                and value >= threshold

            ):

                pairs.append(

                    (

                        str(columns[i]),

                        str(columns[j]),

                        float(value)

                    )

                )

    pairs.sort(

        key=lambda item: item[2],

        reverse=True

    )

    return pairs, False

# ============================================================

# Additional correlation profiling support

# ============================================================

def detect_identifier_columns(

    df: pd.DataFrame

) -> list[str]:

    """

    Automatically detect common identifier naming patterns.

    Examples detected include:

        ID

        SUBJECT_ID

        HADM_ID

        ICUSTAY_ID

        patient-id

        patient id

        PatientID

        PatientId

    Identifier columns are NOT removed from the dataset.

    They are excluded only from the additional Phase 1

    correlation profiling output.

    """

    identifiers = []

    for column in df.columns:

        original = str(column).strip()

        normalized = original.lower()

        standard_pattern = bool(

            re.search(

                r"(^id$|[_\-\s]id$)",

                normalized

            )

        )

        compact_pattern = bool(

            re.search(

                r"(?:ID|Id)$",

                original

            )

        )

        if standard_pattern or compact_pattern:

            identifiers.append(column)

    return identifiers

def resolve_identifier_columns(

    df: pd.DataFrame,

    manual_identifier_columns: list[str] | None = None

) -> tuple[list[str], list[str], list[str]]:

    """

    Combine automatically detected and explicitly supplied IDs.

    Manual identifiers are useful when a dataset uses names such as

    PATIENT_NUMBER, VISIT_CODE, CASE_NUMBER, or another convention

    that does not end in ID.

    Returns

    -------

    automatic_identifiers

        Identifier columns detected from naming patterns.

    manual_identifiers

        Explicit identifiers supplied by the user and found in the

        dataset.

    combined_identifiers

        Union of automatic and manual identifiers in dataset order.

    """

    if manual_identifier_columns is None:

        manual_identifier_columns = []

    automatic_identifiers = detect_identifier_columns(df)

    missing_manual_identifiers = [

        column

        for column in manual_identifier_columns

        if column not in df.columns

    ]

    if missing_manual_identifiers:

        raise ValueError(

            "Explicit identifier column(s) not found in dataset: "

            + ", ".join(missing_manual_identifiers)

        )

    manual_identifiers = [

        column

        for column in manual_identifier_columns

        if column in df.columns

    ]

    combined_set = (

        set(automatic_identifiers)

        | set(manual_identifiers)

    )

    combined_identifiers = [

        column

        for column in df.columns

        if column in combined_set

    ]

    return (

        automatic_identifiers,

        manual_identifiers,

        combined_identifiers

    )

def calculate_full_correlation_profile(

    df: pd.DataFrame,

    threshold: float = 0.95,

    max_correlation_columns: int = 2000,

    manual_identifier_columns: list[str] | None = None

) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:

    """

    Produce the additional Phase 1 correlation outputs.

    This function does not replace or modify the original

    find_redundant_pairs() function. It adds a complete correlation

    profile that:

    1. lists every numeric variable and its role;

    2. excludes identifier columns from correlation calculations;

    3. stores every unique pairwise Pearson correlation;

    4. separately stores pairs satisfying |r| >= threshold;

    5. does not remove or alter any variable in the dataset.

    """

    (

        automatic_identifiers,

        manual_identifiers,

        identifier_columns

    ) = resolve_identifier_columns(

        df,

        manual_identifier_columns

    )

    numeric_columns = (

        df.select_dtypes(

            include=[np.number]

        ).columns.to_list()

    )

    identifier_set = set(identifier_columns)

    correlation_columns = [

        column

        for column in numeric_columns

        if column not in identifier_set

    ]

    numeric_records = []

    for column in numeric_columns:

        series = df[column]

        is_identifier = column in identifier_set

        if column in automatic_identifiers and column in manual_identifiers:

            identifier_source = "automatic+manual"

        elif column in automatic_identifiers:

            identifier_source = "automatic"

        elif column in manual_identifiers:

            identifier_source = "manual"

        else:

            identifier_source = "not_identifier"

        numeric_records.append({

            "variable": column,

            "dtype": str(series.dtype),

            "n_unique": int(series.nunique(dropna=True)),

            "n_missing": int(series.isna().sum()),

            "pct_missing": float(series.isna().mean() * 100.0),

            "is_identifier": is_identifier,

            "identifier_source": identifier_source,

            "included_in_correlation": not is_identifier,

            "reason": (

                "Excluded from correlation: identifier"

                if is_identifier

                else "Included: numeric analytical variable"

            )

        })

    numeric_profile = pd.DataFrame(

        numeric_records,

        columns=[

            "variable",

            "dtype",

            "n_unique",

            "n_missing",

            "pct_missing",

            "is_identifier",

            "identifier_source",

            "included_in_correlation",

            "reason"

        ]

    )

    print("\n" + "-" * 72)

    print("ADDITIONAL COMPLETE CORRELATION PROFILE")

    print("-" * 72)

    print(

        f"Numeric variables found       : {len(numeric_columns):,}"

    )

    print(

        f"Identifiers excluded          : {len(identifier_columns):,}"

    )

    for column in identifier_columns:

        source = (

            "manual"

            if column in manual_identifiers

            and column not in automatic_identifiers

            else "automatic"

        )

        print(

            f"  - {column} ({source})"

        )

    print(

        f"Variables used for correlation: {len(correlation_columns):,}"

    )

    for column in correlation_columns:

        print(

            f"  - {column}"

        )

    if len(correlation_columns) > max_correlation_columns:

        print(

            "\nWARNING:\n"

            "Complete correlation output was skipped because the "

            "number of eligible numeric variables exceeded the "

            "configured safeguard."

        )

        empty_all = pd.DataFrame(

            columns=[

                "column_a",

                "column_b",

                "pearson_r",

                "absolute_pearson_correlation",

                "pairwise_n",

                "above_threshold",

                "status"

            ]

        )

        empty_high = empty_all.copy()

        metadata = {

            "automatic_identifier_columns": automatic_identifiers,

            "manual_identifier_columns": manual_identifiers,

            "combined_identifier_columns": identifier_columns,

            "numeric_columns": numeric_columns,

            "correlation_columns": correlation_columns,

            "correlation_threshold": threshold,

            "correlation_skipped": True,

            "correlation_pairs": 0

        }

        return (

            numeric_profile,

            empty_all,

            empty_high,

            metadata

        )

    pair_records = []

    for i in range(len(correlation_columns)):

        for j in range(i + 1, len(correlation_columns)):

            column_a = correlation_columns[i]

            column_b = correlation_columns[j]

            pair = df[[column_a, column_b]].dropna()

            pairwise_n = len(pair)

            if pairwise_n < 3:

                pearson_r = np.nan

                absolute_r = np.nan

                status = "insufficient observations"

                above_threshold = False

            elif (

                pair[column_a].nunique(dropna=True) <= 1

                or pair[column_b].nunique(dropna=True) <= 1

            ):

                pearson_r = np.nan

                absolute_r = np.nan

                status = "constant variable"

                above_threshold = False

            else:

                pearson_r = pair[column_a].corr(

                    pair[column_b],

                    method="pearson"

                )

                if pd.isna(pearson_r):

                    absolute_r = np.nan

                    status = "undefined correlation"

                    above_threshold = False

                else:

                    pearson_r = float(pearson_r)

                    absolute_r = abs(pearson_r)

                    status = "calculated"

                    above_threshold = absolute_r >= threshold

            pair_records.append({

                "column_a": column_a,

                "column_b": column_b,

                "pearson_r": pearson_r,

                "absolute_pearson_correlation": absolute_r,

                "pairwise_n": pairwise_n,

                "above_threshold": above_threshold,

                "status": status

            })

    all_pairs = pd.DataFrame(

        pair_records,

        columns=[

            "column_a",

            "column_b",

            "pearson_r",

            "absolute_pearson_correlation",

            "pairwise_n",

            "above_threshold",

            "status"

        ]

    )

    if not all_pairs.empty:

        all_pairs = all_pairs.sort_values(

            by="absolute_pearson_correlation",

            ascending=False,

            na_position="last"

        ).reset_index(drop=True)

    high_redundancy = all_pairs[

        all_pairs["above_threshold"] == True

    ].copy()

    print(

        f"Unique correlation pairs       : {len(all_pairs):,}"

    )

    print(

        f"Redundancy threshold           : |r| >= {threshold}"

    )

    print(

        f"Pairs meeting threshold        : {len(high_redundancy):,}"

    )

    if not all_pairs.empty:

        print("\nAll pairwise Pearson correlations:")

        print(

            all_pairs[

                [

                    "column_a",

                    "column_b",

                    "pearson_r",

                    "absolute_pearson_correlation",

                    "pairwise_n"

                ]

            ].to_string(

                index=False,

                float_format=lambda value: f"{value:.6f}"

            )

        )

    metadata = {

        "automatic_identifier_columns": automatic_identifiers,

        "manual_identifier_columns": manual_identifiers,

        "combined_identifier_columns": identifier_columns,

        "numeric_columns": numeric_columns,

        "correlation_columns": correlation_columns,

        "correlation_threshold": threshold,

        "correlation_skipped": False,

        "correlation_pairs": len(all_pairs),

        "high_redundancy_pairs": len(high_redundancy),

        "missing_value_strategy": "pairwise-complete observations",

        "variables_removed": False

    }

    return (

        numeric_profile,

        all_pairs,

        high_redundancy,

        metadata

    )

def save_additional_correlation_results(

    output_dir: str | Path,

    numeric_profile: pd.DataFrame,

    all_pairs: pd.DataFrame,

    high_redundancy: pd.DataFrame,

    correlation_metadata: dict

) -> None:

    """

    Save the additional complete correlation profiling outputs.

    These files are additions to the original Phase 1 outputs.

    Existing output files are left unchanged.

    """

    output_path = Path(output_dir)

    numeric_profile.to_csv(

        output_path / "numeric_variable_profile.csv",

        index=False

    )

    all_pairs.to_csv(

        output_path / "correlation_all_pairs.csv",

        index=False

    )

    high_redundancy.to_csv(

        output_path / "correlation_high_redundancy.csv",

        index=False

    )

    with open(

        output_path / "correlation_metadata.json",

        "w",

        encoding="utf-8"

    ) as file:

        json.dump(

            correlation_metadata,

            file,

            indent=4

        )

# ============================================================

# Complete dataset profiling

# ============================================================

def profile_dataset(

    df: pd.DataFrame,

    source_file: str,

    input_file_bytes: int,

    load_time_seconds: float,

    redundancy_threshold: float = 0.95,

    max_correlation_columns: int = 2000

) -> tuple[DatasetProfile, bool]:

    """

    Profile the DataFrame already held in memory.

    IMPORTANT:

    This function does NOT read the dataset again.

    """

    print("\n" + "=" * 72)

    print("PROFILING DATASET IN MEMORY")

    print("=" * 72)

    start = time.perf_counter()

    # --------------------------------------------------------

    # Memory footprint

    # --------------------------------------------------------

    total_memory = int(

        df.memory_usage(

            index=True,

            deep=True

        ).sum()

    )

    print(

        f"\nDataFrame memory footprint:"

        f" {human_size(total_memory)}"

        f" ({total_memory:,} bytes)"

    )

    # --------------------------------------------------------

    # Individual column profiles

    # --------------------------------------------------------

    print(

        f"\nProfiling {len(df.columns):,} columns..."

    )

    columns = []

    for column in df.columns:

        result = profile_column(

            df,

            column,

            total_memory

        )

        columns.append(result)

    # --------------------------------------------------------

    # Duplicate columns

    # --------------------------------------------------------

    duplicate_groups = find_duplicate_columns(

        df

    )

    # --------------------------------------------------------

    # Correlation

    # --------------------------------------------------------

    redundant_pairs, correlation_skipped = (

        find_redundant_pairs(

            df,

            threshold=redundancy_threshold,

            max_correlation_columns=max_correlation_columns

        )

    )

    profiling_time = (

        time.perf_counter() - start

    )

    profile = DatasetProfile(

        source_file=str(

            Path(source_file).resolve()

        ),

        n_rows=len(df),

        n_cols=len(df.columns),

        input_file_bytes=input_file_bytes,

        total_bytes_in_memory=total_memory,

        load_time_seconds=load_time_seconds,

        profiling_time_seconds=profiling_time,

        columns=columns,

        duplicate_column_groups=duplicate_groups,

        redundant_pairs=redundant_pairs,

    )

    return profile, correlation_skipped

# ============================================================

# Convert column profiles to DataFrame

# ============================================================

def column_profiles_to_dataframe(

    profile: DatasetProfile

) -> pd.DataFrame:

    records = []

    for column in profile.columns:

        records.append({

            "column":

                column.name,

            "dtype":

                column.dtype,

            "n_missing":

                column.n_missing,

            "pct_missing":

                column.pct_missing,

            "n_unique":

                column.n_unique,

            "cardinality_ratio":

                column.cardinality_ratio,

            "n_zero":

                column.n_zero,

            "pct_zero":

                column.pct_zero,

            "estimated_bytes":

                column.estimated_bytes,

            "pct_dataset_memory":

                column.pct_dataset_memory,

        })

    return pd.DataFrame(

        records

    ).sort_values(

        "estimated_bytes",

        ascending=False

    )

# ============================================================

# Console report

# ============================================================

def print_profile_report(

    profile: DatasetProfile,

    correlation_skipped: bool,

    threshold: float,

    top_n: int = 10

) -> None:

    print("\n")

    print("=" * 72)

    print("BASELINE PROFILE RESULTS")

    print("=" * 72)

    print(

        f"Rows                 : "

        f"{profile.n_rows:,}"

    )

    print(

        f"Columns              : "

        f"{profile.n_cols:,}"

    )

    print(

        f"Input file size      : "

        f"{human_size(profile.input_file_bytes)}"

    )

    print(

        f"DataFrame memory     : "

        f"{human_size(profile.total_bytes_in_memory)}"

    )

    print(

        f"Dataset load time    : "

        f"{profile.load_time_seconds:.4f} seconds"

    )

    print(

        f"Profiling time       : "

        f"{profile.profiling_time_seconds:.4f} seconds"

    )

    print(

        f"Total Phase 1 time   : "

        f"{profile.load_time_seconds + profile.profiling_time_seconds:.4f} "

        f"seconds"

    )

    # --------------------------------------------------------

    # Highest storage variables

    # --------------------------------------------------------

    print("\n" + "-" * 72)

    print(

        f"TOP {top_n} VARIABLES BY IN-MEMORY STORAGE"

    )

    print("-" * 72)

    columns_df = column_profiles_to_dataframe(

        profile

    )

    display_columns = [

    "column",

    "dtype",

    "n_missing",

    "pct_missing",

    "n_unique",

    "cardinality_ratio",

    "n_zero",

    "pct_zero",

    "estimated_bytes",

    "pct_dataset_memory",

    ]

    print(

        columns_df[

            display_columns

        ].head(top_n).to_string(

            index=False

        )

    )

    # --------------------------------------------------------

    # Duplicate columns

    # --------------------------------------------------------

    print("\n" + "-" * 72)

    if profile.duplicate_column_groups:

        print(

            "EXACT DUPLICATE COLUMN GROUPS"

        )

        for group in profile.duplicate_column_groups:

            print(f"  {group}")

    else:

        print(

            "No exact duplicate columns found."

        )

    # --------------------------------------------------------

    # Correlations

    # --------------------------------------------------------

    print("\n" + "-" * 72)

    if correlation_skipped:

        print(

            "Full correlation analysis was skipped "

            "because the dataset exceeded the configured "

            "dimensionality safeguard."

        )

    elif profile.redundant_pairs:

        print(

            f"HIGHLY CORRELATED NUMERIC VARIABLES "

            f"(|r| >= {threshold})"

        )

        for a, b, correlation in (

            profile.redundant_pairs[:top_n]

        ):

            print(

                f"  {a} <-> {b}: "

                f"|r| = {correlation:.6f}"

            )

    else:

        print(

            f"No numeric variable pairs with "

            f"|r| >= {threshold}."

        )

# ============================================================

# Run directory and timestamp

# ============================================================

def create_run_directory(

    dataset_path: str,

    base_output_dir: str

) -> tuple[Path, str]:

    """

    Create a unique directory for one profiling experiment.

    Example:

        output/profiling/

            all_stays_20260923_101845/

    """

    dataset = Path(dataset_path)

    dataset_name = dataset.name

    if dataset_name.lower().endswith(".csv.gz"):

        dataset_name = dataset_name[:-7]

    else:

        dataset_name = dataset.stem

    now = datetime.now(timezone.utc)

    folder_timestamp = now.strftime(

        "%Y%m%d_%H%M%S"

    )

    # ISO 8601 timestamp for metadata.

    run_timestamp = now.isoformat()

    run_name = (

        f"{dataset_name}_{folder_timestamp}"

    )

    run_directory = (

        Path(base_output_dir) /

        run_name

    )

    run_directory.mkdir(

        parents=True,

        exist_ok=False

    )

    return run_directory, run_timestamp

# ============================================================

# SHA-256 checksum

# ============================================================

def calculate_file_sha256(

    file_path: str,

    chunk_size: int = 1024 * 1024

) -> str:

    """

    Calculate the SHA-256 checksum of the source dataset.

    The file is read in small binary chunks, so calculating the

    checksum does not create another full copy of the dataset in RAM.

    The checksum provides dataset provenance:

    if even one byte of the source file changes, its SHA-256 value

    will normally change.

    """

    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:

        while True:

            chunk = file.read(chunk_size)

            if not chunk:

                break

            sha256.update(chunk)

    return sha256.hexdigest()

# ============================================================

# Save results

# ============================================================

def save_profile_results(

    profile: DatasetProfile,

    output_dir: str,

    correlation_skipped: bool,

    threshold: float,

    run_timestamp: str,

    dataset_sha256: str,

    command_line_args: argparse.Namespace

) -> None:

    output_path = Path(

        output_dir

    )

    output_path.mkdir(

        parents=True,

        exist_ok=True

    )

    # --------------------------------------------------------

    # 1. Column profile

    # --------------------------------------------------------

    column_file = (

        output_path /

        "column_profile.csv"

    )

    column_profiles_to_dataframe(

        profile

    ).to_csv(

        column_file,

        index=False

    )

    # --------------------------------------------------------

    # 2. Correlated variables

    # --------------------------------------------------------

    correlation_file = (

        output_path /

        "redundant_pairs.csv"

    )

    pd.DataFrame(

        profile.redundant_pairs,

        columns=[

            "column_a",

            "column_b",

            "absolute_pearson_correlation"

        ]

    ).to_csv(

        correlation_file,

        index=False

    )

    # --------------------------------------------------------

    # 3. Duplicate columns

    # --------------------------------------------------------

    duplicate_file = (

        output_path /

        "duplicate_columns.csv"

    )

    duplicate_records = []

    for group_id, group in enumerate(

        profile.duplicate_column_groups,

        start=1

    ):

        for column in group:

            duplicate_records.append({

                "group_id": group_id,

                "column": column

            })

    pd.DataFrame(

        duplicate_records,

        columns=[

            "group_id",

            "column"

        ]

    ).to_csv(

        duplicate_file,

        index=False

    )

    # --------------------------------------------------------

    # 4. Dataset summary

    # --------------------------------------------------------

    summary_file = (

        output_path /

        "dataset_summary.csv"

    )

    total_time = (

        profile.load_time_seconds

        + profile.profiling_time_seconds

    )

    summary = pd.DataFrame([{

        "source_file":

            profile.source_file,

        "n_rows":

            profile.n_rows,

        "n_columns":

            profile.n_cols,

        "input_file_bytes":

            profile.input_file_bytes,

        "dataframe_memory_bytes":

            profile.total_bytes_in_memory,

        "load_time_seconds":

            profile.load_time_seconds,

        "profiling_time_seconds":

            profile.profiling_time_seconds,

        "total_phase1_seconds":

            total_time,

        "duplicate_groups":

            len(

                profile.duplicate_column_groups

            ),

        "highly_correlated_pairs":

            len(

                profile.redundant_pairs

            ),

        "correlation_threshold":

            threshold,

        "correlation_skipped":

            correlation_skipped,

    }])

    summary.to_csv(

        summary_file,

        index=False

    )

    # ========================================================

    # Reproducibility metadata

    # ========================================================

    metadata_file = (

        output_path /

        "profile_metadata.json"

    )

    total_time = (

        profile.load_time_seconds

        + profile.profiling_time_seconds

    )

    metadata = {

        # ----------------------------------------------------

        # Experiment identification

        # ----------------------------------------------------

        "experiment": {

            "phase":

                "Phase 1 - Baseline Profiling",

            "script":

                Path(__file__).name,

            "run_timestamp_utc":

                run_timestamp,

        },

        # ----------------------------------------------------

        # Source dataset provenance

        # ----------------------------------------------------

        "dataset": {

            "filename":

                Path(

                    profile.source_file

                ).name,

            "absolute_path":

                profile.source_file,

            "sha256":

                dataset_sha256,

            "rows":

                profile.n_rows,

            "columns":

                profile.n_cols,

            "input_file_bytes":

                profile.input_file_bytes,

            "dataframe_memory_bytes":

                profile.total_bytes_in_memory,

        },

        # ----------------------------------------------------

        # Profiling configuration

        # ----------------------------------------------------

        "parameters": {

            "correlation_threshold":

                threshold,

            "max_correlation_columns":

                command_line_args.max_correlation_columns,

            "top_n":

                command_line_args.top_n,

            "base_output_directory":

                command_line_args.output_dir,

        },

        # ----------------------------------------------------

        # Actual command-line arguments

        # ----------------------------------------------------

        "command_line": {

            "argv":

                sys.argv,

            "parsed_arguments":

                vars(

                    command_line_args

                ),

        },

        # ----------------------------------------------------

        # Software environment

        # ----------------------------------------------------

        "environment": {

            "python_version":

                platform.python_version(),

            "python_implementation":

                platform.python_implementation(),

            "pandas_version":

                pd.__version__,

            "numpy_version":

                np.__version__,

            "operating_system":

                platform.system(),

            "operating_system_release":

                platform.release(),

            "machine":

                platform.machine(),

        },

        # ----------------------------------------------------

        # Computational timing

        # ----------------------------------------------------

        "timing": {

            "dataset_load_seconds":

                profile.load_time_seconds,

            "profiling_seconds":

                profile.profiling_time_seconds,

            "total_phase1_seconds":

                total_time,

        },

        # ----------------------------------------------------

        # Redundancy analysis

        # ----------------------------------------------------

        "redundancy_analysis": {

            "duplicate_groups":

                len(

                    profile.duplicate_column_groups

                ),

            "correlation_threshold":

                threshold,

            "highly_correlated_pairs":

                len(

                    profile.redundant_pairs

                ),

            "correlation_skipped":

                correlation_skipped,

        }

    }

    with open(

        metadata_file,

        "w",

        encoding="utf-8"

    ) as file:

        json.dump(

            metadata,

            file,

            indent=4

        )

# ============================================================

# Command-line arguments

# ============================================================

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(

        description=(

            "Phase 1 baseline profiling for "

            "large-scale anonymized clinical datasets."

        )

    )

    parser.add_argument(

        "dataset",

        help=(

            "Path to the anonymized dataset "

            "(.csv, .csv.gz, .parquet, .xlsx, .xls)"

        )

    )

    parser.add_argument(

        "--output-dir",

        default="output/profiling",

        help=(

            "Directory for profiling results. "

            "Default: output/profiling"

        )

    )

    parser.add_argument(

        "--threshold",

        type=float,

        default=0.95,

        help=(

            "Absolute Pearson correlation threshold "

            "for identifying potentially redundant "

            "numeric variables. Default: 0.95"

        )

    )

    parser.add_argument(

        "--max-correlation-columns",

        type=int,

        default=2000,

        help=(

            "Maximum number of numeric variables for "

            "full correlation-matrix computation. "

            "Default: 2000"

        )

    )

    parser.add_argument(

        "--top-n",

        type=int,

        default=10,

        help=(

            "Number of highest-storage variables and "

            "correlated pairs displayed. Default: 10"

        )

    )

    parser.add_argument(

        "--identifier-columns",

        nargs="*",

        default=[],

        help=(

            "Additional identifier columns that do not follow "

            "the usual ID naming pattern. These columns are retained "

            "in the dataset but excluded from the additional complete "

            "correlation analysis."

        )

    )

    args = parser.parse_args()

    if not 0 <= args.threshold <= 1:

        parser.error(

            "--threshold must be between 0 and 1."

        )

    if args.max_correlation_columns < 2:

        parser.error(

            "--max-correlation-columns must be >= 2."

        )

    if args.top_n < 1:

        parser.error(

            "--top-n must be >= 1."

        )

    return args

# ============================================================

# Main program

# ============================================================

def main() -> None:

    args = parse_arguments()

    # ========================================================

    # STEP 1

    # Read dataset ONCE into the working DataFrame.

    # ========================================================

    df, load_time, file_size = load_dataset(

        args.dataset

    )

    # ========================================================

    # STEP 2

    # Profile the in-memory DataFrame.

    # ========================================================

    profile, correlation_skipped = profile_dataset(

        df=df,

        source_file=args.dataset,

        input_file_bytes=file_size,

        load_time_seconds=load_time,

        redundancy_threshold=args.threshold,

        max_correlation_columns=(

            args.max_correlation_columns

        )

    )

    # ========================================================

    # ADDITIONAL CORRELATION PROFILE

    #

    # This supplements the original correlation analysis without

    # changing the existing Phase 1 profiling logic.

    # ========================================================

    (

        numeric_profile,

        all_correlation_pairs,

        high_redundancy_pairs,

        correlation_metadata

    ) = calculate_full_correlation_profile(

        df=df,

        threshold=args.threshold,

        max_correlation_columns=(

            args.max_correlation_columns

        ),

        manual_identifier_columns=(

            args.identifier_columns

        )

    )

    # ========================================================

    # STEP 3

    # Display profiling results.

    # ========================================================

    print_profile_report(

        profile=profile,

        correlation_skipped=correlation_skipped,

        threshold=args.threshold,

        top_n=args.top_n

    )

    # ========================================================

    # STEP 4

    # Create experiment directory.

    # ========================================================

    run_directory, run_timestamp = (

        create_run_directory(

            dataset_path=args.dataset,

            base_output_dir=args.output_dir

        )

    )

    # ========================================================

    # STEP 5

    # Calculate source dataset checksum.

    #

    # This performs a sequential binary read for provenance,

    # but does NOT create another DataFrame or full RAM copy.

    # ========================================================

    print("\nCalculating source dataset SHA-256...")

    checksum_start = time.perf_counter()

    dataset_sha256 = calculate_file_sha256(

        args.dataset

    )

    checksum_time = (

        time.perf_counter()

        - checksum_start

    )

    print(

        f"SHA-256       : {dataset_sha256}"

    )

    print(

        f"Checksum time : {checksum_time:.4f} seconds"

    )

    # ========================================================

    # STEP 6

    # Save experimental results and provenance metadata.

    # ========================================================

    save_profile_results(

        profile=profile,

        output_dir=str(

            run_directory

        ),

        correlation_skipped=correlation_skipped,

        threshold=args.threshold,

        run_timestamp=run_timestamp,

        dataset_sha256=dataset_sha256,

        command_line_args=args

    )

    # ========================================================

    # ADDITIONAL CORRELATION OUTPUT FILES

    # ========================================================

    save_additional_correlation_results(

        output_dir=run_directory,

        numeric_profile=numeric_profile,

        all_pairs=all_correlation_pairs,

        high_redundancy=high_redundancy_pairs,

        correlation_metadata=correlation_metadata

    )

    print("\n" + "=" * 72)

    print("PHASE 1 COMPLETED SUCCESSFULLY")

    print("=" * 72)

    print(

        f"\nResults saved to:\n"

        f"  {run_directory.resolve()}"

    )

if __name__ == "__main__":

    main()
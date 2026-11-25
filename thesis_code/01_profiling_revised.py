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
8. Correlation profiling is descriptive in Phase 1:
   no variables are removed.
9. Numeric identifier columns are excluded from correlation
   because their numeric values do not represent quantitative
   clinical measurements.
10. Pearson correlation profiles linear relationships.
11. Spearman rank correlation profiles monotonic relationships.
12. Distance correlation provides an exploratory check for more
    general nonlinear dependence.
13. Automatic variable roles are audited alongside manual overrides.
14. Completely empty and globally constant numeric variables do not
    participate in correlation; they remain in the complete profile.
15. A minimum complete-pair count is required for nonlinear *flags*,
    but not for reporting the descriptive dependence coefficients.
16. All source data, including metadata and outcomes, are retained
    in the baseline transfer dataset.

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

python 01_profiling.py input/mimic_data.csv \
    --output-dir output/profiling/mimic

python 01_profiling.py input/mimic_data.csv \
    --threshold 0.95 \
    --top-n 20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
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

    # Every eligible numeric-variable pair.
    correlation_pairs: list[dict] = field(
        default_factory=list
    )

    # Only pairs satisfying |r| >= threshold.
    redundant_pairs: list[tuple[str, str, float]] = field(
        default_factory=list
    )

    # Identifier information.
    identifier_columns: list[str] = field(
        default_factory=list
    )

    # Numeric variables actually used for correlation.
    correlation_variables: list[str] = field(
        default_factory=list
    )

    variable_roles: pd.DataFrame = field(default_factory=pd.DataFrame)
    correlation_scope: str = "all"
    min_pairwise_n: int = 100


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


def percentage(
    part: int | float,
    whole: int | float
) -> float:
    """Safely calculate a percentage."""

    if whole == 0:
        return 0.0

    return float(
        part / whole * 100.0
    )


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

    print("\nDataset:")
    print(f"  {path.resolve()}")

    print(
        f"\nSource file size:"
        f" {human_size(file_size)}"
        f" ({file_size:,} bytes)"
    )

    print(
        "\nReading dataset into memory once..."
    )

    start = time.perf_counter()

    if (
        filename.endswith(".csv")
        or filename.endswith(".csv.gz")
        or filename.endswith(".csv.zst")
    ):

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

    load_time = (
        time.perf_counter()
        - start
    )

    print(
        "\nDataset loaded successfully."
    )

    print(
        f"Rows       : {len(df):,}"
    )

    print(
        f"Columns    : {len(df.columns):,}"
    )

    print(
        f"Load time  : {load_time:.4f} seconds"
    )

    return (
        df,
        load_time,
        file_size
    )


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

    if pd.api.types.is_numeric_dtype(
        series
    ):

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
# Identifier detection
# ============================================================

def detect_identifier_columns(
    df: pd.DataFrame
) -> list[str]:
    """
    Detect likely identifier variables using column-name patterns.

    Examples detected:
        ID
        id
        SUBJECT_ID
        subject_id
        HADM_ID
        ICUSTAY_ID
        patient-id
        patient id
        PatientID
        PatientId

    Important
    ---------
    Identifier detection does NOT remove columns from the dataset.

    It only prevents numeric identifiers from participating in
    statistical correlation analysis.
    """

    identifiers = []

    for column in df.columns:

        original = str(column).strip()
        normalized = original.lower()

        # Standard naming patterns:
        #
        # ID
        # id
        # subject_id
        # patient-id
        # patient id
        standard_pattern = bool(
            re.search(
                r"(^id$|[_\-\s]id$)",
                normalized
            )
        )

        # Compact/camel-case patterns:
        #
        # PatientID
        # PatientId
        # EncounterID
        compact_pattern = bool(
            re.search(
                r"(?:ID|Id)$",
                original
            )
        )

        if (
            standard_pattern
            or compact_pattern
        ):
            identifiers.append(column)

    return identifiers

def combine_identifier_columns(
    df: pd.DataFrame,
    manual_identifiers: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """
    Combine automatically detected identifiers with identifiers
    explicitly supplied by the user.

    Returns
    -------
    automatic_identifiers
        IDs detected from column-name conventions.

    manual_identifiers_present
        User-specified IDs that exist in the dataset.

    combined_identifiers
        Union of automatic and manual identifiers, preserving
        the original dataset column order.
    """

    automatic_identifiers = (
        detect_identifier_columns(df)
    )

    manual_identifiers_present = [
        column
        for column in manual_identifiers
        if column in df.columns
    ]

    combined_set = (
        set(automatic_identifiers)
        | set(manual_identifiers_present)
    )

    combined_identifiers = [
        column
        for column in df.columns
        if column in combined_set
    ]

    return (
        automatic_identifiers,
        manual_identifiers_present,
        combined_identifiers
    )

# ============================================================
# Variable roles -- descriptive, never removes source columns
# ============================================================

def classify_variable_roles(
    df: pd.DataFrame,
    identifier_columns: list[str],
    time_columns: list[str] | None = None,
    label_columns: list[str] | None = None,
    categorical_columns: list[str] | None = None,
    manual_identifier_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Audit automatically inferred roles and explicit, precedence-taking overrides.

    Roles describe column semantics; correlation eligibility additionally
    requires usable numerical values. No source values are changed or deleted.
    """
    automatic_identifiers = set(detect_identifier_columns(df))
    identifiers = set(identifier_columns)
    manual_ids = set(manual_identifier_columns or [])
    manual_times = set(time_columns or [])
    manual_labels = set(label_columns or [])
    manual_categories = set(categorical_columns or [])
    rows = []

    for col in df.columns:
        series = df[col]
        name = str(col).strip()
        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
        words = re.sub(r"[^a-zA-Z0-9]+", "_", snake).lower().strip("_")
        tokens = set(words.split("_"))
        numeric = bool(pd.api.types.is_numeric_dtype(series))
        distinct = int(series.nunique(dropna=True))
        non_missing = int(series.notna().sum())

        # Base classification is always inferred, independently of overrides.
        if col in automatic_identifiers:
            automatic_role, automatic_method = "identifier", "identifier name pattern"
        elif pd.api.types.is_datetime64_any_dtype(series):
            automatic_role, automatic_method = "time_candidate", "datetime dtype"
        elif (
            words in {"time", "timestamp", "datetime", "date", "iculos",
                      "hospadmtime", "charttime", "storetime", "admittime",
                      "dischtime", "intime", "outtime", "dob", "dod", "deathtime"}
            or bool(tokens.intersection({"timestamp", "datetime", "date", "time"}))
            or words.endswith(("_time", "_date", "_timestamp", "_datetime"))
            or words.startswith(("time_", "date_"))
        ):
            automatic_role, automatic_method = "time_candidate", "column-name pattern"
        elif (
            words in {"label", "target", "outcome", "sepsislabel"}
            or words.endswith(("_label", "_outcome", "_target"))
            or bool(tokens.intersection({"label", "outcome", "target"}))
        ):
            automatic_role, automatic_method = "outcome_candidate", "column-name pattern"
        elif distinct == 0:
            automatic_role, automatic_method = "empty", "no observed values"
        elif distinct == 1:
            automatic_role, automatic_method = "constant", "one observed value"
        elif pd.api.types.is_bool_dtype(series) or (numeric and distinct == 2):
            automatic_role, automatic_method = "binary", "two observed values"
        elif numeric:
            automatic_role, automatic_method = "numeric", "numeric dtype"
        else:
            automatic_role, automatic_method = "categorical", "non-numeric dtype"

        if col in manual_ids:
            manual_role = "identifier"
        elif col in manual_times:
            manual_role = "time"
        elif col in manual_labels:
            manual_role = "outcome"
        elif col in manual_categories:
            manual_role = "categorical"
        else:
            manual_role = None

        # The previous API's identifier_columns remains supported. Automatic
        # ID names are already handled above, and any manual role wins.
        effective_role = manual_role or (
            "identifier" if col in identifiers else automatic_role
        )
        detection_method = (
            "manual override" if manual_role is not None
            else automatic_method
        )
        if non_missing == 0:
            value_status = "empty"
        elif distinct <= 1:
            value_status = "constant"
        elif non_missing < 3:
            value_status = "too_few_observations"
        else:
            value_status = "variable"

        # Do not use any globally empty/constant variable in either mode,
        # even if its semantic role is time, identifier or outcome.
        usable = numeric and value_status == "variable"
        general = bool(usable and effective_role != "identifier")
        continuous = bool(usable and effective_role == "numeric")
        if not numeric:
            exclusion_reason = "non-numeric data"
        elif value_status != "variable":
            exclusion_reason = value_status
        elif effective_role == "identifier":
            exclusion_reason = "identifier"
        elif effective_role != "numeric":
            exclusion_reason = f"role excluded in continuous mode: {effective_role}"
        else:
            exclusion_reason = "eligible"

        rows.append({
            "variable": col,
            "automatic_role": automatic_role,
            "automatic_detection_method": automatic_method,
            "manual_override_role": manual_role or "",
            "role": effective_role,
            "detection_method": detection_method,
            "data_type": str(series.dtype),
            "n_unique": distinct,
            "n_observed": non_missing,
            "n_missing": int(series.isna().sum()),
            "pct_missing": float(series.isna().mean() * 100),
            "value_status": value_status,
            "included_in_general_correlation": general,
            "included_in_continuous_correlation": continuous,
            "exclusion_reason": exclusion_reason,
            "retained_in_original_transfer": True,
        })
    return pd.DataFrame(rows)


# ============================================================
# Numeric-variable profile
# ============================================================

# ============================================================
# Numeric-variable profile
# ============================================================

def numeric_variable_profile(
    df: pd.DataFrame,
    identifier_columns: list[str],
    variable_roles: pd.DataFrame | None = None,
    correlation_scope: str = "all",
) -> pd.DataFrame:
    """
    Describe all numeric variables and indicate whether each
    participates in correlation analysis.
    """

    numeric_columns = (
        df
        .select_dtypes(
            include=[np.number]
        )
        .columns
        .tolist()
    )

    identifier_set = set(
        identifier_columns
    )

    role_map = (
        variable_roles.set_index("variable").to_dict("index")
        if variable_roles is not None and not variable_roles.empty else {}
    )
    selection_key = (
        "included_in_continuous_correlation"
        if correlation_scope == "continuous"
        else "included_in_general_correlation"
    )
    records = []

    for column in numeric_columns:

        series = df[column]

        is_identifier = (
            column in identifier_set
        )

        records.append({
            "variable":
                column,

            "data_type":
                str(series.dtype),

            "n_unique":
                int(
                    series.nunique(
                        dropna=True
                    )
                ),

            "n_missing":
                int(
                    series.isna().sum()
                ),

            "pct_missing":
                float(
                    series.isna().mean()
                    * 100.0
                ),

            "identifier":
                is_identifier,

            "role": role_map.get(column, {}).get("role", "unclassified"),
            "value_status": role_map.get(column, {}).get("value_status", "unknown"),
            "included_in_correlation": (
                bool(role_map[column][selection_key])
                if column in role_map else not is_identifier
            ),
            "reason": (
                "Included under correlation scope: " + correlation_scope
                if (bool(role_map[column][selection_key]) if column in role_map else not is_identifier)
                else ("Excluded: " + str(role_map.get(column, {}).get("exclusion_reason", "not eligible")))
            ),
        })

    return pd.DataFrame(
        records,
        columns=[
            "variable",
            "data_type",
            "n_unique",
            "n_missing",
            "pct_missing",
            "identifier",
            "role",
            "value_status",
            "included_in_correlation",
            "reason",
        ]
    )


# ============================================================
# Exact duplicate column detection
# ============================================================

def column_fingerprint(
    series: pd.Series
) -> str:
    """
    Produce a hash fingerprint for a column.

    Comparing every column against every other column directly
    can become expensive.

    Hashes are therefore used to generate candidate duplicate
    groups. Exact equality is subsequently verified using
    Series.equals().

    Hashing is NOT treated as final proof of equality.
    """

    hashed_values = (
        pd.util
        .hash_pandas_object(
            series,
            index=False
        )
        .values
    )

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

    print(
        "\nChecking exact duplicate columns..."
    )

    hash_groups: dict[
        str,
        list[str]
    ] = {}

    for column in df.columns:

        fingerprint = (
            column_fingerprint(
                df[column]
            )
        )

        hash_groups.setdefault(
            fingerprint,
            []
        ).append(column)

    duplicate_groups = []

    for candidates in (
        hash_groups.values()
    ):

        if len(candidates) < 2:
            continue

        verified_groups: list[
            list[str]
        ] = []

        for candidate in candidates:

            matched = False

            for group in verified_groups:

                representative = (
                    group[0]
                )

                if df[candidate].equals(
                    df[representative]
                ):

                    group.append(
                        candidate
                    )

                    matched = True

                    break

            if not matched:

                verified_groups.append(
                    [candidate]
                )

        for group in verified_groups:

            if len(group) > 1:
                duplicate_groups.append(
                    group
                )

    return duplicate_groups


# ============================================================
# Correlation analysis
# ============================================================

def distance_correlation_1d(
    x: np.ndarray,
    y: np.ndarray
) -> float:
    """
    Calculate sample distance correlation for two one-dimensional
    numeric variables.

    Distance correlation can detect general dependence, including
    relationships that are nonlinear and non-monotonic.

    The standard sample calculation requires O(n^2) pairwise
    distance storage, so the caller controls the number of rows
    supplied to this function.
    """

    x = np.asarray(x, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64).reshape(-1)

    if len(x) != len(y):
        raise ValueError(
            "x and y must contain the same number of observations."
        )

    if len(x) < 3:
        return np.nan

    a = np.abs(
        x[:, None] - x[None, :]
    )

    b = np.abs(
        y[:, None] - y[None, :]
    )

    A = (
        a
        - a.mean(axis=1, keepdims=True)
        - a.mean(axis=0, keepdims=True)
        + a.mean()
    )

    B = (
        b
        - b.mean(axis=1, keepdims=True)
        - b.mean(axis=0, keepdims=True)
        + b.mean()
    )

    distance_covariance_squared = float(
        np.mean(A * B)
    )

    distance_variance_x_squared = float(
        np.mean(A * A)
    )

    distance_variance_y_squared = float(
        np.mean(B * B)
    )

    denominator = np.sqrt(
        distance_variance_x_squared
        * distance_variance_y_squared
    )

    if denominator <= 0:
        return np.nan

    distance_correlation_squared = (
        distance_covariance_squared
        / denominator
    )

    distance_correlation_squared = max(
        0.0,
        distance_correlation_squared
    )

    return float(
        np.sqrt(
            distance_correlation_squared
        )
    )


def calculate_correlation_pairs(
    df: pd.DataFrame,
    threshold: float = 0.95,
    max_correlation_columns: int = 2000,
    manual_identifier_columns: list[str] | None = None,
    nonlinear_gap: float = 0.20,
    distance_correlation_max_rows: int = 2000,
    distance_random_seed: int = 42,
    time_columns: list[str] | None = None,
    label_columns: list[str] | None = None,
    categorical_columns: list[str] | None = None,
    correlation_scope: str = "all",
    min_pairwise_n: int = 100,
) -> tuple[
    list[dict],
    list[tuple[str, str, float]],
    list[str],
    list[str],
    bool
]:
    """
    Profile dependence between eligible numeric variables.

    Phase 1 purpose
    ---------------
    Dependence analysis is DESCRIPTIVE at this stage.

    The objectives are to:

    1. describe relationships among numeric analytical variables;
    2. identify possible linear redundancy;
    3. check whether important monotonic or nonlinear relationships
       may be missed by Pearson correlation alone;
    4. provide evidence for later feature-selection decisions.

    No variables are removed here.

    Measures
    --------
    Pearson correlation
        Measures linear association.

    Spearman rank correlation
        Measures monotonic association and can detect monotonic
        nonlinear relationships.

    Distance correlation
        Provides an exploratory measure of more general dependence,
        including non-monotonic nonlinear relationships.

    Identifier handling
    -------------------
    Numeric identifier columns are automatically detected using
    naming patterns and excluded from dependence analysis.

    Additional identifiers can be supplied explicitly through
    --identifier-columns.

    Missing values
    --------------
    Pearson and Spearman are calculated using all pairwise-complete
    observations for each pair.

    Distance-correlation safeguard
    ------------------------------
    Exact distance correlation requires O(n^2) pairwise-distance
    storage. If a variable pair contains more than
    distance_correlation_max_rows complete observations, a
    deterministic random sample of that size is used only for the
    distance-correlation calculation.

    The output explicitly records:
        distance_pairwise_n
        distance_sampled

    Pearson and Spearman are never subsampled.

    Nonlinear review flag
    ---------------------
    A pair is flagged for exploratory nonlinear review when either
    absolute Spearman correlation or distance correlation exceeds
    absolute Pearson correlation by at least nonlinear_gap.

    This is a screening flag only. It is NOT an automatic variable
    removal rule.

    Computational safeguard
    -----------------------
    The number of unique variable pairs grows approximately as O(p^2).

    If eligible numeric variables exceed max_correlation_columns,
    dependence profiling is skipped rather than silently sampling
    variables.

    Returns
    -------
    all_pairs
        Every unique eligible numeric-variable pair and all dependence
        measures.

    redundant_pairs
        Pairs satisfying the original Pearson rule |r| >= threshold.

    identifier_columns
        Combined automatic and manually specified identifiers.

    correlation_variables
        Numeric variables actually analyzed.

    skipped
        Whether dependence analysis was skipped.
    """

    numeric_columns = (
        df
        .select_dtypes(
            include=[np.number]
        )
        .columns
        .tolist()
    )

    if manual_identifier_columns is None:
        manual_identifier_columns = []

    (
        automatic_identifiers,
        manual_identifiers,
        identifier_columns
    ) = combine_identifier_columns(
        df,
        manual_identifier_columns
    )

    identifier_set = set(
        identifier_columns
    )

    roles = classify_variable_roles(
        df, identifier_columns, time_columns, label_columns,
        categorical_columns, manual_identifier_columns,
    )
    # Effective roles account for manual overrides, not just name patterns.
    identifier_columns = roles.loc[
        roles["role"] == "identifier", "variable"
    ].tolist()
    identifier_set = set(identifier_columns)
    eligibility_key = (
        "included_in_continuous_correlation"
        if correlation_scope == "continuous"
        else "included_in_general_correlation"
    )
    eligible = set(roles.loc[roles[eligibility_key], "variable"])
    correlation_variables = [
        column for column in numeric_columns if column in eligible
    ]

    print(
        "\nCorrelation and dependence profiling"
    )

    print("-" * 72)

    print(
        f"Numeric variables found       : "
        f"{len(numeric_columns):,}"
    )

    print(
        f"Automatic identifiers found   : "
        f"{len(automatic_identifiers):,}"
    )

    print(
        f"Manual identifiers found      : "
        f"{len(manual_identifiers):,}"
    )

    numeric_ids_excluded = [c for c in identifier_columns if c in numeric_columns]
    print(f"Identifiers detected (all types): {len(identifier_columns):,}")
    print(f"Numeric identifiers excluded  : {len(numeric_ids_excluded):,}")
    print(f"Non-numeric identifiers       : {len(identifier_columns)-len(numeric_ids_excluded):,}")

    if identifier_columns:
        for column in identifier_columns:
            print(
                f"  - {column}"
            )

    print(
        f"Variables used for analysis   : "
        f"{len(correlation_variables):,}"
    )

    if correlation_variables:
        for column in correlation_variables:
            print(
                f"  - {column}"
            )

    # Fully empty and constant columns stay in the column-profile file,
    # but are excluded from costly and uninformative correlations.
    skipped_numeric = roles.loc[
        roles["data_type"].map(lambda dtype: pd.api.types.is_numeric_dtype(
            pd.api.types.pandas_dtype(dtype)
        )) & ~roles[eligibility_key],
        ["variable", "role", "value_status", "exclusion_reason"],
    ]
    if not skipped_numeric.empty:
        print("\nNumeric variables omitted from this correlation scope:")
        for item in skipped_numeric.itertuples(index=False):
            print(f"  - {item.variable}: {item.exclusion_reason}")

    n_numeric = len(
        correlation_variables
    )

    if n_numeric < 2:
        print(
            "\nFewer than two eligible numeric "
            "variables are available."
        )

        return (
            [],
            [],
            identifier_columns,
            correlation_variables,
            False
        )

    if (
        n_numeric
        > max_correlation_columns
    ):
        print(
            "\nWARNING:"
            "\nFull dependence profiling was skipped."
            f"\nEligible numeric columns = "
            f"{n_numeric:,}"
            f"\nConfigured maximum = "
            f"{max_correlation_columns:,}"
        )

        print(
            "\nReason: the number of pairwise "
            "relationships grows quadratically."
        )

        return (
            [],
            [],
            identifier_columns,
            correlation_variables,
            True
        )

    expected_pairs = (
        n_numeric
        * (n_numeric - 1)
        // 2
    )

    print(
        f"Unique variable pairs         : "
        f"{expected_pairs:,}"
    )

    print(
        f"Pearson redundancy threshold  : "
        f"|r| >= {threshold:.2f}"
    )

    print(
        f"Nonlinear review gap          : "
        f"{nonlinear_gap:.2f}"
    )
    print(f"Minimum pairs for nonlinear flag: {min_pairwise_n:,}")

    print(
        f"Distance-correlation row cap  : "
        f"{distance_correlation_max_rows:,}"
    )

    print(
        "\nCalculating Pearson, Spearman, "
        "and distance dependence measures..."
    )

    all_pairs = []
    redundant_pairs = []

    for (
        variable_a,
        variable_b
    ) in combinations(
        correlation_variables,
        2
    ):

        pair = (
            df[
                [
                    variable_a,
                    variable_b
                ]
            ]
            .dropna()
        )

        pairwise_n = len(pair)

        if pairwise_n < 3:
            all_pairs.append({
                "column_a": variable_a,
                "column_b": variable_b,
                "pearson_r": np.nan,
                "absolute_pearson_correlation": np.nan,
                "spearman_rho": np.nan,
                "absolute_spearman_correlation": np.nan,
                "distance_correlation": np.nan,
                "pairwise_n": pairwise_n,
                "distance_pairwise_n": 0,
                "distance_sampled": False,
                "above_threshold": False,
                "spearman_minus_pearson_abs": np.nan,
                "distance_minus_pearson_abs": np.nan,
                "nonlinear_review": False,
                "nonlinear_gap_met": False,
                "nonlinear_review_status": "not evaluated",
                "status": "insufficient observations",
            })
            continue

        if (
            pair[variable_a]
            .nunique(dropna=True)
            <= 1
            or
            pair[variable_b]
            .nunique(dropna=True)
            <= 1
        ):
            all_pairs.append({
                "column_a": variable_a,
                "column_b": variable_b,
                "pearson_r": np.nan,
                "absolute_pearson_correlation": np.nan,
                "spearman_rho": np.nan,
                "absolute_spearman_correlation": np.nan,
                "distance_correlation": np.nan,
                "pairwise_n": pairwise_n,
                "distance_pairwise_n": 0,
                "distance_sampled": False,
                "above_threshold": False,
                "spearman_minus_pearson_abs": np.nan,
                "distance_minus_pearson_abs": np.nan,
                "nonlinear_review": False,
                "nonlinear_gap_met": False,
                "nonlinear_review_status": "not evaluated",
                "status": "constant variable",
            })
            continue

        pearson_r = (
            pair[variable_a]
            .corr(
                pair[variable_b],
                method="pearson"
            )
        )

        rank_a = (
            pair[variable_a]
            .rank(
                method="average"
            )
        )

        rank_b = (
            pair[variable_b]
            .rank(
                method="average"
            )
        )

        spearman_rho = (
            rank_a.corr(
                rank_b,
                method="pearson"
            )
        )

        if (
            pd.isna(pearson_r)
            or pd.isna(spearman_rho)
        ):
            all_pairs.append({
                "column_a": variable_a,
                "column_b": variable_b,
                "pearson_r": np.nan,
                "absolute_pearson_correlation": np.nan,
                "spearman_rho": np.nan,
                "absolute_spearman_correlation": np.nan,
                "distance_correlation": np.nan,
                "pairwise_n": pairwise_n,
                "distance_pairwise_n": 0,
                "distance_sampled": False,
                "above_threshold": False,
                "spearman_minus_pearson_abs": np.nan,
                "distance_minus_pearson_abs": np.nan,
                "nonlinear_review": False,
                "nonlinear_gap_met": False,
                "nonlinear_review_status": "not evaluated",
                "status": "undefined correlation",
            })
            continue

        pearson_r = float(
            pearson_r
        )

        spearman_rho = float(
            spearman_rho
        )

        abs_pearson = abs(
            pearson_r
        )

        abs_spearman = abs(
            spearman_rho
        )

        if (
            pairwise_n
            > distance_correlation_max_rows
        ):
            distance_pair = pair.sample(
                n=distance_correlation_max_rows,
                random_state=distance_random_seed
            )

            distance_sampled = True

        else:
            distance_pair = pair
            distance_sampled = False

        distance_pairwise_n = len(
            distance_pair
        )

        distance_corr = (
            distance_correlation_1d(
                distance_pair[
                    variable_a
                ].to_numpy(),

                distance_pair[
                    variable_b
                ].to_numpy()
            )
        )

        distance_corr = (
            float(distance_corr)
            if pd.notna(distance_corr)
            else np.nan
        )

        above_threshold = (
            abs_pearson
            >= threshold
        )

        spearman_gap = (
            abs_spearman
            - abs_pearson
        )

        distance_gap = (
            distance_corr
            - abs_pearson
            if pd.notna(distance_corr)
            else np.nan
        )

        nonlinear_gap_met = bool(
            spearman_gap >= nonlinear_gap
            or (pd.notna(distance_gap) and distance_gap >= nonlinear_gap)
        )
        nonlinear_review = bool(
            nonlinear_gap_met and pairwise_n >= min_pairwise_n
        )
        nonlinear_review_status = (
            "flagged" if nonlinear_review
            else "insufficient pairwise observations"
            if nonlinear_gap_met else "below gap threshold"
        )

        all_pairs.append({
            "column_a": variable_a,
            "column_b": variable_b,
            "pearson_r": pearson_r,
            "absolute_pearson_correlation": abs_pearson,
            "spearman_rho": spearman_rho,
            "absolute_spearman_correlation": abs_spearman,
            "distance_correlation": distance_corr,
            "pairwise_n": pairwise_n,
            "distance_pairwise_n": distance_pairwise_n,
            "distance_sampled": distance_sampled,
            "above_threshold": above_threshold,
            "spearman_minus_pearson_abs": spearman_gap,
            "distance_minus_pearson_abs": distance_gap,
            "nonlinear_review": nonlinear_review,
            "nonlinear_gap_met": nonlinear_gap_met,
            "nonlinear_review_status": nonlinear_review_status,
            "status": "calculated",
        })

        if above_threshold:
            redundant_pairs.append(
                (
                    str(variable_a),
                    str(variable_b),
                    abs_pearson
                )
            )

    all_pairs.sort(
        key=lambda item: (
            -1.0
            if pd.isna(
                item[
                    "absolute_pearson_correlation"
                ]
            )
            else item[
                "absolute_pearson_correlation"
            ]
        ),
        reverse=True
    )

    redundant_pairs.sort(
        key=lambda item: item[2],
        reverse=True
    )

    return (
        all_pairs,
        redundant_pairs,
        identifier_columns,
        correlation_variables,
        False
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
    max_correlation_columns: int = 2000,
    manual_identifier_columns: list[str] | None = None,
    nonlinear_gap: float = 0.20,
    distance_correlation_max_rows: int = 2000,
    distance_random_seed: int = 42,
    time_columns: list[str] | None = None,
    label_columns: list[str] | None = None,
    categorical_columns: list[str] | None = None,
    correlation_scope: str = "all",
    min_pairwise_n: int = 100,
) -> tuple[
    DatasetProfile,
    bool
]:
    """
    Profile the DataFrame already held in memory.

    IMPORTANT:
    This function does NOT read the dataset again.
    """

    print(
        "\n" + "=" * 72
    )

    print(
        "PROFILING DATASET IN MEMORY"
    )

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
        f"\nProfiling "
        f"{len(df.columns):,} columns..."
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

    duplicate_groups = (
        find_duplicate_columns(
            df
        )
    )

    # --------------------------------------------------------
    # Correlation profiling
    # --------------------------------------------------------

    (
        correlation_pairs,
        redundant_pairs,
        identifier_columns,
        correlation_variables,
        correlation_skipped
    ) = calculate_correlation_pairs(
        df=df,
        threshold=redundancy_threshold,
        max_correlation_columns=max_correlation_columns,
        manual_identifier_columns=manual_identifier_columns,
        nonlinear_gap=nonlinear_gap,
        distance_correlation_max_rows=distance_correlation_max_rows,
        distance_random_seed=distance_random_seed,
        time_columns=time_columns,
        label_columns=label_columns,
        categorical_columns=categorical_columns,
        correlation_scope=correlation_scope,
        min_pairwise_n=min_pairwise_n,
    )

    profiling_time = (
        time.perf_counter()
        - start
    )

    profile = DatasetProfile(
        source_file=str(
            Path(
                source_file
            ).resolve()
        ),

        n_rows=len(df),

        n_cols=len(
            df.columns
        ),

        input_file_bytes=(
            input_file_bytes
        ),

        total_bytes_in_memory=(
            total_memory
        ),

        load_time_seconds=(
            load_time_seconds
        ),

        profiling_time_seconds=(
            profiling_time
        ),

        columns=columns,

        duplicate_column_groups=(
            duplicate_groups
        ),

        correlation_pairs=(
            correlation_pairs
        ),

        redundant_pairs=(
            redundant_pairs
        ),

        identifier_columns=(
            identifier_columns
        ),

        correlation_variables=(
            correlation_variables
        ),
        variable_roles=classify_variable_roles(
            df, identifier_columns, time_columns,
            label_columns, categorical_columns,
            manual_identifier_columns,
        ),
        correlation_scope=correlation_scope,
        min_pairwise_n=min_pairwise_n,
    )

    return (
        profile,
        correlation_skipped
    )


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

    return (
        pd.DataFrame(
            records
        )
        .sort_values(
            "estimated_bytes",
            ascending=False
        )
    )


# ============================================================
# Console report
# ============================================================

def print_profile_report(
    profile: DatasetProfile,
    correlation_skipped: bool,
    threshold: float,
    nonlinear_gap: float,
    top_n: int = 10
) -> None:

    print("\n")

    print("=" * 72)

    print(
        "BASELINE PROFILE RESULTS"
    )

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

    print(
        "\n" + "-" * 72
    )

    print(
        f"TOP {top_n} VARIABLES "
        f"BY IN-MEMORY STORAGE"
    )

    print("-" * 72)

    columns_df = (
        column_profiles_to_dataframe(
            profile
        )
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
        ]
        .head(top_n)
        .to_string(
            index=False
        )
    )

    # --------------------------------------------------------
    # Duplicate columns
    # --------------------------------------------------------

    print(
        "\n" + "-" * 72
    )

    if (
        profile
        .duplicate_column_groups
    ):

        print(
            "EXACT DUPLICATE COLUMN GROUPS"
        )

        for group in (
            profile
            .duplicate_column_groups
        ):

            print(
                f"  {group}"
            )

    else:

        print(
            "No exact duplicate columns found."
        )

    # --------------------------------------------------------
    # Correlation-variable summary
    # --------------------------------------------------------

    print(
        "\n" + "-" * 72
    )

    print(
        "CORRELATION PROFILING"
    )

    print("-" * 72)

    numeric_id_set = {
        col.name for col in profile.columns
        if col.name in profile.identifier_columns
        and pd.api.types.is_numeric_dtype(pd.api.types.pandas_dtype(col.dtype))
    }
    print(f"Identifiers detected         : {len(profile.identifier_columns)}")
    print(f"Numeric identifiers excluded : {len(numeric_id_set)}")

    for column in (
        profile.identifier_columns
    ):

        print(
            f"  - {column}"
        )

    print(
        f"\nNumeric analytical variables: "
        f"{len(profile.correlation_variables)}"
    )

    for column in (
        profile.correlation_variables
    ):

        print(
            f"  - {column}"
        )

    # --------------------------------------------------------
    # Variable role classifications (descriptive only)
    # --------------------------------------------------------
    print("\nVARIABLE ROLE DETECTION (all columns preserved)")
    role_df = profile.variable_roles
    if not role_df.empty:
        print(role_df[["variable", "role", "detection_method"]].to_string(index=False))
        print("\nRole totals:")
        print(role_df["role"].value_counts().to_string())

    # --------------------------------------------------------
    # All dependence measures
    # --------------------------------------------------------

    if correlation_skipped:

        print(
            "\nFull dependence analysis was skipped "
            "because the dataset exceeded the "
            "configured dimensionality safeguard."
        )

        return

    print(
        "\nALL PAIRWISE DEPENDENCE MEASURES"
    )

    print(
        "(Pearson = linear, Spearman = monotonic, "
        "distance correlation = general dependence)"
    )

    print("-" * 72)

    if profile.correlation_pairs:

        correlation_df = (
            pd.DataFrame(
                profile.correlation_pairs
            )
        )

        display = [
            "column_a",
            "column_b",
            "pearson_r",
            "spearman_rho",
            "distance_correlation",
            "pairwise_n",
            "distance_pairwise_n",
            "distance_sampled",
        ]

        print(
            correlation_df[
                display
            ].to_string(
                index=False,
                float_format=lambda x: (
                    f"{x:.6f}"
                )
            )
        )

        nonlinear_df = (
            correlation_df[
                correlation_df[
                    "nonlinear_review"
                ]
            ]
        )

        print(
            "\n" + "-" * 72
        )

        print(
            "PAIRS FLAGGED FOR NONLINEAR REVIEW"
        )

        print(
            f"(Spearman or distance dependence exceeds "
            f"|Pearson| by >= {nonlinear_gap:.2f}; "
            f"pairwise_n >= {profile.min_pairwise_n})"
        )

        if nonlinear_df.empty:

            print(
                "No pairs met the nonlinear-review rule."
            )

        else:

            nonlinear_display = [
                "column_a",
                "column_b",
                "pearson_r",
                "spearman_rho",
                "distance_correlation",
                "spearman_minus_pearson_abs",
                "distance_minus_pearson_abs",
            ]

            print(
                nonlinear_df[
                    nonlinear_display
                ].to_string(
                    index=False,
                    float_format=lambda x: (
                        f"{x:.6f}"
                    )
                )
            )

    else:

        print(
            "No eligible variable pairs."
        )

    # --------------------------------------------------------
    # Thresholded correlations
    # --------------------------------------------------------

    print(
        "\n" + "-" * 72
    )

    if profile.redundant_pairs:

        print(
            f"POTENTIALLY REDUNDANT NUMERIC VARIABLES "
            f"(|r| >= {threshold})"
        )

        for (
            a,
            b,
            correlation
        ) in (
            profile
            .redundant_pairs[
                :top_n
            ]
        ):

            print(
                f"  {a} <-> {b}: "
                f"|r| = "
                f"{correlation:.6f}"
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
) -> tuple[
    Path,
    str
]:
    """
    Create a unique directory for one profiling experiment.

    Example:
        output/profiling/
            all_stays_20260923_101845/
    """

    dataset = Path(
        dataset_path
    )

    dataset_name = (
        dataset.name
    )

    if (
        dataset_name
        .lower()
        .endswith(".csv.gz")
    ):

        dataset_name = (
            dataset_name[:-7]
        )

    else:

        dataset_name = (
            dataset.stem
        )

    now = datetime.now(
        timezone.utc
    )

    folder_timestamp = (
        now.strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    run_timestamp = (
        now.isoformat()
    )

    run_name = (
        f"{dataset_name}_"
        f"{folder_timestamp}"
    )

    run_directory = (
        Path(base_output_dir)
        / run_name
    )

    run_directory.mkdir(
        parents=True,
        exist_ok=False
    )

    return (
        run_directory,
        run_timestamp
    )


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

    The checksum provides dataset provenance.
    """

    sha256 = (
        hashlib.sha256()
    )

    with open(
        file_path,
        "rb"
    ) as file:

        while True:

            chunk = file.read(
                chunk_size
            )

            if not chunk:
                break

            sha256.update(
                chunk
            )

    return (
        sha256.hexdigest()
    )


# ============================================================
# Save results
# ============================================================

def save_profile_results(
    profile: DatasetProfile,
    df: pd.DataFrame,
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
    # 1. Complete column profile
    # --------------------------------------------------------

    column_file = (
        output_path
        / "column_profile.csv"
    )

    column_profiles_to_dataframe(
        profile
    ).to_csv(
        column_file,
        index=False
    )

    # --------------------------------------------------------
    # 2. Numeric-variable profile
    # --------------------------------------------------------

    numeric_file = (
        output_path
        / "numeric_variable_profile.csv"
    )

    numeric_variable_profile(
        df,
        profile.identifier_columns,
        profile.variable_roles,
        profile.correlation_scope,
    ).to_csv(
        numeric_file,
        index=False
    )

    # Complete role audit: every column, whether or not correlated.
    profile.variable_roles.to_csv(
        output_path / "variable_roles.csv", index=False
    )

    # --------------------------------------------------------
    # 3. ALL pairwise correlations
    # --------------------------------------------------------

    all_correlation_file = (
        output_path
        / "correlation_all_pairs.csv"
    )

    correlation_output_df = pd.DataFrame(
        profile.correlation_pairs,
        columns=[
            "column_a",
            "column_b",
            "pearson_r",
            "absolute_pearson_correlation",
            "spearman_rho",
            "absolute_spearman_correlation",
            "distance_correlation",
            "pairwise_n",
            "distance_pairwise_n",
            "distance_sampled",
            "above_threshold",
            "spearman_minus_pearson_abs",
            "distance_minus_pearson_abs",
            "nonlinear_review",
            "nonlinear_gap_met",
            "nonlinear_review_status",
            "status",
        ]
    )

    correlation_output_df.to_csv(
        all_correlation_file,
        index=False
    )

    # --------------------------------------------------------
    # 3b. Pairs flagged for exploratory nonlinear review
    # --------------------------------------------------------

    nonlinear_file = (
        output_path
        / "nonlinear_dependency_pairs.csv"
    )

    if correlation_output_df.empty:
        nonlinear_output_df = correlation_output_df.copy()
    else:
        nonlinear_output_df = (
            correlation_output_df[
                correlation_output_df[
                    "nonlinear_review"
                ] == True
            ]
            .copy()
        )

    nonlinear_output_df.to_csv(
        nonlinear_file,
        index=False
    )

    # --------------------------------------------------------
    # 4. Thresholded correlated variables
    # --------------------------------------------------------

    redundant_file = (
        output_path
        / "redundant_pairs.csv"
    )

    pd.DataFrame(
        profile.redundant_pairs,
        columns=[
            "column_a",
            "column_b",
            "absolute_pearson_correlation"
        ]
    ).to_csv(
        redundant_file,
        index=False
    )

    # --------------------------------------------------------
    # 5. Duplicate columns
    # --------------------------------------------------------

    duplicate_file = (
        output_path
        / "duplicate_columns.csv"
    )

    duplicate_records = []

    for (
        group_id,
        group
    ) in enumerate(
        profile.duplicate_column_groups,
        start=1
    ):

        for column in group:

            duplicate_records.append({
                "group_id":
                    group_id,

                "column":
                    column
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
    # 6. Dataset summary
    # --------------------------------------------------------

    summary_file = (
        output_path
        / "dataset_summary.csv"
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

        "numeric_identifiers_excluded":
            sum(
                col.name in profile.identifier_columns
                and pd.api.types.is_numeric_dtype(pd.api.types.pandas_dtype(col.dtype))
                for col in profile.columns
            ),

        "numeric_variables_correlated":
            len(
                profile.correlation_variables
            ),

        "correlation_pairs_calculated":
            len(
                profile.correlation_pairs
            ),

        "duplicate_groups":
            len(
                profile
                .duplicate_column_groups
            ),

        "highly_correlated_pairs":
            len(
                profile.redundant_pairs
            ),

        "nonlinear_review_pairs":
            sum(
                1
                for item in profile.correlation_pairs
                if item.get(
                    "nonlinear_review",
                    False
                )
            ),

        "correlation_threshold":
            threshold,

        "min_pairwise_n_for_nonlinear_review":
            profile.min_pairwise_n,

        "numeric_columns_skipped_in_selected_scope":
            int(sum(
                pd.api.types.is_numeric_dtype(
                    pd.api.types.pandas_dtype(row.data_type)
                ) and not bool(getattr(
                    row,
                    "included_in_continuous_correlation"
                    if profile.correlation_scope == "continuous"
                    else "included_in_general_correlation",
                ))
                for row in profile.variable_roles.itertuples(index=False)
            )),

        "correlation_skipped":
            correlation_skipped,
    }])

    summary.to_csv(
        summary_file,
        index=False
    )

    # ========================================================
    # 7. Reproducibility metadata
    # ========================================================

    metadata_file = (
        output_path
        / "profile_metadata.json"
    )

    roles_df = profile.variable_roles
    automatic_roles = {
        role: roles_df.loc[
            roles_df["automatic_role"] == role, "variable"
        ].tolist()
        for role in sorted(roles_df["automatic_role"].unique())
    }
    effective_roles = {
        role: roles_df.loc[roles_df["role"] == role, "variable"].tolist()
        for role in sorted(roles_df["role"].unique())
    }
    role_overrides = {
        "identifier": command_line_args.identifier_columns,
        "time": command_line_args.time_columns,
        "outcome": command_line_args.label_columns,
        "categorical": command_line_args.categorical_columns,
    }
    eligibility_col = (
        "included_in_continuous_correlation"
        if profile.correlation_scope == "continuous"
        else "included_in_general_correlation"
    )
    skipped_values = roles_df.loc[
        roles_df["value_status"].isin(["empty", "constant", "too_few_observations"]),
        ["variable", "value_status"],
    ].to_dict(orient="records")

    metadata = {

        "variable_classification": {
            "automatic_roles": automatic_roles,
            "manual_overrides": role_overrides,
            "effective_roles": effective_roles,
            "effective_role_by_column": dict(zip(
                roles_df["variable"], roles_df["role"]
            )),
            "automatic_roles_are_candidates": True,
            "correlation_scope": profile.correlation_scope,
            "eligible_correlation_variables": profile.correlation_variables,
            "ineligible_numeric_or_constant_columns": skipped_values,
            "all_original_columns_retained_for_transfer": True,
            "detailed_role_audit_file": "variable_roles.csv",
        },

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

            "nonlinear_gap":
                command_line_args
                .nonlinear_gap,

            "min_pairwise_n": command_line_args.min_pairwise_n,

            "distance_correlation_max_rows":
                command_line_args
                .distance_correlation_max_rows,

            "distance_random_seed":
                command_line_args
                .distance_random_seed,

            "max_correlation_columns":
                command_line_args
                .max_correlation_columns,

            "top_n":
                command_line_args
                .top_n,

            "base_output_directory":
                command_line_args
                .output_dir,
        },

        # ----------------------------------------------------
        # Correlation methodology
        # ----------------------------------------------------

        "correlation_analysis": {

            "purpose":
                (
                    "Descriptive Phase 1 profiling "
                    "of relationships and potential "
                    "redundancy among numeric "
                    "analytical variables."
                ),

            "methods": [
                "Pearson correlation",
                "Spearman rank correlation",
                "Distance correlation"
            ],

            "pearson_role":
                (
                    "Profiles linear association and retains the "
                    "original redundancy threshold."
                ),

            "spearman_role":
                (
                    "Profiles monotonic association, including "
                    "monotonic nonlinear relationships."
                ),

            "distance_correlation_role":
                (
                    "Exploratory check for more general nonlinear "
                    "and non-monotonic dependence."
                ),

            "threshold":
                threshold,

            "threshold_rule":
                (
                    "Potential linear redundancy flagged "
                    "when absolute Pearson "
                    "correlation >= threshold."
                ),

            "nonlinear_review_gap":
                command_line_args.nonlinear_gap,

            "min_pairwise_n_for_nonlinear_review": profile.min_pairwise_n,

            "nonlinear_gap_met_but_insufficient_n": sum(
                bool(row.get("nonlinear_gap_met"))
                and not bool(row.get("nonlinear_review"))
                for row in profile.correlation_pairs
            ),

            "nonlinear_review_rule":
                (
                    "Exploratory review only: flag a pair when "
                    "absolute Spearman correlation or distance "
                    "correlation exceeds absolute Pearson "
                    "correlation by at least nonlinear_gap AND "
                    "there are at least min_pairwise_n complete pairs. "
                    "Correlations remain available below that threshold."
                ),

            "distance_correlation_max_rows":
                command_line_args.distance_correlation_max_rows,

            "distance_random_seed":
                command_line_args.distance_random_seed,

            "distance_sampling_rule":
                (
                    "Pearson and Spearman use all pairwise-complete "
                    "observations. Distance correlation uses all "
                    "pairwise-complete observations up to the row cap; "
                    "above the cap, a deterministic random sample is "
                    "used and explicitly reported."
                ),

            "variables_removed":
                False,

            "identifier_detection":
                (
                    "Automatic column-name pattern "
                    "detection."
                ),

            "identifier_columns":
                profile.identifier_columns,

            "identifier_columns_excluded":
                True,

            "correlation_scope": profile.correlation_scope,
            "manual_time_columns": command_line_args.time_columns,
            "manual_label_columns": command_line_args.label_columns,
            "manual_categorical_columns": command_line_args.categorical_columns,
            "effective_time_columns": [
                row.variable for row in roles_df.itertuples(index=False)
                if row.role in ("time", "time_candidate")
            ],
            "effective_label_columns": [
                row.variable for row in roles_df.itertuples(index=False)
                if row.role in ("outcome", "outcome_candidate")
            ],
            "effective_binary_columns": [
                row.variable for row in roles_df.itertuples(index=False)
                if row.role == "binary"
            ],

            "correlation_variables":
                profile.correlation_variables,

            "missing_value_strategy":
                (
                    "Pairwise-complete observations."
                ),

            "total_pairs":
                len(
                    profile.correlation_pairs
                ),

            "highly_correlated_pairs":
                len(
                    profile.redundant_pairs
                ),

            "nonlinear_review_pairs":
                sum(
                    1
                    for item in profile.correlation_pairs
                    if item.get(
                        "nonlinear_review",
                        False
                    )
                ),

            "correlation_skipped":
                correlation_skipped,
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
                    profile
                    .duplicate_column_groups
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

def parse_arguments() -> (
    argparse.Namespace
):

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

        default=(
            "output/profiling"
        ),

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
            "for flagging potentially redundant "
            "numeric variables during profiling. "
            "No columns are removed. "
            "Default: 0.95"
        )
    )

    parser.add_argument(
        "--max-correlation-columns",

        type=int,

        default=2000,

        help=(
            "Maximum number of eligible numeric "
            "variables for complete pairwise "
            "correlation profiling. "
            "Default: 2000"
        )
    )

    parser.add_argument(
        "--top-n",

        type=int,

        default=10,

        help=(
            "Number of highest-storage variables "
            "and thresholded correlated pairs "
            "displayed. Default: 10"
        )
    )

    parser.add_argument(
        "--identifier-columns",
        nargs="*",
        default=[],
        help=(
            "Additional identifier columns that are not "
            "recognized automatically from their names. "
            "These columns are retained in the dataset but "
            "excluded from correlation analysis."
        )
    )

    parser.add_argument(
        "--time-columns", nargs="*", default=[],
        help="Override automatically inferred time columns; retained in transfer.",
    )
    parser.add_argument(
        "--label-columns", nargs="*", default=[],
        help="Override automatically inferred outcome columns; retained in transfer.",
    )
    parser.add_argument(
        "--categorical-columns", nargs="*", default=[],
        help="Columns to annotate as categorical (retained for transfer).",
    )
    parser.add_argument(
        "--correlation-scope", choices=["all", "continuous"],
        default="all",
        help="all: eligible numeric non-ID variables, including labels, "
             "time and binary indicators; continuous: quantitative "
             "numeric variables only. Empty and constant variables "
             "are excluded from both correlations. Default: all",
    )

    parser.add_argument(
        "--min-pairwise-n", type=int, default=100,
        help="Minimum number of paired observations needed to flag "
             "a nonlinear-review candidate (default: 100). All valid "
             "correlation coefficients still calculated for smaller pairs.",
    )

    parser.add_argument(
        "--nonlinear-gap",
        type=float,
        default=0.20,
        help=(
            "Exploratory nonlinear-review gap. A pair is flagged "
            "when absolute Spearman correlation or distance "
            "correlation exceeds absolute Pearson correlation by "
            "at least this amount. No columns are removed. "
            "Default: 0.20"
        )
    )

    parser.add_argument(
        "--distance-correlation-max-rows",
        type=int,
        default=2000,
        help=(
            "Maximum pairwise-complete rows used for the O(n^2) "
            "distance-correlation calculation. Larger pairs use a "
            "deterministic random sample of this size. Pearson and "
            "Spearman still use all pairwise-complete rows. "
            "Default: 2000"
        )
    )

    parser.add_argument(
        "--distance-random-seed",
        type=int,
        default=42,
        help=(
            "Random seed used only when distance correlation "
            "requires deterministic row sampling. Default: 42"
        )
    )

    args = parser.parse_args()

    if not (
        0 < args.threshold <= 1
    ):

        parser.error(
            "--threshold must be "
            "> 0 and <= 1."
        )

    if (
        args.max_correlation_columns
        < 2
    ):

        parser.error(
            "--max-correlation-columns "
            "must be >= 2."
        )

    if args.top_n < 1:

        parser.error(
            "--top-n must be >= 1."
        )

    if args.min_pairwise_n < 3:
        parser.error("--min-pairwise-n must be >= 3")

    if not (
        0 <= args.nonlinear_gap <= 1
    ):

        parser.error(
            "--nonlinear-gap must be between 0 and 1."
        )

    if (
        args.distance_correlation_max_rows
        < 3
    ):

        parser.error(
            "--distance-correlation-max-rows must be >= 3."
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

    (
        df,
        load_time,
        file_size
    ) = load_dataset(
        args.dataset
    )

    for option in ("identifier_columns", "time_columns", "label_columns", "categorical_columns"):
        missing = set(getattr(args, option)) - set(df.columns)
        if missing:
            raise ValueError(f"Unknown columns in --{option.replace('_', '-')}: {sorted(missing)}")
    overrides = (args.identifier_columns, args.time_columns,
                 args.label_columns, args.categorical_columns)
    assigned = [name for group in overrides for name in group]
    if len(set(assigned)) < len(assigned):
        raise ValueError("A column has multiple explicit roles; choose one role per column")

    # ========================================================
    # STEP 2
    # Profile the in-memory DataFrame.
    # ========================================================

    (
        profile,
        correlation_skipped
    ) = profile_dataset(

        df=df,

        source_file=(
            args.dataset
        ),

        input_file_bytes=(
            file_size
        ),

        load_time_seconds=(
            load_time
        ),

        redundancy_threshold=(
            args.threshold
        ),

        max_correlation_columns=(
            args
            .max_correlation_columns
        ),

        manual_identifier_columns=(
            args
            .identifier_columns
        ),

        nonlinear_gap=(
            args
            .nonlinear_gap
        ),

        distance_correlation_max_rows=(
            args
            .distance_correlation_max_rows
        ),

        distance_random_seed=(
            args
            .distance_random_seed
        ),
        time_columns=args.time_columns,
        label_columns=args.label_columns,
        categorical_columns=args.categorical_columns,
        correlation_scope=args.correlation_scope,
        min_pairwise_n=args.min_pairwise_n,
    )

    # ========================================================
    # STEP 3
    # Display profiling results.
    # ========================================================

    print_profile_report(

        profile=profile,

        correlation_skipped=(
            correlation_skipped
        ),

        threshold=(
            args.threshold
        ),

        nonlinear_gap=(
            args.nonlinear_gap
        ),

        top_n=(
            args.top_n
        )
    )

    # ========================================================
    # STEP 4
    # Create experiment directory.
    # ========================================================

    (
        run_directory,
        run_timestamp
    ) = create_run_directory(

        dataset_path=(
            args.dataset
        ),

        base_output_dir=(
            args.output_dir
        )
    )

    # ========================================================
    # STEP 5
    # Calculate source dataset checksum.
    #
    # Sequential binary read for provenance.
    # Does not create another DataFrame.
    # ========================================================

    print(
        "\nCalculating source dataset SHA-256..."
    )

    checksum_start = (
        time.perf_counter()
    )

    dataset_sha256 = (
        calculate_file_sha256(
            args.dataset
        )
    )

    checksum_time = (
        time.perf_counter()
        - checksum_start
    )

    print(
        f"SHA-256       : "
        f"{dataset_sha256}"
    )

    print(
        f"Checksum time : "
        f"{checksum_time:.4f} seconds"
    )

    # ========================================================
    # STEP 6
    # Save experimental results and provenance metadata.
    # ========================================================

    save_profile_results(

        profile=profile,

        df=df,

        output_dir=str(
            run_directory
        ),

        correlation_skipped=(
            correlation_skipped
        ),

        threshold=(
            args.threshold
        ),

        run_timestamp=(
            run_timestamp
        ),

        dataset_sha256=(
            dataset_sha256
        ),

        command_line_args=(
            args
        )
    )

    print(
        "\n" + "=" * 72
    )

    print(
        "PHASE 1 COMPLETED SUCCESSFULLY"
    )

    print("=" * 72)

    print(
        f"\nResults saved to:\n"
        f"  {run_directory.resolve()}"
    )

    print(
        "\nGenerated correlation outputs:"
    )

    print(
        "  - numeric_variable_profile.csv"
    )
    print("  - variable_roles.csv")

    print(
        "  - correlation_all_pairs.csv"
    )

    print(
        "  - nonlinear_dependency_pairs.csv"
    )

    print(
        "  - redundant_pairs.csv"
    )


if __name__ == "__main__":
    main()
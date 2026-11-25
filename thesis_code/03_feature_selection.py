"""
03_feature_selection.py

Phase 3 - Feature Selection

Thesis:
Efficient Dimensionality Reduction and Compression Strategies
for Large-Scale Clinical Data Transfer Between Hospitals and
University Data Centers.

Purpose
-------
Reduce unnecessary variables BEFORE Phase 4 dimensionality reduction.

Primary feature-selection stages:
    1. Missingness-based filtering
    2. Constant-feature removal
    3. Exact-duplicate removal
    4. Correlation-based redundancy filtering
    5. Domain-informed filtering

Important methodological rules
------------------------------
- Statistical rarity alone is NOT grounds for removal.
- Protected variables are never automatically removed.
- Identifier variables are automatically detected from column names.
- Additional identifiers may be supplied manually.
- Identifiers are excluded from correlation analysis but retained
  in the resulting dataset unless explicitly removed by a
  domain-informed rule.
- Mutual-information deletion is intentionally excluded from the
  primary Phase 3 experiment.
- PCA is NOT performed in this phase.
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
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# Data structures
# ============================================================

@dataclass
class SelectionReport:
    original_columns: list[str]
    kept_columns: list[str]

    dropped_columns: dict[str, str] = field(
        default_factory=dict
    )

    protected_overrides: list[str] = field(
        default_factory=list
    )

    step_records: list[dict] = field(
        default_factory=list
    )

    duplicate_pairs: list[dict] = field(
        default_factory=list
    )

    correlation_pairs: list[dict] = field(
        default_factory=list
    )

    auto_identifier_columns: list[str] = field(
        default_factory=list
    )

    manual_identifier_columns: list[str] = field(
        default_factory=list
    )

    identifier_columns: list[str] = field(
        default_factory=list
    )

    def summary(self) -> str:
        lines = [
            f"Original columns : {len(self.original_columns)}",
            f"Kept columns     : {len(self.kept_columns)}",
            f"Dropped columns  : {len(self.dropped_columns)}",
        ]

        if self.identifier_columns:
            lines.append(
                "\nIdentifier columns excluded from "
                "statistical redundancy analysis:"
            )

            for column in self.identifier_columns:
                source = []

                if column in self.auto_identifier_columns:
                    source.append("automatic")

                if column in self.manual_identifier_columns:
                    source.append("manual")

                source_text = ", ".join(source)

                lines.append(
                    f"  - {column} ({source_text})"
                )

        if self.protected_overrides:
            lines.append(
                "\nProtected overrides:"
            )

            for column in self.protected_overrides:
                lines.append(
                    f"  - {column}"
                )

        if self.dropped_columns:
            lines.append(
                "\nDropped columns:"
            )

            for column, reason in self.dropped_columns.items():
                lines.append(
                    f"  - {column}: {reason}"
                )

        return "\n".join(lines)


# ============================================================
# General utilities
# ============================================================

def human_size(
    size_bytes: int
) -> str:
    size = float(size_bytes)

    for unit in [
        "B",
        "KB",
        "MB",
        "GB",
        "TB"
    ]:
        if size < 1024:
            return f"{size:.2f} {unit}"

        size /= 1024

    return f"{size:.2f} PB"


def calculate_file_sha256(
    file_path: str | Path,
    chunk_size: int = 1024 * 1024
) -> str:
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(chunk_size)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


def percentage_reduction(
    original: float,
    reduced: float
) -> float:
    if original <= 0:
        return 0.0

    return (
        1.0
        - (reduced / original)
    ) * 100.0


# ============================================================
# Dataset loading
# ============================================================

def load_dataset(
    file_path: str | Path
) -> tuple[pd.DataFrame, float, int]:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {path}"
        )

    input_bytes = path.stat().st_size

    suffixes = [
        suffix.lower()
        for suffix in path.suffixes
    ]

    start = time.perf_counter()

    if suffixes[-2:] == [".csv", ".gz"]:
        df = pd.read_csv(
            path,
            low_memory=False
        )

    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(
            path,
            low_memory=False
        )

    elif path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)

    elif path.suffix.lower() in [
        ".xlsx",
        ".xls"
    ]:
        df = pd.read_excel(path)

    else:
        raise ValueError(
            "Unsupported dataset format. "
            "Supported formats: CSV, CSV.GZ, "
            "Parquet, XLSX and XLS."
        )

    elapsed = (
        time.perf_counter()
        - start
    )

    return (
        df,
        elapsed,
        input_bytes
    )


# ============================================================
# Output directory
# ============================================================

def create_run_directory(
    dataset_path: Path,
    output_root: str
) -> tuple[Path, str]:
    if (
        dataset_path.name
        .lower()
        .endswith(".csv.gz")
    ):
        dataset_name = dataset_path.name[:-7]

    else:
        dataset_name = dataset_path.stem

    now = datetime.now(
        timezone.utc
    )

    folder_timestamp = now.strftime(
        "%Y%m%d_%H%M%S"
    )

    timestamp_iso = now.isoformat()

    run_directory = (
        Path(output_root)
        / f"{dataset_name}_{folder_timestamp}"
    )

    run_directory.mkdir(
        parents=True,
        exist_ok=False
    )

    return (
        run_directory,
        timestamp_iso
    )


# ============================================================
# Identifier detection
# ============================================================

def normalize_column_name(
    column: str
) -> str:
    """
    Normalize a column name for pattern matching.

    Examples
    --------
    ' SUBJECT_ID ' -> 'subject_id'
    'Patient-ID'   -> 'patient-id'
    'Patient ID'   -> 'patient id'
    """
    return str(column).strip().lower()


def detect_identifier_columns(
    df: pd.DataFrame
) -> list[str]:
    """
    Automatically detect likely identifier columns from names.

    Examples detected
    -----------------
    ID
    id
    SUBJECT_ID
    subject_id
    HADM_ID
    ICUSTAY_ID
    patient-id
    patient id
    PatientID
    encounterId

    Detection is based on naming conventions only.

    This function DOES NOT drop identifier columns. The detected
    identifiers are excluded from statistical redundancy analysis.

    Manual identifier configuration remains available for datasets
    that use unusual naming conventions.
    """

    identifiers = []

    for column in df.columns:
        normalized = normalize_column_name(
            column
        )

        # Standard token/separator forms:
        #
        # id
        # subject_id
        # subject-id
        # subject id
        #
        standard_id_pattern = bool(
            re.search(
                r"(^id$|[_\-\s]id$)",
                normalized
            )
        )

        # CamelCase / compact forms:
        #
        # PatientID
        # patientId
        # encounterID
        #
        # Because lower-casing destroys CamelCase boundaries,
        # use the original stripped name as well.
        original = str(column).strip()

        camel_or_upper_id_pattern = bool(
            re.search(
                r"(?:Id|ID)$",
                original
            )
        )

        if (
            standard_id_pattern
            or camel_or_upper_id_pattern
        ):
            identifiers.append(column)

    return identifiers


def combine_identifier_columns(
    df: pd.DataFrame,
    manual_identifiers: list[str] | None
) -> tuple[
    list[str],
    list[str],
    list[str]
]:
    """
    Combine automatically detected and manually configured IDs.

    Returns
    -------
    auto_identifiers
    manual_identifiers_present
    combined_identifiers
    """

    auto_identifiers = (
        detect_identifier_columns(df)
    )

    manual_identifiers = (
        manual_identifiers or []
    )

    manual_present = [
        column
        for column in manual_identifiers
        if column in df.columns
    ]

    # Preserve original dataset column order.
    combined_set = (
        set(auto_identifiers)
        | set(manual_present)
    )

    combined = [
        column
        for column in df.columns
        if column in combined_set
    ]

    return (
        auto_identifiers,
        manual_present,
        combined
    )


# ============================================================
# Step recording
# ============================================================

def record_step(
    records: list[dict],
    step: str,
    before: int,
    after: int,
    elapsed: float
) -> None:
    records.append({
        "step": step,
        "columns_before": before,
        "columns_after": after,
        "columns_removed": before - after,
        "elapsed_seconds": elapsed,
    })


# ============================================================
# Protected-column helper
# ============================================================

def protect_or_drop(
    column: str,
    reason: str,
    protected: set[str],
    to_drop: set[str],
    dropped: dict[str, str],
    overrides: list[str]
) -> None:
    if column in protected:
        overrides.append(column)

    else:
        to_drop.add(column)
        dropped[column] = reason


# ============================================================
# Step 1 - Missingness
# ============================================================

def apply_missingness_filter(
    df: pd.DataFrame,
    threshold: float,
    protected: set[str]
) -> tuple[
    pd.DataFrame,
    dict[str, str],
    list[str]
]:
    dropped = {}
    overrides = []
    to_drop = set()

    for column in df.columns:
        missing_fraction = (
            df[column]
            .isna()
            .mean()
        )

        if missing_fraction > threshold:
            protect_or_drop(
                column=column,

                reason=(
                    f"missingness "
                    f"{missing_fraction:.2%} "
                    f"> threshold "
                    f"{threshold:.2%}"
                ),

                protected=protected,
                to_drop=to_drop,
                dropped=dropped,
                overrides=overrides
            )

    selected = df[
        [
            column
            for column in df.columns
            if column not in to_drop
        ]
    ]

    return (
        selected,
        dropped,
        sorted(set(overrides))
    )


# ============================================================
# Step 2 - Constant columns
# ============================================================

def apply_constant_filter(
    df: pd.DataFrame,
    protected: set[str]
) -> tuple[
    pd.DataFrame,
    dict[str, str],
    list[str]
]:
    """
    Remove only truly constant/non-informative columns.

    Rare binary variables are NOT removed simply because
    most observations have the same value.
    """

    dropped = {}
    overrides = []
    to_drop = set()

    for column in df.columns:
        unique_non_missing = (
            df[column]
            .nunique(dropna=True)
        )

        if unique_non_missing <= 1:
            protect_or_drop(
                column=column,

                reason=(
                    "constant or no "
                    "informative variation"
                ),

                protected=protected,
                to_drop=to_drop,
                dropped=dropped,
                overrides=overrides
            )

    selected = df[
        [
            column
            for column in df.columns
            if column not in to_drop
        ]
    ]

    return (
        selected,
        dropped,
        sorted(set(overrides))
    )


# ============================================================
# Step 3 - Exact duplicate columns
# ============================================================

def column_fingerprint(
    series: pd.Series
) -> str:
    hashed = (
        pd.util
        .hash_pandas_object(
            series,
            index=False
        )
        .values
        .tobytes()
    )

    return (
        hashlib
        .sha256(hashed)
        .hexdigest()
    )


def choose_duplicate_to_drop(
    a: str,
    b: str,
    protected: set[str],
    preferred: set[str]
) -> str | None:
    """
    Decide which exact duplicate to remove.

    Priority
    --------
    1. Protected variables survive.
    2. Preferred variables survive.
    3. Otherwise retain the first variable in original order.

    None means keep both.
    """

    a_protected = a in protected
    b_protected = b in protected

    if a_protected and b_protected:
        return None

    if a_protected:
        return b

    if b_protected:
        return a

    a_preferred = a in preferred
    b_preferred = b in preferred

    if a_preferred and not b_preferred:
        return b

    if b_preferred and not a_preferred:
        return a

    return b


def apply_duplicate_filter(
    df: pd.DataFrame,
    protected: set[str],
    preferred: set[str]
) -> tuple[
    pd.DataFrame,
    dict[str, str],
    list[str],
    list[dict]
]:
    dropped = {}
    overrides = []
    duplicate_pairs = []
    to_drop = set()

    fingerprint_groups: dict[
        str,
        list[str]
    ] = {}

    for column in df.columns:
        fingerprint = (
            column_fingerprint(
                df[column]
            )
        )

        fingerprint_groups.setdefault(
            fingerprint,
            []
        ).append(column)

    for group in fingerprint_groups.values():
        if len(group) < 2:
            continue

        retained = group[0]

        for candidate in group[1:]:
            # Fingerprint is candidate detection only.
            # Confirm exact equality before removal.
            if not df[retained].equals(
                df[candidate]
            ):
                continue

            remove = (
                choose_duplicate_to_drop(
                    retained,
                    candidate,
                    protected,
                    preferred
                )
            )

            duplicate_pairs.append({
                "column_a": retained,
                "column_b": candidate,
                "exact_duplicate": True,

                "decision": (
                    "keep_both"
                    if remove is None
                    else f"drop {remove}"
                ),
            })

            if remove is None:
                overrides.extend(
                    [
                        retained,
                        candidate
                    ]
                )

                continue

            other = (
                candidate
                if remove == retained
                else retained
            )

            to_drop.add(remove)

            dropped[remove] = (
                f"exact duplicate of {other}"
            )

            if remove == retained:
                retained = candidate

    selected = df[
        [
            column
            for column in df.columns
            if column not in to_drop
        ]
    ]

    return (
        selected,
        dropped,
        sorted(set(overrides)),
        duplicate_pairs
    )


# ============================================================
# Correlation helpers
# ============================================================

def valid_numeric_features(
    df: pd.DataFrame,
    excluded_columns: set[str]
) -> list[str]:
    """
    Return numeric analytical variables after excluding
    identifier columns.
    """

    numeric_columns = (
        df
        .select_dtypes(
            include=[np.number]
        )
        .columns
        .tolist()
    )

    return [
        column
        for column in numeric_columns
        if column not in excluded_columns
    ]


def pairwise_correlation(
    a: pd.Series,
    b: pd.Series
) -> tuple[float, int]:
    """
    Pearson correlation using pairwise-complete observations.
    """

    pair = pd.concat(
        [a, b],
        axis=1
    ).dropna()

    if len(pair) < 3:
        return (
            float("nan"),
            len(pair)
        )

    if (
        pair.iloc[:, 0]
        .nunique()
        <= 1
    ):
        return (
            float("nan"),
            len(pair)
        )

    if (
        pair.iloc[:, 1]
        .nunique()
        <= 1
    ):
        return (
            float("nan"),
            len(pair)
        )

    r = (
        pair.iloc[:, 0]
        .corr(
            pair.iloc[:, 1],
            method="pearson"
        )
    )

    return (
        float(r),
        len(pair)
    )


# ============================================================
# Step 4 - Correlation redundancy
# ============================================================

def choose_correlated_to_drop(
    a: str,
    b: str,
    df: pd.DataFrame,
    protected: set[str],
    preferred: set[str]
) -> str | None:
    """
    Decide which highly correlated variable to remove.

    Decision priority:
        1. Protected variable survives.
        2. Preferred variable survives.
        3. Variable with less missingness survives.
        4. Reproducible fallback keeps first variable.
    """

    if (
        a in protected
        and b in protected
    ):
        return None

    if a in protected:
        return b

    if b in protected:
        return a

    if (
        a in preferred
        and b not in preferred
    ):
        return b

    if (
        b in preferred
        and a not in preferred
    ):
        return a

    missing_a = (
        df[a].isna().mean()
    )

    missing_b = (
        df[b].isna().mean()
    )

    if missing_a < missing_b:
        return b

    if missing_b < missing_a:
        return a

    return b


def apply_correlation_filter(
    df: pd.DataFrame,
    threshold: float,
    protected: set[str],
    preferred: set[str],
    excluded_columns: set[str]
) -> tuple[
    pd.DataFrame,
    dict[str, str],
    list[str],
    list[dict]
]:
    columns = valid_numeric_features(
        df,
        excluded_columns
    )

    if len(columns) < 2:
        return (
            df,
            {},
            [],
            []
        )

    dropped = {}
    overrides = []
    correlation_pairs = []
    to_drop = set()

    for i in range(
        len(columns)
    ):
        for j in range(
            i + 1,
            len(columns)
        ):
            a = columns[i]
            b = columns[j]

            if (
                a in to_drop
                or b in to_drop
            ):
                continue

            r, n_pair = (
                pairwise_correlation(
                    df[a],
                    df[b]
                )
            )

            if np.isnan(r):
                continue

            abs_r = abs(r)

            if abs_r < threshold:
                continue

            remove = (
                choose_correlated_to_drop(
                    a=a,
                    b=b,
                    df=df,
                    protected=protected,
                    preferred=preferred
                )
            )

            correlation_pairs.append({
                "column_a": a,
                "column_b": b,
                "pearson_r": r,
                "abs_r": abs_r,
                "pairwise_n": n_pair,
                "threshold": threshold,

                "decision": (
                    "keep_both"
                    if remove is None
                    else f"drop {remove}"
                ),
            })

            if remove is None:
                overrides.extend(
                    [a, b]
                )

                continue

            other = (
                b
                if remove == a
                else a
            )

            to_drop.add(remove)

            dropped[remove] = (
                f"high correlation with "
                f"{other} "
                f"(r={r:.6f}, "
                f"|r| >= {threshold})"
            )

    selected = df[
        [
            column
            for column in df.columns
            if column not in to_drop
        ]
    ]

    return (
        selected,
        dropped,
        sorted(set(overrides)),
        correlation_pairs
    )


# ============================================================
# Step 5 - Domain-informed exclusion
# ============================================================

def apply_domain_filter(
    df: pd.DataFrame,
    domain_drop_columns: set[str],
    protected: set[str]
) -> tuple[
    pd.DataFrame,
    dict[str, str],
    list[str]
]:
    dropped = {}
    overrides = []
    to_drop = set()

    for column in domain_drop_columns:
        if column not in df.columns:
            continue

        protect_or_drop(
            column=column,

            reason=(
                "domain-informed exclusion"
            ),

            protected=protected,
            to_drop=to_drop,
            dropped=dropped,
            overrides=overrides
        )

    selected = df[
        [
            column
            for column in df.columns
            if column not in to_drop
        ]
    ]

    return (
        selected,
        dropped,
        sorted(set(overrides))
    )


# ============================================================
# Complete feature-selection pipeline
# ============================================================

def run_feature_selection(
    df: pd.DataFrame,
    protected_columns: list[str] | None = None,
    identifier_columns: list[str] | None = None,
    preferred_columns: list[str] | None = None,
    domain_drop_columns: list[str] | None = None,
    missingness_threshold: float = 0.90,
    correlation_threshold: float = 0.95
) -> tuple[
    pd.DataFrame,
    SelectionReport
]:
    protected = set(
        protected_columns or []
    )

    preferred = set(
        preferred_columns or []
    )

    domain_drop = set(
        domain_drop_columns or []
    )

    # --------------------------------------------------------
    # Automatic + manual identifier classification
    # --------------------------------------------------------

    (
        auto_identifiers,
        manual_identifiers,
        combined_identifiers
    ) = combine_identifier_columns(
        df,
        identifier_columns
    )

    identifiers = set(
        combined_identifiers
    )

    original_columns = list(
        df.columns
    )

    all_dropped = {}
    all_overrides = []
    step_records = []
    duplicate_pairs = []
    correlation_pairs = []

    current = df.copy()

    # --------------------------------------------------------
    # Step 1: Missingness
    # --------------------------------------------------------

    before = len(
        current.columns
    )

    start = time.perf_counter()

    (
        current,
        dropped,
        overrides
    ) = apply_missingness_filter(
        current,
        missingness_threshold,
        protected
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    all_dropped.update(dropped)
    all_overrides.extend(overrides)

    record_step(
        step_records,
        "missingness",
        before,
        len(current.columns),
        elapsed
    )

    # --------------------------------------------------------
    # Step 2: Constant variables
    # --------------------------------------------------------

    before = len(
        current.columns
    )

    start = time.perf_counter()

    (
        current,
        dropped,
        overrides
    ) = apply_constant_filter(
        current,
        protected
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    all_dropped.update(dropped)
    all_overrides.extend(overrides)

    record_step(
        step_records,
        "constant_features",
        before,
        len(current.columns),
        elapsed
    )

    # --------------------------------------------------------
    # Step 3: Exact duplicates
    # --------------------------------------------------------

    before = len(
        current.columns
    )

    start = time.perf_counter()

    (
        current,
        dropped,
        overrides,
        duplicates
    ) = apply_duplicate_filter(
        current,
        protected,
        preferred
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    all_dropped.update(dropped)
    all_overrides.extend(overrides)
    duplicate_pairs.extend(duplicates)

    record_step(
        step_records,
        "exact_duplicates",
        before,
        len(current.columns),
        elapsed
    )

    # --------------------------------------------------------
    # Step 4: Correlation
    # --------------------------------------------------------

    before = len(
        current.columns
    )

    start = time.perf_counter()

    (
        current,
        dropped,
        overrides,
        correlations
    ) = apply_correlation_filter(
        current,
        correlation_threshold,
        protected,
        preferred,
        identifiers
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    all_dropped.update(dropped)
    all_overrides.extend(overrides)
    correlation_pairs.extend(correlations)

    record_step(
        step_records,
        "correlation",
        before,
        len(current.columns),
        elapsed
    )

    # --------------------------------------------------------
    # Step 5: Domain-informed filtering
    # --------------------------------------------------------

    before = len(
        current.columns
    )

    start = time.perf_counter()

    (
        current,
        dropped,
        overrides
    ) = apply_domain_filter(
        current,
        domain_drop,
        protected
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    all_dropped.update(dropped)
    all_overrides.extend(overrides)

    record_step(
        step_records,
        "domain_informed",
        before,
        len(current.columns),
        elapsed
    )

    report = SelectionReport(
        original_columns=original_columns,

        kept_columns=list(
            current.columns
        ),

        dropped_columns=all_dropped,

        protected_overrides=sorted(
            set(all_overrides)
        ),

        step_records=step_records,

        duplicate_pairs=duplicate_pairs,

        correlation_pairs=correlation_pairs,

        auto_identifier_columns=(
            auto_identifiers
        ),

        manual_identifier_columns=(
            manual_identifiers
        ),

        identifier_columns=(
            combined_identifiers
        ),
    )

    return (
        current,
        report
    )


# ============================================================
# Save experiment results
# ============================================================

def save_results(
    original_df: pd.DataFrame,
    selected_df: pd.DataFrame,
    report: SelectionReport,
    run_directory: Path,
    source_path: Path,
    source_bytes: int,
    source_sha256: str,
    timestamp: str,
    load_seconds: float,
    selection_seconds: float,
    args: argparse.Namespace
) -> None:

    # --------------------------------------------------------
    # Selected dataset
    # --------------------------------------------------------

    selected_path = (
        run_directory
        / "selected_dataset.csv"
    )

    start = time.perf_counter()

    selected_df.to_csv(
        selected_path,
        index=False
    )

    serialization_seconds = (
        time.perf_counter()
        - start
    )

    selected_bytes = (
        selected_path
        .stat()
        .st_size
    )

    selected_sha256 = (
        calculate_file_sha256(
            selected_path
        )
    )

    # --------------------------------------------------------
    # Feature-selection report
    # --------------------------------------------------------

    report_rows = []

    auto_ids = set(
        report.auto_identifier_columns
    )

    manual_ids = set(
        report.manual_identifier_columns
    )

    combined_ids = set(
        report.identifier_columns
    )

    protected = set(
        args.protected_columns
    )

    preferred = set(
        args.preferred_columns
    )

    for column in report.original_columns:
        if column in report.dropped_columns:
            status = "dropped"

            reason = (
                report
                .dropped_columns[column]
            )

        else:
            status = "kept"
            reason = ""

        report_rows.append({
            "column": column,
            "status": status,
            "reason": reason,

            "protected":
                column in protected,

            "identifier":
                column in combined_ids,

            "identifier_auto_detected":
                column in auto_ids,

            "identifier_manual":
                column in manual_ids,

            "preferred":
                column in preferred,
        })

    pd.DataFrame(
        report_rows
    ).to_csv(
        run_directory
        / "feature_selection_report.csv",

        index=False
    )

    # --------------------------------------------------------
    # Identifier report
    # --------------------------------------------------------

    identifier_rows = []

    for column in report.identifier_columns:
        identifier_rows.append({
            "column": column,

            "automatic_detection":
                column in auto_ids,

            "manual_configuration":
                column in manual_ids,

            "excluded_from_correlation":
                True,

            "removed_from_dataset":
                column
                in report.dropped_columns,
        })

    pd.DataFrame(
        identifier_rows,
        columns=[
            "column",
            "automatic_detection",
            "manual_configuration",
            "excluded_from_correlation",
            "removed_from_dataset",
        ]
    ).to_csv(
        run_directory
        / "identifier_columns.csv",

        index=False
    )

    # --------------------------------------------------------
    # Step report
    # --------------------------------------------------------

    pd.DataFrame(
        report.step_records
    ).to_csv(
        run_directory
        / "feature_selection_steps.csv",

        index=False
    )

    # --------------------------------------------------------
    # Duplicate report
    # --------------------------------------------------------

    pd.DataFrame(
        report.duplicate_pairs,
        columns=[
            "column_a",
            "column_b",
            "exact_duplicate",
            "decision",
        ]
    ).to_csv(
        run_directory
        / "duplicate_pairs.csv",

        index=False
    )

    # --------------------------------------------------------
    # Correlation report
    # --------------------------------------------------------

    pd.DataFrame(
        report.correlation_pairs,
        columns=[
            "column_a",
            "column_b",
            "pearson_r",
            "abs_r",
            "pairwise_n",
            "threshold",
            "decision",
        ]
    ).to_csv(
        run_directory
        / "correlation_pairs.csv",

        index=False
    )

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    original_dimensions = (
        len(original_df.columns)
    )

    selected_dimensions = (
        len(selected_df.columns)
    )

    dimension_reduction_pct = (
        percentage_reduction(
            original_dimensions,
            selected_dimensions
        )
    )

    serialized_size_reduction_pct = (
        percentage_reduction(
            source_bytes,
            selected_bytes
        )
    )

    metadata = {
        "experiment": {
            "phase":
                "Phase 3 - Feature Selection",

            "timestamp_utc":
                timestamp,

            "script":
                "03_feature_selection.py",
        },

        "source_dataset": {
            "filename":
                source_path.name,

            "absolute_path":
                str(source_path),

            "sha256":
                source_sha256,

            "rows":
                int(original_df.shape[0]),

            "columns":
                int(original_df.shape[1]),

            "source_file_bytes":
                source_bytes,

            "dataframe_memory_bytes":
                int(
                    original_df
                    .memory_usage(
                        index=True,
                        deep=True
                    )
                    .sum()
                ),
        },

        "selected_dataset": {
            "filename":
                selected_path.name,

            "sha256":
                selected_sha256,

            "rows":
                int(selected_df.shape[0]),

            "columns":
                int(selected_df.shape[1]),

            "serialized_csv_bytes":
                selected_bytes,

            "dataframe_memory_bytes":
                int(
                    selected_df
                    .memory_usage(
                        index=True,
                        deep=True
                    )
                    .sum()
                ),
        },

        "reduction": {
            "original_dimensions":
                original_dimensions,

            "selected_dimensions":
                selected_dimensions,

            "dimensions_removed":
                (
                    original_dimensions
                    - selected_dimensions
                ),

            "dimension_reduction_pct":
                dimension_reduction_pct,

            "source_file_bytes":
                source_bytes,

            "selected_csv_bytes":
                selected_bytes,

            "serialized_size_reduction_pct":
                serialized_size_reduction_pct,
        },

        "identifier_detection": {
            "automatic_method":
                (
                    "case-insensitive column-name "
                    "patterns: ID, *_ID, *-ID, "
                    "' ID', PatientID/PatientId-style "
                    "suffixes"
                ),

            "automatic_identifiers":
                report.auto_identifier_columns,

            "manual_identifiers":
                report.manual_identifier_columns,

            "combined_identifiers":
                report.identifier_columns,

            "identifier_columns_removed_automatically":
                False,

            "excluded_from_correlation":
                True,
        },

        "parameters": {
            "missingness_threshold":
                args.missingness_threshold,

            "correlation_threshold":
                args.correlation_threshold,

            "protected_columns":
                args.protected_columns,

            "manual_identifier_columns":
                args.identifier_columns,

            "preferred_columns":
                args.preferred_columns,

            "domain_drop_columns":
                args.domain_drop_columns,
        },

        "timing": {
            "dataset_load_seconds":
                load_seconds,

            "feature_selection_seconds":
                selection_seconds,

            "selected_dataset_serialization_seconds":
                serialization_seconds,
        },

        "methodology": {
            "missingness_filter":
                True,

            "constant_filter":
                True,

            "exact_duplicate_filter":
                True,

            "correlation_filter":
                True,

            "mutual_information_filter":
                False,

            "pca":
                False,

            "protected_columns_override_automatic_filters":
                True,

            "identifier_detection":
                "automatic naming heuristic plus manual override",

            "identifier_columns_excluded_from_correlation":
                True,

            "identifier_columns_retained_in_dataset":
                True,

            "correlation_missing_value_strategy":
                "pairwise complete observations",

            "rare_variables_automatically_removed":
                False,
        },

        "environment": {
            "python":
                platform.python_version(),

            "pandas":
                pd.__version__,

            "numpy":
                np.__version__,

            "operating_system":
                platform.system(),

            "os_release":
                platform.release(),

            "machine":
                platform.machine(),
        },

        "command_line": {
            "argv":
                sys.argv,
        },
    }

    with open(
        run_directory
        / "feature_selection_metadata.json",

        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            metadata,
            file,
            indent=2
        )


# ============================================================
# CLI
# ============================================================

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 3 clinical-data "
            "feature-selection experiment."
        )
    )

    parser.add_argument(
        "dataset",
        help="Input clinical dataset."
    )

    parser.add_argument(
        "--missingness-threshold",
        type=float,
        default=0.90,
        help=(
            "Drop columns with missingness "
            "strictly greater than this fraction "
            "(default: 0.90)."
        )
    )

    parser.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.95,
        help=(
            "Absolute Pearson correlation "
            "threshold (default: 0.95)."
        )
    )

    parser.add_argument(
        "--protected-columns",
        nargs="*",
        default=[],
        help=(
            "Columns that automatic filters "
            "must never remove."
        )
    )

    parser.add_argument(
        "--identifier-columns",
        nargs="*",
        default=[],
        help=(
            "Additional identifier columns not "
            "detected automatically from their "
            "column names."
        )
    )

    parser.add_argument(
        "--preferred-columns",
        nargs="*",
        default=[
            "MORTALITY"
        ],
        help=(
            "Columns preferred when choosing "
            "between redundant variables."
        )
    )

    parser.add_argument(
        "--domain-drop-columns",
        nargs="*",
        default=[],
        help=(
            "Variables explicitly excluded for "
            "domain/methodological reasons."
        )
    )

    parser.add_argument(
        "--output-dir",
        default="output/feature_selection",
        help="Root output directory."
    )

    args = parser.parse_args()

    if not (
        0
        <= args.missingness_threshold
        <= 1
    ):
        parser.error(
            "--missingness-threshold "
            "must be between 0 and 1."
        )

    if not (
        0
        < args.correlation_threshold
        <= 1
    ):
        parser.error(
            "--correlation-threshold "
            "must be > 0 and <= 1."
        )

    return args


# ============================================================
# Main
# ============================================================

def main() -> None:
    args = parse_arguments()

    print("=" * 100)

    print(
        "PHASE 3 - FEATURE SELECTION"
    )

    print("=" * 100)

    source_path = Path(
        args.dataset
    ).resolve()

    # --------------------------------------------------------
    # Load dataset once
    # --------------------------------------------------------

    (
        df,
        load_seconds,
        source_bytes
    ) = load_dataset(
        source_path
    )

    print("\nDataset")
    print("-" * 50)

    print(
        f"File       : {source_path}"
    )

    print(
        f"Rows       : {len(df):,}"
    )

    print(
        f"Columns    : {len(df.columns):,}"
    )

    print(
        f"Source size: {human_size(source_bytes)}"
    )

    print(
        f"Load time  : {load_seconds:.6f} s"
    )

    # --------------------------------------------------------
    # Automatic identifier detection
    # --------------------------------------------------------

    (
        auto_identifiers,
        manual_identifiers,
        combined_identifiers
    ) = combine_identifier_columns(
        df,
        args.identifier_columns
    )

    print(
        "\nIdentifier detection"
    )

    print("-" * 50)

    print(
        "Automatically detected:"
    )

    if auto_identifiers:
        for column in auto_identifiers:
            print(
                f"  - {column}"
            )

    else:
        print("  None")

    if args.identifier_columns:
        print(
            "\nManually configured:"
        )

        for column in args.identifier_columns:
            if column in df.columns:
                print(
                    f"  - {column}"
                )

            else:
                print(
                    f"  - {column} "
                    f"(not found)"
                )

    print(
        "\nCombined identifier set:"
    )

    if combined_identifiers:
        for column in combined_identifiers:
            print(
                f"  - {column}"
            )

    else:
        print("  None")

    # --------------------------------------------------------
    # Validate configured columns
    # --------------------------------------------------------

    configured_columns = (
        set(args.protected_columns)
        | set(args.identifier_columns)
        | set(args.preferred_columns)
        | set(args.domain_drop_columns)
    )

    unknown_columns = (
        configured_columns
        - set(df.columns)
    )

    if unknown_columns:
        print(
            "\nWarning: configured columns "
            "not present in dataset:"
        )

        for column in sorted(
            unknown_columns
        ):
            print(
                f"  - {column}"
            )

    # --------------------------------------------------------
    # Create run directory
    # --------------------------------------------------------

    (
        run_directory,
        timestamp
    ) = create_run_directory(
        source_path,
        args.output_dir
    )

    # --------------------------------------------------------
    # Source provenance
    # --------------------------------------------------------

    print(
        "\nCalculating source SHA-256..."
    )

    source_sha256 = (
        calculate_file_sha256(
            source_path
        )
    )

    print(
        f"SHA-256: {source_sha256}"
    )

    # --------------------------------------------------------
    # Feature selection
    # --------------------------------------------------------

    print(
        "\nRunning feature selection..."
    )

    start = time.perf_counter()

    (
        selected_df,
        report
    ) = run_feature_selection(
        df=df,

        protected_columns=(
            args.protected_columns
        ),

        identifier_columns=(
            args.identifier_columns
        ),

        preferred_columns=(
            args.preferred_columns
        ),

        domain_drop_columns=(
            args.domain_drop_columns
        ),

        missingness_threshold=(
            args.missingness_threshold
        ),

        correlation_threshold=(
            args.correlation_threshold
        ),
    )

    selection_seconds = (
        time.perf_counter()
        - start
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_results(
        original_df=df,
        selected_df=selected_df,
        report=report,
        run_directory=run_directory,
        source_path=source_path,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        timestamp=timestamp,
        load_seconds=load_seconds,
        selection_seconds=selection_seconds,
        args=args,
    )

    # --------------------------------------------------------
    # Console summary
    # --------------------------------------------------------

    print(
        "\n" + "=" * 100
    )

    print(
        "FEATURE SELECTION RESULTS"
    )

    print("=" * 100)

    print(
        "\n" + report.summary()
    )

    original_dimensions = (
        len(df.columns)
    )

    selected_dimensions = (
        len(selected_df.columns)
    )

    dimension_reduction = (
        percentage_reduction(
            original_dimensions,
            selected_dimensions
        )
    )

    selected_path = (
        run_directory
        / "selected_dataset.csv"
    )

    selected_bytes = (
        selected_path
        .stat()
        .st_size
    )

    size_reduction = (
        percentage_reduction(
            source_bytes,
            selected_bytes
        )
    )

    print(
        "\nReduction"
    )

    print("-" * 50)

    print(
        f"Original dimensions : "
        f"{original_dimensions}"
    )

    print(
        f"Selected dimensions : "
        f"{selected_dimensions}"
    )

    print(
        f"Dimensions removed  : "
        f"{original_dimensions - selected_dimensions}"
    )

    print(
        f"Dimension reduction : "
        f"{dimension_reduction:.2f}%"
    )

    print(
        f"\nOriginal file size  : "
        f"{human_size(source_bytes)}"
    )

    print(
        f"Selected CSV size   : "
        f"{human_size(selected_bytes)}"
    )

    print(
        f"Serialized size reduction: "
        f"{size_reduction:.2f}%"
    )

    print(
        f"\nFeature-selection time: "
        f"{selection_seconds:.6f} s"
    )

    print(
        "\nOutput directory:"
    )

    print(
        f"  {run_directory.resolve()}"
    )

    print(
        "\nGenerated files:"
    )

    for path in sorted(
        run_directory.iterdir()
    ):
        print(
            f"  - {path.name}"
        )


if __name__ == "__main__":
    main()
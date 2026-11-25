#!/usr/bin/env python3
"""Phase 3: full-cohort, reproducible feature-selection experiments.

Thesis: Efficient Dimensionality Reduction and Compression Strategies for
Large-Scale Clinical Data Transfer Between Hospitals and University Data Centers.

Use with the 1,000-patient development dataset, then Training Set A (20,336
patients). There are NO train/validation/test splits in this script. Feature
selection describes and reduces this *existing* dataset for transfer experiments;
it does not establish predictive performance on unseen patients.

Methodological safeguards
-------------------------
* Compute selection statistics on ALL patients and observations.
* Preserve patient_id, time, SepsisLabel and other identifiers in every output;
  exclude them from predictor filtering and correlations.
* Report hourly missingness and patient-level measurement coverage.
* Compare no missingness filter against 80%, 90%, and 95% thresholds.
* Remove constant/all-missing predictors and confirmed exact duplicates.
* Flag high Pearson correlations for clinical review by default. An explicit
  opt-in can delete supported correlated pairs (use only with care).
* Keep the primary thresholds unmodified, and add an explicitly labelled FS-95
  clinical-review variant that retains highly sparse variables when they have
  sufficient patient-level coverage, plus explicitly justified variables.
* The 75% coverage threshold is an EXPERIMENTAL assumption, not a published
  validated cutoff. Record all decisions for sensitivity analysis.
* Compare standardized CSV sizes, record timings and SHA-256 hashes, and use
  timestamped output folders to avoid overwriting prior runs.

No FIDDLE, PCA, imputation, or mutual-information selection occurs in Phase 3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Experiment:
    name: str
    missingness_threshold: float | None
    patient_coverage_guard: float | None = None
    extra_protected: tuple[str, ...] = ()
    rationale: str = "Baseline feature-selection threshold comparison"


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def reduction_pct(before: int, after: int) -> float:
    return 100.0 * (1.0 - after / before) if before else 0.0


def load_dataset(path: Path) -> pd.DataFrame:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes[-2:] == [".csv", ".gz"] or path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ValueError("Supported dataset formats: .csv, .csv.gz, .parquet")


def detect_identifier_columns(columns: list[str]) -> list[str]:
    """Detect names such as ID, SUBJECT_ID, PatientID or encounterId."""
    detected: list[str] = []
    for column in columns:
        original = str(column).strip()
        normalized = original.lower()
        if re.search(r"(^id$|[_\-\s]id$)", normalized) or re.search(
            r"(?:ID|Id)$", original
        ):
            detected.append(column)
    return detected


def make_experiments(
    thresholds: list[float],
    include_clinical_variant: bool = True,
    fs95_coverage_min: float = 0.75,
    fs95_clinically_protected: tuple[str, ...] = ("Lactate",),
) -> list[Experiment]:
    configs = [Experiment("FS_00_no_missingness_filter", None)]
    seen = set()
    for threshold in thresholds:
        if not (0.0 <= threshold <= 1.0):
            raise ValueError("Missingness thresholds must be between 0 and 1")
        if threshold in seen:
            continue
        seen.add(threshold)
        configs.append(
            Experiment(f"FS_{round(100 * threshold):02d}_missingness", threshold)
        )
    if include_clinical_variant:
        if 0.95 not in seen:
            configs.append(Experiment("FS_95_missingness", 0.95))
        configs.append(
            Experiment(
                name="FS_95_clinical_review",
                missingness_threshold=0.95,
                patient_coverage_guard=fs95_coverage_min,
                extra_protected=fs95_clinically_protected,
                rationale=(
                    "Exploratory hypothesis: retain sparse predictors measured in "
                    "a substantial share of patients and clinically motivated "
                    "variables; the cutoff is not a literature-established rule."
                ),
            )
        )
    names = [config.name for config in configs]
    if len(set(names)) != len(names):
        raise ValueError("Threshold names collide; use distinct whole-percent values")
    return configs


def availability_profile(
    df: pd.DataFrame, patient_column: str, columns: list[str]
) -> pd.DataFrame:
    """Patient coverage is the share of patients measured at least once."""
    n_rows = len(df)
    n_patients = int(df[patient_column].nunique())
    records: list[dict] = []
    patient_ids = df[patient_column]
    for column in columns:
        observed = df[column].notna()
        observed_rows = int(observed.sum())
        observed_patients = int(patient_ids.loc[observed].nunique())
        records.append(
            {
                "column": column,
                "dtype": str(df[column].dtype),
                "total_rows": n_rows,
                "observed_rows": observed_rows,
                "missing_rows": n_rows - observed_rows,
                "hourly_missingness_pct": reduction_pct(n_rows, observed_rows),
                "n_patients": n_patients,
                "patients_measured": observed_patients,
                "patient_coverage_pct": (
                    100.0 * observed_patients / n_patients if n_patients else 0.0
                ),
                "n_unique_nonmissing": int(df[column].nunique(dropna=True)),
            }
        )
    return pd.DataFrame.from_records(records).set_index("column", drop=False)


def choose_redundant_column(
    a: str,
    b: str,
    profile: pd.DataFrame,
    preferred: set[str],
) -> str:
    """Keep preferred variable, otherwise most-observed variable, else first."""
    if a in preferred and b not in preferred:
        return b
    if b in preferred and a not in preferred:
        return a
    missing_a = float(profile.loc[a, "hourly_missingness_pct"])
    missing_b = float(profile.loc[b, "hourly_missingness_pct"])
    if missing_a < missing_b:
        return b
    if missing_b < missing_a:
        return a
    return b


def feature_selection(
    df: pd.DataFrame,
    all_columns: list[str],
    profile: pd.DataFrame,
    experiment: Experiment,
    protected: set[str],
    preferred: set[str],
    domain_drop: set[str],
    patient_column: str,
    correlation_threshold: float,
    min_pairwise_observations: int,
    min_pairwise_patients: int,
    correlation_action: str,
) -> tuple[list[str], list[dict], list[dict], list[dict], list[dict]]:
    """Select columns from the full dataset, retaining their original order."""
    current = list(all_columns)
    # Only the explicitly labelled clinical-review experiment adds protection.
    clinical_protected = set(experiment.extra_protected)
    protected = protected | clinical_protected
    retained_by_coverage: set[str] = set()
    retained_by_clinical_review: set[str] = set()
    dropped: dict[str, str] = {}
    step_rows: list[dict] = []
    duplicate_pairs: list[dict] = []
    correlation_pairs: list[dict] = []
    steps_started = time.perf_counter()

    def record(step: str, before: int, start: float) -> None:
        step_rows.append(
            {
                "step": step,
                "columns_before": before,
                "columns_after": len(current),
                "columns_removed": before - len(current),
                "elapsed_seconds": time.perf_counter() - start,
            }
        )

    # (1) Hourly missingness; the standard FS-95 stays unmodified.
    # The clinical variant is exploratory, with its own auditable retention notes.
    before = len(current)
    start = time.perf_counter()
    if experiment.missingness_threshold is not None:
        threshold_pct = experiment.missingness_threshold * 100.0
        for column in list(current):
            missingness = float(profile.loc[column, "hourly_missingness_pct"])
            coverage = float(profile.loc[column, "patient_coverage_pct"])
            if missingness <= threshold_pct + 1e-10:
                continue
            if column in clinical_protected:
                retained_by_clinical_review.add(column)
                continue
            if column in protected:
                continue
            if (
                experiment.patient_coverage_guard is not None
                and coverage >= 100.0 * experiment.patient_coverage_guard
            ):
                retained_by_coverage.add(column)
                continue
            current.remove(column)
            dropped[column] = (
                f"hourly missingness {missingness:.2f}% > {threshold_pct:.2f}% "
                f"(patients measured {coverage:.2f}%)"
            )
    record("missingness", before, start)

    # (2) Truly constant/all missing; do not remove rare but varying features.
    before = len(current)
    start = time.perf_counter()
    for column in list(current):
        if column not in protected and int(profile.loc[column, "n_unique_nonmissing"]) <= 1:
            current.remove(column)
            dropped[column] = "constant or entirely missing in the dataset"
    record("constant_features", before, start)

    # (3) Full-dataset exact duplicates. Confirm equality, never rely on hash alone.
    before = len(current)
    start = time.perf_counter()
    fingerprints: dict[str, list[str]] = {}
    for column in current:
        if column in protected:
            continue
        hashed = pd.util.hash_pandas_object(df[column], index=False).to_numpy()
        digest = hashlib.sha256(hashed.tobytes()).hexdigest()
        fingerprints.setdefault(digest, []).append(column)

    for group in fingerprints.values():
        if len(group) < 2:
            continue
        retained = group[0]
        for candidate in group[1:]:
            if retained not in current or candidate not in current:
                continue
            if not df[retained].equals(df[candidate]):
                continue
            to_drop = choose_redundant_column(retained, candidate, profile, preferred)
            survivor = candidate if to_drop == retained else retained
            duplicate_pairs.append(
                {
                    "column_a": retained,
                    "column_b": candidate,
                    "exact_duplicate_in_dataset": True,
                    "decision": f"drop {to_drop}; keep {survivor}",
                }
            )
            current.remove(to_drop)
            dropped[to_drop] = f"exact duplicate of {survivor} in full dataset"
            retained = survivor
    record("exact_duplicates", before, start)

    # (4) Correlation: only NUMERIC predictors, never label, time, or IDs.
    before = len(current)
    start = time.perf_counter()
    numeric = [
        name for name in current
        if name not in protected and pd.api.types.is_numeric_dtype(df[name])
    ]
    if len(numeric) >= 2:
        # min_periods=3 so high-r/low-support pairs are visible for review.
        coefficients = df[numeric].corr(method="pearson", min_periods=3)
        for i, a in enumerate(numeric):
            for b in numeric[i + 1 :]:
                if a not in current or b not in current:
                    continue
                r = coefficients.loc[a, b]
                if pd.isna(r) or abs(float(r)) < correlation_threshold:
                    continue
                paired = df[a].notna() & df[b].notna()
                paired_n = int(paired.sum())
                paired_patients = int(df.loc[paired, patient_column].nunique())
                supported = (
                    paired_n >= min_pairwise_observations
                    and paired_patients >= min_pairwise_patients
                )
                if not supported:
                    decision = "flag: insufficient independent-patient/paired-observation support"
                elif correlation_action == "flag":
                    decision = "flag for clinical review; retain both"
                else:
                    to_drop = choose_redundant_column(a, b, profile, preferred)
                    survivor = b if to_drop == a else a
                    current.remove(to_drop)
                    dropped[to_drop] = (
                        f"Pearson-correlated with {survivor} (r={float(r):.6f}); "
                        f"{paired_n} paired observations, {paired_patients} patients"
                    )
                    decision = f"drop {to_drop}; keep {survivor}"
                correlation_pairs.append(
                    {
                        "column_a": a,
                        "column_b": b,
                        "pearson_r": float(r),
                        "absolute_pearson_r": abs(float(r)),
                        "paired_observations": paired_n,
                        "paired_patients": paired_patients,
                        "support_sufficient": supported,
                        "correlation_threshold": correlation_threshold,
                        "decision": decision,
                    }
                )
    record("correlation_review_or_filter", before, start)

    # (5) Only explicit domain-informed removals; structural columns are protected.
    before = len(current)
    start = time.perf_counter()
    for column in list(current):
        if column in domain_drop and column not in protected:
            current.remove(column)
            dropped[column] = "explicit domain-informed exclusion"
    record("domain_informed", before, start)

    report_rows = []
    for column in all_columns:
        report_rows.append(
            {
                "column": column,
                "status": "removed" if column in dropped else "retained",
                "reason": dropped.get(column, ""),
                "protected": column in protected,
                "clinically_protected_this_experiment": column in clinical_protected,
                "hourly_threshold_exceeded": (
                    experiment.missingness_threshold is not None
                    and float(profile.loc[column, "hourly_missingness_pct"])
                    > 100.0 * experiment.missingness_threshold + 1e-10
                ),
                "retained_by_coverage_guard": column in retained_by_coverage and column in current,
                "retained_by_clinical_review": column in retained_by_clinical_review and column in current,
                "retention_rationale": (
                    "explicit clinical-review protection: needs task-specific justification"
                    if column in retained_by_clinical_review and column in current
                    else "experimental patient-coverage safeguard"
                    if column in retained_by_coverage and column in current
                    else ""
                ),
                "preferred": column in preferred,
                "hourly_missingness_pct_full": profile.loc[column, "hourly_missingness_pct"],
                "patient_coverage_pct_full": profile.loc[column, "patient_coverage_pct"],
                "n_unique_nonmissing_full": profile.loc[column, "n_unique_nonmissing"],
            }
        )
    step_rows.append(
        {
            "step": "total_selection",
            "columns_before": len(all_columns),
            "columns_after": len(current),
            "columns_removed": len(all_columns) - len(current),
            "elapsed_seconds": time.perf_counter() - steps_started,
        }
    )
    return current, report_rows, step_rows, duplicate_pairs, correlation_pairs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 3: full-cohort feature-selection sensitivity experiments (no patient split)"
    )
    parser.add_argument("dataset", help="Combined 1,000- or 20,336-patient CSV/Parquet")
    parser.add_argument("--output-dir", default="output/sepsis2019/phase3_feature_selection")
    parser.add_argument("--patient-id-col", default="patient_id")
    parser.add_argument("--time-col", default="time")
    parser.add_argument("--label-col", default="SepsisLabel")
    parser.add_argument(
        "--missingness-thresholds", type=float, nargs="+", default=[0.80, 0.90, 0.95],
        help="Multiple row-level missingness cutoffs; no-filter control is always included",
    )
    parser.add_argument("--correlation-threshold", type=float, default=0.95)
    parser.add_argument("--min-correlation-observations", type=int, default=200)
    parser.add_argument("--min-correlation-patients", type=int, default=30)
    parser.add_argument(
        "--correlation-action", choices=["flag", "drop"], default="flag",
        help="Default FLAG (manual review); 'drop' opts in to automatic support-checked deletion",
    )
    parser.add_argument(
        "--fs95-patient-coverage-min", type=float, default=0.75,
        help=("Patient-level measured fraction needed to rescue a predictor "
              "from the >95%% hourly-missingness rule in the CLINICAL VARIANT only "
              "(default 0.75, an exploratory hypothesis, not an established cutoff)"),
    )
    parser.add_argument(
        "--fs95-clinically-protected", nargs="*", default=["Lactate"],
        help=("Variables to retain in the FS-95 clinical-review variant "
              "irrespective of hourly missingness; default: Lactate"),
    )
    parser.add_argument(
        "--no-fs95-clinical-variant", action="store_true",
        help="Disable the exploratory FS-95 clinical-review experiment",
    )
    parser.add_argument("--protected-columns", nargs="*", default=[])
    parser.add_argument("--identifier-columns", nargs="*", default=[])
    parser.add_argument("--preferred-columns", nargs="*", default=[])
    parser.add_argument("--domain-drop-columns", nargs="*", default=[])
    parser.add_argument(
        "--skip-standardized-baseline", action="store_true",
        help="Skip writing baseline_reserialized.csv (source-vs-selected sizes will not be perfectly comparable)",
    )
    args = parser.parse_args()
    if not (0 < args.correlation_threshold <= 1):
        parser.error("--correlation-threshold must lie in (0, 1]")
    if args.min_correlation_observations < 3 or args.min_correlation_patients < 1:
        parser.error("Minimum correlation observations must be >=3; patients >=1")
    if not 0 <= args.fs95_patient_coverage_min <= 1:
        parser.error("--fs95-patient-coverage-min must lie in [0, 1]")
    return args


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset).expanduser().resolve()
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Input dataset does not exist: {dataset_path}")
    experiments = make_experiments(
        args.missingness_thresholds,
        include_clinical_variant=not args.no_fs95_clinical_variant,
        fs95_coverage_min=args.fs95_patient_coverage_min,
        fs95_clinically_protected=tuple(args.fs95_clinically_protected),
    )

    start_load = time.perf_counter()
    df = load_dataset(dataset_path)
    load_seconds = time.perf_counter() - start_load
    columns = list(df.columns)
    if len(set(columns)) != len(columns):
        raise ValueError("Duplicated column names are not supported")
    required = {args.patient_id_col, args.time_col, args.label_col}
    absent = required.difference(columns)
    if absent:
        raise ValueError(
            f"Missing required structural column(s): {sorted(absent)}. "
            "Use --patient-id-col/--time-col/--label-col for your column names."
        )
    configured = (
        set(args.protected_columns) | set(args.identifier_columns)
        | set(args.preferred_columns) | set(args.domain_drop_columns)
        | set(args.fs95_clinically_protected)
    )
    unknown = configured.difference(columns)
    if unknown:
        raise ValueError(f"Configured columns not found: {sorted(unknown)}")
    auto_ids = detect_identifier_columns(columns)
    identifiers = set(auto_ids) | set(args.identifier_columns) | {args.patient_id_col}
    protected = identifiers | required | set(args.protected_columns)
    preferred = set(args.preferred_columns)
    domain_drop = set(args.domain_drop_columns)
    conflicting = protected & domain_drop
    if conflicting:
        print(f"Note: protected columns cannot be domain-dropped: {sorted(conflicting)}")
    if args.correlation_action == "drop":
        print("WARNING: automatic correlation deletion enabled; verify clinical utility.")

    # Phase 3 is a full-cohort selection and transfer-size experiment.
    if df.empty:
        raise ValueError("The dataset is empty")
    if df[args.patient_id_col].isna().any():
        raise ValueError(f"Patient identifier {args.patient_id_col!r} contains nulls")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC")
    run_dir = Path(args.output_dir) / f"{dataset_path.stem}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    print(f"Source dataset: {dataset_path}")
    print(f"Rows: {len(df):,}; patients: {df[args.patient_id_col].nunique():,}; columns: {len(df.columns)}")
    print("Selection statistics: ALL patients and observations (no split)")
    print(f"Protected structural/ID columns: {sorted(protected)}")
    print(f"Results: {run_dir.resolve()}")

    source_sha = file_sha256(dataset_path)
    source_bytes = dataset_path.stat().st_size

    # Describe the entire dataset and use exactly these same statistics
    # when making feature-selection decisions.
    full_profile = availability_profile(df, args.patient_id_col, columns)
    full_profile.to_csv(run_dir / "feature_availability_full.csv", index=False)

    baseline_bytes: int | None = None
    baseline_hash: str | None = None
    baseline_serialize_seconds: float | None = None
    if not args.skip_standardized_baseline:
        baseline_path = run_dir / "baseline_reserialized.csv"
        start = time.perf_counter()
        df.to_csv(baseline_path, index=False)
        baseline_serialize_seconds = time.perf_counter() - start
        baseline_bytes = baseline_path.stat().st_size
        baseline_hash = file_sha256(baseline_path)

    summary: list[dict] = []
    for experiment in experiments:
        print(f"\nRunning {experiment.name} ...")
        config_dir = run_dir / experiment.name
        config_dir.mkdir(exist_ok=False)
        begin = time.perf_counter()
        selected_columns, report, steps, duplicate_pairs, correlation_pairs = feature_selection(
            df=df,
            all_columns=columns,
            profile=full_profile,
            experiment=experiment,
            protected=protected,
            preferred=preferred,
            domain_drop=domain_drop,
            patient_column=args.patient_id_col,
            correlation_threshold=args.correlation_threshold,
            min_pairwise_observations=args.min_correlation_observations,
            min_pairwise_patients=args.min_correlation_patients,
            correlation_action=args.correlation_action,
        )
        select_seconds = time.perf_counter() - begin

        output_file = config_dir / "selected_dataset.csv"
        begin = time.perf_counter()
        df[selected_columns].to_csv(output_file, index=False)
        write_seconds = time.perf_counter() - begin
        selected_bytes = output_file.stat().st_size
        output_sha = file_sha256(output_file)

        report_df = pd.DataFrame(report)
        report_df.to_csv(config_dir / "feature_selection_report.csv", index=False)
        # Traceable high-missingness decisions, including retained sparse features.
        if experiment.missingness_threshold is not None:
            high_missing = report_df.loc[
                report_df["hourly_threshold_exceeded"]
                & ~report_df["column"].isin(protected)
            ].copy()
        else:
            high_missing = report_df.iloc[:0].copy()
        high_missing.to_csv(config_dir / "sparse_feature_decisions.csv", index=False)
        pd.DataFrame(steps).to_csv(config_dir / "feature_selection_steps.csv", index=False)
        pd.DataFrame(
            duplicate_pairs,
            columns=["column_a", "column_b", "exact_duplicate_in_dataset", "decision"],
        ).to_csv(config_dir / "duplicate_pairs.csv", index=False)
        pd.DataFrame(
            correlation_pairs,
            columns=[
                "column_a", "column_b", "pearson_r", "absolute_pearson_r",
                "paired_observations", "paired_patients", "support_sufficient",
                "correlation_threshold", "decision",
            ],
        ).to_csv(config_dir / "correlation_pairs.csv", index=False)
        (config_dir / "retained_columns.txt").write_text(
            "\n".join(selected_columns) + "\n", encoding="utf-8"
        )
        selection_record = {
            "experiment": experiment.name,
            "hourly_missingness_threshold": experiment.missingness_threshold,
            "rows": len(df),
            "patients": int(df[args.patient_id_col].nunique()),
            "columns_original_total": len(columns),
            "columns_retained_total": len(selected_columns),
            "columns_removed_total": len(columns) - len(selected_columns),
            "predictors_original": len([c for c in columns if c not in protected]),
            "predictors_retained": len([c for c in selected_columns if c not in protected]),
            "predictors_removed": len([c for c in columns if c not in protected]) - len([c for c in selected_columns if c not in protected]),
            "predictor_reduction_pct": reduction_pct(len([c for c in columns if c not in protected]), len([c for c in selected_columns if c not in protected])),
            "dimension_reduction_pct_total": reduction_pct(len(columns), len(selected_columns)),
            "source_bytes": source_bytes,
            "standardized_baseline_bytes": baseline_bytes,
            "selected_csv_bytes": selected_bytes,
            "size_reduction_pct_vs_source": reduction_pct(source_bytes, selected_bytes),
            "size_reduction_pct_vs_standardized_baseline": (
                reduction_pct(baseline_bytes, selected_bytes) if baseline_bytes else None
            ),
            "fit_selection_seconds": select_seconds,
            "write_selected_csv_seconds": write_seconds,
            "selected_sha256": output_sha,
            "correlation_action": args.correlation_action,
            "correlation_pairs_flagged_or_reviewed": len(correlation_pairs),
            "patient_coverage_guard": experiment.patient_coverage_guard,
            "extra_clinical_protected_columns": list(experiment.extra_protected),
            "experimental_rationale": experiment.rationale,
            "retained_by_patient_coverage_guard": report_df.loc[
                report_df["retained_by_coverage_guard"], "column"
            ].tolist(),
            "retained_by_clinical_review": report_df.loc[
                report_df["retained_by_clinical_review"], "column"
            ].tolist(),
        }
        summary.append(selection_record)
        (config_dir / "experiment_metadata.json").write_text(
            json.dumps(selection_record, indent=2), encoding="utf-8"
        )
        print(
            f"  Columns: {len(columns)} -> {len(selected_columns)}; "
            f"file: {selected_bytes:,} bytes; "
            f"selection: {select_seconds:.3f}s; flagged correlations: {len(correlation_pairs)}"
        )

    pd.DataFrame(summary).to_csv(run_dir / "threshold_comparison.csv", index=False)
    metadata = {
        "phase": "Phase 3 - Feature Selection",
        "dataset": str(dataset_path),
        "source_sha256": source_sha,
        "source_bytes": source_bytes,
        "source_rows": len(df),
        "source_columns": columns,
        "patients": int(df[args.patient_id_col].nunique()),
        "timestamp_utc": timestamp,
        "patient_splitting_performed": False,
        "structural_columns": {
            "patient_id": args.patient_id_col,
            "time": args.time_col,
            "outcome": args.label_col,
            "identifier_columns": sorted(identifiers),
            "protected_columns": sorted(protected),
        },
        "parameters": {
            "missingness_thresholds": args.missingness_thresholds,
            "patient_coverage_guard": "per-experiment (FS-95 clinical variant only)",
            "fs95_patient_coverage_min": args.fs95_patient_coverage_min,
            "fs95_clinically_protected": args.fs95_clinically_protected,
            "fs95_clinical_variant_enabled": not args.no_fs95_clinical_variant,
            "correlation_threshold": args.correlation_threshold,
            "min_correlation_observations": args.min_correlation_observations,
            "min_correlation_patients": args.min_correlation_patients,
            "correlation_action": args.correlation_action,
            "preferred_columns": args.preferred_columns,
            "domain_drop_columns": args.domain_drop_columns,
        },
        "baseline": {
            "reserialized_csv_bytes": baseline_bytes,
            "reserialized_csv_sha256": baseline_hash,
            "serialization_seconds": baseline_serialize_seconds,
            "important_note": "Size differences vs original source can reflect reserialization; compare with the standardized baseline for fair CSV-to-CSV reductions.",
        },
        "methodology": {
            "feature_selection_fitted_on": "all rows and all patients in supplied dataset",
            "selected_csv_rows": "all original rows, with only selected columns",
            "hourly_missingness": "fraction of all hourly rows without measured value",
            "patient_coverage": "fraction of all patients with at least one measured value",
            "constant_filter": "<=1 distinct observed value in whole dataset",
            "exact_duplicate_filter": "pandas Series.equals on whole dataset",
            "correlation": "Pearson, pairwise complete observations from whole dataset, paired patient counts reported; correlation flags by default",
            "no_prediction_model_trained": True,
            "analytical_utility_evaluated_here": False,
            "fiddle_or_pca_applied": False,
            "clinical_variant_status": (
                "exploratory, not a validated clinical threshold; compare with unmodified FS-95"
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "input_argv": sys.argv,
        "read_dataset_seconds": load_seconds,
    }
    (run_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(f"\nCompleted {len(experiments)} experiments. Comparison: {run_dir / 'threshold_comparison.csv'}")
    if not args.no_fs95_clinical_variant:
        print(
            f"NOTE: {100 * args.fs95_patient_coverage_min:.1f}% patient coverage is "
            "a study-defined sensitivity threshold, not a published clinical cutoff."
        )


if __name__ == "__main__":
    main()

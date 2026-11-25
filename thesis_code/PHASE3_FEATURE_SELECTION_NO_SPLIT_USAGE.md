# Phase 3 — full-dataset feature selection (no patient splitting)

## File

`03_feature_selection_no_split.py` (same revised code also provided as `03_feature_selection_updated.py`).

This version is for **descriptive clinical-data reduction and transfer benchmarking**, not supervised prediction. It uses **all observations from all patients** to determine which columns to retain. No train/validation/test split is created, and no prediction model is trained. The full dataset is used to calculate hourly missingness, patient coverage, exact duplicates, and Pearson correlations. Since rules are determined on the same dataset that is reduced, do **not** claim generalisation to unseen patient cohorts or improved predictive performance from these results.

## Development run: 1,000 patients

From the `thesis_code` directory, substitute your actual input file path:

```bash
python 03_feature_selection_no_split.py \
  sepsis_1000_raw.csv \
  --output-dir output/sepsis2019/phase3_dev
```

## Main experiment: full Training Set A, 20,336 patients

After the 1,000-patient development run is validated:

```bash
python 03_feature_selection_no_split.py \
  output/sepsis2019/sepsis_20336_raw.csv \
  --output-dir output/sepsis2019/phase3_main
```

Each run creates a uniquely timestamped folder. The script reads the combined input dataset once into memory; available RAM and disk space must be adequate for 20,336 patients and four output CSVs. Do not mix metrics from different dataset versions when comparing transfer performance.

## Default experiment configurations

- `FS_00_no_missingness_filter`: no missingness deletion, but still removes entirely unobserved/constant features and exact duplicates.
- `FS_80_missingness`: delete ordinary predictor columns with **more than** 80% missing hourly rows.
- `FS_90_missingness`: delete ordinary predictors with **more than** 90% missing hourly rows.
- `FS_95_missingness`: delete ordinary predictors with **more than** 95% missing hourly rows.

The script always protects structural/identifier columns, including `patient_id`, `time`, and `SepsisLabel`. It excludes them from predictor-based redundancy checks. High correlation pairs (default |Pearson r| >=0.95) are **flagged for review**, not removed automatically.

## Optional comparisons

Retain medically important variables even if their hourly missingness is high:

```bash
python 03_feature_selection_no_split.py sepsis_1000_raw.csv \
  --protected-columns Lactate \
  --output-dir output/sepsis2019/phase3_clinical_review
```

Retain otherwise-droppable sparse features measured in at least 75% of patients (an **experimental sensitivity setting**, not a clinically validated cutoff):

```bash
python 03_feature_selection_no_split.py sepsis_1000_raw.csv \
  --sparse-coverage-guard 0.75 \
  --output-dir output/sepsis2019/phase3_coverage_review
```

Automatic correlation-based deletion is opt-in, and should be used cautiously:

```bash
python 03_feature_selection_no_split.py sepsis_1000_raw.csv \
  --correlation-action drop \
  --min-correlation-observations 200 \
  --min-correlation-patients 30 \
  --output-dir output/sepsis2019/phase3_correlation_sensitivity
```

## Output files

At the **run root**:

- `threshold_comparison.csv` — four-way comparison of predictors retained, rows, patients, sizes, reduction percentages, and processing times.
- `feature_availability_full.csv` — hourly missingness, patient-level measurement coverage and cardinality for **all patients**.
- `baseline_reserialized.csv` — standardized original-column CSV used as the denominator for fair CSV size comparisons (unless skipped).
- `run_metadata.json` — source hash, source columns, cohort dimensions, parameters and environment, with `patient_splitting_performed: false`.

Within each `FS_*` configuration directory:

- `selected_dataset.csv` — **all original patient observations**, retaining selected columns only.
- `feature_selection_report.csv` — column decisions, reasons and full-cohort missingness/coverage.
- `feature_selection_steps.csv` — filtering stage counts and timings.
- `duplicate_pairs.csv`, `correlation_pairs.csv` — evidence for redundancy review.
- `retained_columns.txt` and `experiment_metadata.json` — reproducibility and metrics.

**Removed files:** `patient_splits.csv`, `patient_split_summary.csv`, `feature_availability_training.csv`. No train/validation/test CLI flags remain.

## Research interpretation

The estimated CSV file-size reduction is measured **before compression**; benchmark compression and transfer separately. Column-selection reduction is not the same as clinically safe information reduction. Any dropped column is unavailable in the selected representation, even if it could be clinically important. Phase 4 (FIDDLE/PCA) is separate, and the downstream **analytical information-preservation** evaluation should not be described as a sepsis-prediction experiment unless you decide to add such a task.

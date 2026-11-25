> **v7 SSH recovery update:** See [README_SSH_RECOVERY.md](README_SSH_RECOVERY.md) for retries, timeouts, verified destination directories, resume, timing definitions and thesis methodology wording. It supersedes older flat-destination/failure behaviour described below.

# Thesis Code – Running Guide

## Project

**Efficient Dimensionality Reduction and Compression Strategies for Large-Scale Clinical Data Transfer Between Hospitals and University Data Centers**

This README explains how to run the thesis scripts and what the available command-line options mean.

The main current structured-data workflow is:

```text
Dataset
  |
  v
01_profiling.py
  |
  v
02_transfer_benchmark.py
  |
  v
03_feature_selection.py
  |
  v
Later phases: dimensionality reduction, utility evaluation, packaging
```

The older `00_data_preparation.py` and `01_fiddle_interface.py` scripts are optional helpers and are documented separately at the end.

---

# 1. Environment Setup

From the thesis project directory:

```bash
cd ~/philemon/thesis_code
```

Activate the project virtual environment:

```bash
source thesis/bin/activate
```

Check Python:

```bash
python --version
```

Useful package checks:

```bash
python -c "import pandas, numpy; print(pandas.__version__, numpy.__version__)"
```

Some file formats require optional packages:

```bash
pip install pyarrow
pip install zstandard
pip install openpyxl
```

- `pyarrow` is normally required for Parquet.
- `zstandard` is required for `.csv.zst`.
- `openpyxl` is normally required for `.xlsx`.

To see the exact options supported by any script:

```bash
python SCRIPT_NAME.py --help
```

Example:

```bash
python 01_profiling.py --help
```

---

# 2. Phase 1 – Baseline Dataset Profiling

## Script

```text
01_profiling.py
```

## Purpose

Profiles the source dataset without modifying it.

The script measures:

- number of rows and columns;
- source-file size;
- in-memory DataFrame size;
- data types;
- missingness;
- cardinality;
- zero sparsity;
- per-column memory footprint;
- exact duplicate columns;
- numeric dependence;
- Pearson correlation;
- Spearman rank correlation;
- distance correlation;
- possible nonlinear relationships;
- potentially redundant numeric variables;
- dataset loading time;
- profiling time;
- SHA-256 checksum and reproducibility metadata.

Numeric identifier variables are retained in the dataset but excluded from dependence analysis.

## Supported input formats

```text
.csv
.csv.gz
.csv.zst
.parquet
.xlsx
.xls
```

## Basic syntax

```bash
python 01_profiling.py DATASET [OPTIONS]
```

## Simplest run

```bash
python 01_profiling.py all_stays.csv
```

## Running each supported format

Plain CSV:

```bash
python 01_profiling.py all_stays.csv
```

gzip-compressed CSV:

```bash
python 01_profiling.py all_stays.csv.gz
```

Zstandard-compressed CSV:

```bash
python 01_profiling.py all_stays.csv.zst
```

Parquet:

```bash
python 01_profiling.py all_stays.parquet
```

Excel `.xlsx`:

```bash
python 01_profiling.py all_stays.xlsx
```

Legacy Excel `.xls`:

```bash
python 01_profiling.py all_stays.xls
```

---

## Phase 1 options

### `DATASET`

Required positional argument.

```bash
python 01_profiling.py all_stays.csv
```

This is the file to profile.

### `--output-dir`

Output base directory.

Default:

```text
output/profiling
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --output-dir output/profiling
```

Custom directory:

```bash
python 01_profiling.py all_stays.csv \
    --output-dir results/phase1
```

Each execution creates a timestamped run directory.

Example:

```text
output/profiling/
└── all_stays_20261012_044500/
```

### `--threshold`

Absolute Pearson-correlation threshold used to flag potential linear redundancy.

Default:

```text
0.95
```

Rule:

```text
|Pearson r| >= threshold
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --threshold 0.95
```

Alternative exploratory threshold:

```bash
python 01_profiling.py all_stays.csv \
    --threshold 0.90
```

This does **not** remove variables in Phase 1. It only flags them.

Allowed range:

```text
0 < threshold <= 1
```

### `--max-correlation-columns`

Maximum number of eligible numeric variables for complete pairwise dependence analysis.

Default:

```text
2000
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --max-correlation-columns 1000
```

This is a computational safeguard because the number of pairs grows approximately as:

```text
p(p - 1) / 2
```

If the number of eligible numeric columns exceeds the limit, complete correlation profiling is skipped rather than silently sampling variables.

Minimum:

```text
2
```

### `--top-n`

Controls how many of the highest-storage variables and thresholded correlated pairs are printed to the terminal.

Default:

```text
10
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --top-n 20
```

### `--identifier-columns`

Explicitly specifies additional identifier columns.

Use this when an identifier does not have a name such as `_ID`, `ID`, or `Id`.

Example:

```bash
python 01_profiling.py dataset.csv \
    --identifier-columns PATIENT_NUMBER VISIT_CODE
```

The script combines automatically detected identifiers with manually specified identifiers.

Identifiers are:

- retained in the dataset;
- profiled normally;
- excluded from Pearson, Spearman, and distance-correlation analysis.

Example using the current dataset:

```bash
python 01_profiling.py all_stays.csv \
    --identifier-columns SUBJECT_ID HADM_ID ICUSTAY_ID
```

This is not necessary for these columns because they are detected automatically, but it is valid.

### `--nonlinear-gap`

Exploratory rule for flagging variable pairs that may require nonlinear review.

Default:

```text
0.20
```

A pair is flagged when either:

```text
|Spearman rho| - |Pearson r| >= nonlinear_gap
```

or:

```text
distance_correlation - |Pearson r| >= nonlinear_gap
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --nonlinear-gap 0.20
```

More sensitive exploratory setting:

```bash
python 01_profiling.py all_stays.csv \
    --nonlinear-gap 0.10
```

Important: `0.20` is a **study-specific exploratory screening rule**, not a universal statistical definition of nonlinearity.

No feature is removed based on this rule during Phase 1.

Allowed range:

```text
0 <= nonlinear_gap <= 1
```

### `--distance-correlation-max-rows`

Maximum number of pairwise-complete rows used in the distance-correlation calculation.

Default:

```text
2000
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --distance-correlation-max-rows 3000
```

Pearson and Spearman still use all available pairwise-complete observations.

Only distance correlation is sampled when the number of usable observations exceeds this limit.

Minimum:

```text
3
```

### `--distance-random-seed`

Random seed used when distance correlation needs to sample observations.

Default:

```text
42
```

Example:

```bash
python 01_profiling.py all_stays.csv \
    --distance-random-seed 123
```

Keeping the same seed makes the sampling reproducible.

## Phase 1 – using all options together

```bash
python 01_profiling.py all_stays.csv \
    --output-dir output/profiling \
    --threshold 0.95 \
    --max-correlation-columns 2000 \
    --top-n 20 \
    --identifier-columns SUBJECT_ID HADM_ID ICUSTAY_ID \
    --nonlinear-gap 0.20 \
    --distance-correlation-max-rows 2000 \
    --distance-random-seed 42
```

For the current `all_stays` dataset, the shorter command is normally sufficient:

```bash
python 01_profiling.py all_stays.csv
```

## Phase 1 output files

A run produces files including:

```text
column_profile.csv
numeric_variable_profile.csv
correlation_all_pairs.csv
nonlinear_dependency_pairs.csv
redundant_pairs.csv
duplicate_columns.csv
dataset_summary.csv
profile_metadata.json
```

### `column_profile.csv`
Full per-variable profile.

### `numeric_variable_profile.csv`
Shows numeric variables, their data types, missingness, identifier status, and whether they were included in dependence analysis.

### `correlation_all_pairs.csv`
Contains every eligible numeric-variable pair with fields such as:

```text
column_a
column_b
pearson_r
absolute_pearson_correlation
spearman_rho
absolute_spearman_correlation
distance_correlation
pairwise_n
distance_pairwise_n
distance_sampled
above_threshold
spearman_minus_pearson_abs
distance_minus_pearson_abs
nonlinear_review
status
```

### `nonlinear_dependency_pairs.csv`
Subset of pairs flagged by the exploratory nonlinear-review rule.

### `redundant_pairs.csv`
Pairs satisfying the Pearson redundancy criterion.

### `duplicate_columns.csv`
Exact duplicate-column groups.

### `dataset_summary.csv`
Dataset-level size, timing, dimensionality, and dependence-analysis summary.

### `profile_metadata.json`
Reproducibility information including script, command-line arguments, run timestamp, dataset checksum, environment, thresholds, random seed, and dependence-analysis configuration.

---

# 3. Phase 2 – Baseline Transfer Benchmark

## Script

```text
02_transfer_benchmark.py
```

## Purpose

Benchmarks file packaging and transfer performance before dimensionality reduction.

## Basic syntax

```bash
python 02_transfer_benchmark.py DATASET [OPTIONS]
```

## Simplest run

```bash
python 02_transfer_benchmark.py all_stays.csv
```

## Phase 2 options

### `DATASET`
Input dataset.

### `--transfer-mode`
Available values:

```text
simulated
ssh
```

Simulated transfer:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode simulated
```

Real SSH/SCP transfer:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode ssh \
    --host RECEIVER_HOST \
    --user RECEIVER_USER
```

### `--packaging-runs`
Default:

```text
10
```

Example:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --packaging-runs 20
```

### `--transfer-runs`
Default:

```text
10
```

Example:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-runs 20
```

### `--bandwidth-mbps`
Bandwidth used for simulated transfer.

Default:

```text
100.0 Mbps
```

Example:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode simulated \
    --bandwidth-mbps 50
```

### `--gzip-level`
Default:

```text
6
```

Example:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --gzip-level 9
```

### `--zstd-level`
Default:

```text
3
```

Example:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --zstd-level 5
```

### `--host`
Remote receiver hostname or IP address for SSH mode.

Example:

```bash
--host 192.168.1.50
```

### `--user`
Remote SSH username.

Example:

```bash
--user researcher
```

### `--port`
Default:

```text
22
```

Example:

```bash
--port 2222
```

### `--remote-dir`
Default:

```text
/tmp/thesis_transfer
```

Example:

```bash
--remote-dir /home/researcher/thesis_transfer
```

### `--output-dir`
Default:

```text
output/transfer
```

Example:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --output-dir output/transfer
```

## Phase 2 – complete simulated example

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode simulated \
    --packaging-runs 10 \
    --transfer-runs 10 \
    --bandwidth-mbps 100 \
    --gzip-level 6 \
    --zstd-level 3 \
    --output-dir output/transfer
```

## Phase 2 – complete SSH example

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode ssh \
    --packaging-runs 10 \
    --transfer-runs 10 \
    --gzip-level 6 \
    --zstd-level 3 \
    --host RECEIVER_HOST \
    --user RECEIVER_USER \
    --port 22 \
    --remote-dir /tmp/thesis_transfer \
    --output-dir output/transfer
```

For repeated SSH/SCP runs, SSH key authentication is preferable to repeatedly entering a password.

---

# 4. Phase 3 – Feature Selection

## Script

```text
03_feature_selection.py
```

## Purpose

Applies actual feature-selection rules after Phase 1 profiling and Phase 2 baseline benchmarking.

The feature-selection process includes missingness filtering, constant-feature checking, exact duplicate detection, correlation-based redundancy checking, identifier handling, protected variables, and domain-informed exclusions.

PCA is **not** part of Phase 3. PCA belongs to the later dimensionality-reduction phase.

## Basic syntax

```bash
python 03_feature_selection.py DATASET [OPTIONS]
```

## Simplest run

```bash
python 03_feature_selection.py all_stays.csv
```

## Phase 3 options

### `DATASET`
Dataset to process.

### `--missingness-threshold`
Default:

```text
0.90
```

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --missingness-threshold 0.90
```

A lower threshold is more aggressive.

### `--correlation-threshold`
Default:

```text
0.95
```

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --correlation-threshold 0.95
```

### `--protected-columns`
Columns that must not be automatically removed.

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --protected-columns MORTALITY AGE
```

### `--identifier-columns`
Explicit identifier variables.

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --identifier-columns SUBJECT_ID HADM_ID ICUSTAY_ID
```

### `--preferred-columns`
Specifies preferred variables when redundant or duplicate variables represent the same information.

Established default:

```text
MORTALITY
```

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --preferred-columns MORTALITY
```

### `--domain-drop-columns`
Explicit domain-informed removal list.

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --domain-drop-columns COLUMN_A COLUMN_B
```

### `--output-dir`
Default:

```text
output/feature_selection
```

Example:

```bash
python 03_feature_selection.py all_stays.csv \
    --output-dir output/feature_selection
```

## Phase 3 – using all established options

```bash
python 03_feature_selection.py all_stays.csv \
    --missingness-threshold 0.90 \
    --correlation-threshold 0.95 \
    --protected-columns AGE LOS \
    --identifier-columns SUBJECT_ID HADM_ID ICUSTAY_ID \
    --preferred-columns MORTALITY \
    --domain-drop-columns COLUMN_A COLUMN_B \
    --output-dir output/feature_selection
```

If there are no domain-drop columns, use the shorter form:

```bash
python 03_feature_selection.py all_stays.csv \
    --missingness-threshold 0.90 \
    --correlation-threshold 0.95 \
    --preferred-columns MORTALITY
```

## Typical Phase 3 output

```text
output/feature_selection/
└── all_stays_YYYYMMDD_HHMMSS/
    ├── selected_dataset.csv
    ├── feature_selection_report.csv
    ├── feature_selection_steps.csv
    ├── duplicate_pairs.csv
    ├── correlation_pairs.csv
    └── feature_selection_metadata.json
```

Keep `selected_dataset.csv` as the Phase 3 artifact and use it as input to later phases rather than overwriting it.

---

# 5. Optional / Earlier Data-Preparation Helper

## Script

```text
00_data_preparation.py
```

This script was used earlier to prepare external structured datasets and create alternative representations such as raw/gzip data, minimally extracted features, and FIDDLE-compatible long-format data.

Confirmed basic usage:

```bash
python 00_data_preparation.py INPUT_FILE
```

Example:

```bash
python 00_data_preparation.py all_stays.csv \
    --id-col SUBJECT_ID \
    --time-col ADMITTIME
```

Confirmed options from the earlier implementation:

### `--id-col`
Earlier default:

```text
patient_id
```

### `--time-col`
Earlier default:

```text
None
```

An earlier revision also discussed a `--value-cols` option, for example:

```bash
--value-cols AGE LOS
```

Because this helper changed during development, verify the exact local version before relying on this option:

```bash
python 00_data_preparation.py --help
```

The current thesis workflow can operate directly on structured source data, so FIDDLE formatting is not required for the present Phase 1–3 pathway.

---

# 6. Optional FIDDLE Interface

## Script

```text
01_fiddle_interface.py
```

Typical usage:

```bash
python 01_fiddle_interface.py mimic
```

Earlier versions also allowed:

```bash
python 01_fiddle_interface.py eicu
```

The MIMIC configuration used during thesis experiments was:

```text
T = 48.0
dt = 1.0
theta_1 = 0.001
theta_2 = 0.001
theta_freq = 1.0
stats_functions = min max mean
```

Equivalent underlying FIDDLE invocation:

```bash
python -m FIDDLE.run \
    --data_fname=./input/mimic_data.csv \
    --population_fname=./input/mimic_population.csv \
    --output_dir=./output/mimic/ \
    --T=48.0 \
    --dt=1.0 \
    --theta_1=0.001 \
    --theta_2=0.001 \
    --theta_freq=1.0 \
    --stats_functions min max mean
```

Typical outputs include:

```text
S_all.npz
S.npz
X_all.npz
X.npz
feature-name JSON files
discretization JSON files
IDs.csv
frequency files
```

The current structured-data pathway does not require FIDDLE unless an experiment specifically compares the FIDDLE representation against the raw/structured pathway.

---

# 7. Recommended Current Execution Order

## Step 1 – Profile raw data

```bash
python 01_profiling.py all_stays.csv
```

Optionally repeat with equivalent storage formats:

```bash
python 01_profiling.py all_stays.csv.gz
python 01_profiling.py all_stays.csv.zst
python 01_profiling.py all_stays.parquet
```

## Step 2 – Establish transfer baseline

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode simulated
```

or, for an actual receiver:

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode ssh \
    --host RECEIVER_HOST \
    --user RECEIVER_USER
```

## Step 3 – Run feature selection

```bash
python 03_feature_selection.py all_stays.csv
```

## Step 4 – Continue to dimensionality reduction

Use the timestamped Phase 3 `selected_dataset.csv` as the input artifact for the later dimensionality-reduction phase.

Do not overwrite the Phase 3 artifact.

---

# 8. Useful Help Commands

```bash
python 01_profiling.py --help
python 02_transfer_benchmark.py --help
python 03_feature_selection.py --help
python 00_data_preparation.py --help
```

---

# 9. Reproducibility Recommendations

1. Keep the source dataset unchanged.
2. Use timestamped output directories.
3. Record the exact command used.
4. Keep thresholds in metadata.
5. Keep the random seed fixed when sampling is required.
6. Keep SHA-256 checksums for dataset provenance.
7. Do not overwrite outputs from earlier runs.
8. Compare experiments using outputs generated from the same logical dataset.
9. Treat Phase 1 nonlinear flags as exploratory evidence, not automatic feature-removal decisions.
10. Keep identifiers for linkage while excluding them from quantitative dependence calculations.

---

# 10. Current Dataset Examples

The current dataset has been tested as:

```text
all_stays.csv
all_stays.csv.gz
all_stays.csv.zst
all_stays.parquet
```

All four represent the same logical dataset:

```text
Rows:    42,276
Columns: 20
```

For a fair comparison of storage or loading performance, always confirm that the different file representations contain the same logical rows and columns.

---

# 11. Quick Command Reference

## Phase 1

```bash
python 01_profiling.py all_stays.csv
```

Full configuration:

```bash
python 01_profiling.py all_stays.csv \
    --output-dir output/profiling \
    --threshold 0.95 \
    --max-correlation-columns 2000 \
    --top-n 10 \
    --identifier-columns SUBJECT_ID HADM_ID ICUSTAY_ID \
    --nonlinear-gap 0.20 \
    --distance-correlation-max-rows 2000 \
    --distance-random-seed 42
```

## Phase 2 – simulated

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode simulated \
    --packaging-runs 10 \
    --transfer-runs 10 \
    --bandwidth-mbps 100 \
    --gzip-level 6 \
    --zstd-level 3 \
    --output-dir output/transfer
```

## Phase 2 – SSH

```bash
python 02_transfer_benchmark.py all_stays.csv \
    --transfer-mode ssh \
    --packaging-runs 10 \
    --transfer-runs 10 \
    --gzip-level 6 \
    --zstd-level 3 \
    --host RECEIVER_HOST \
    --user RECEIVER_USER \
    --port 22 \
    --remote-dir /tmp/thesis_transfer \
    --output-dir output/transfer
```

## Phase 3

```bash
python 03_feature_selection.py all_stays.csv \
    --missingness-threshold 0.90 \
    --correlation-threshold 0.95 \
    --identifier-columns SUBJECT_ID HADM_ID ICUSTAY_ID \
    --preferred-columns MORTALITY \
    --output-dir output/feature_selection
```

---

## Important methodological distinction

```text
Phase 1:
Profile and identify possible relationships/redundancy.
No automatic removal.

Phase 2:
Measure baseline packaging and transfer behaviour.

Phase 3:
Apply feature-selection decisions and create a reduced dataset.

Later Phase:
Apply dimensionality-reduction methods such as PCA and evaluate utility.
```

## Optional autoencoder GPU execution

See [README_AE_ACCELERATION.md](README_AE_ACCELERATION.md) for GPU setup, batch-size controls, live epoch progress, measured timing/quality tradeoffs and validation. CPU remains the default. Restart the dashboard server after an active experiment finishes to load the new controls.

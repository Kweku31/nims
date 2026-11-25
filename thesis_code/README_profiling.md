# Phase 1 — Baseline Clinical Dataset Profiling

This README documents **only** `01_profiling_phase1_updated.py`, the Phase 1 dataset-profiling script for the thesis:

> **Efficient Dimensionality Reduction and Compression Strategies for Large-Scale Clinical Data Transfer Between Hospitals and University Data Centers**

**Research Question 1:** Which variables or dimensions contribute most to dataset size and transfer cost?

The script measures the baseline structure and storage footprint of a clinical dataset and explores statistical dependencies between numerical columns. It **does not perform prediction, feature selection, PCA, FIDDLE processing, compression, or network transfer**. Those are separate experiments.

**Important:** All original variables—including patient identifiers, time columns, ICU indicators, and `SepsisLabel`—remain in the source dataset. A column excluded from a particular *correlation calculation* is **not deleted from the dataset** and is not excluded from later transfer.

---

## 1. Requirements and installation

- **Python:** 3.10 or newer (the script uses modern type annotations).
- **Required Python libraries:** `numpy`, `pandas`.
- **Optional format readers:** `pyarrow` for Parquet, `openpyxl` for `.xlsx`, and `xlrd` for `.xls`.
- For `.csv.zst`, the Python environment also needs Zstandard support (for example, `zstandard`).

On Ubuntu, from the thesis project directory:

```bash
cd ~/philemon/thesis_code  # replace with your actual project directory
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install numpy pandas pyarrow openpyxl xlrd zstandard
```

If you already use a thesis virtual environment, **activate that environment instead**; creating a new one is optional. For CSV-only profiling, `numpy` and `pandas` are sufficient.

Place `01_profiling_phase1_updated.py` in your project directory (or adjust its path in the commands below).

## 2. Supported datasets and file formats

| Format | Example | Notes |
|---|---|---|
| CSV | `sepsis_1000_raw.csv` | Supported by default |
| Gzip-compressed CSV | `all_stays.csv.gz` | Read as CSV |
| Zstd-compressed CSV | `data.csv.zst` | Requires Zstandard support |
| Parquet | `data.parquet` | Install `pyarrow` |
| Excel | `data.xlsx` | Install `openpyxl` |
| Legacy Excel | `data.xls` | Install `xlrd` |

The script expects **one tabular dataset per input file**. It does not combine `.psv` patient files. For the Sepsis 2019 challenge, first create the combined patient-level observation CSV using your data-preparation workflow, then profile that CSV.

## 3. Quick start

### A. Profile the entire dataset — automatic role detection

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv
```

This uses the default `--correlation-scope all`: every eligible numeric column is considered for dependence analysis, including numeric time columns, binary indicators, and `SepsisLabel`. Confirmed identifiers and globally unusable numeric columns (empty, constant, or fewer than three observed values) are excluded **from correlations only**.

### B. Run with explicit recommended Phase 1 settings

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope all \
  --min-pairwise-n 100 \
  --threshold 0.95 \
  --nonlinear-gap 0.20 \
  --distance-correlation-max-rows 2000 \
  --distance-random-seed 42
```

These are the default values; explicitly supplying them makes the research procedure easier to document.

### C. Focus the dependence analysis on quantitative variables

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope continuous
```

`continuous` restricts pairwise correlations to columns **classified as numeric**. It excludes detected identifier, time, outcome, binary, categorical, empty, and constant roles **from the correlation calculation only**. It may still include numeric demographic variables (such as `Age`) or coded numerics with more than two distinct values. Review `variable_roles.csv` before interpreting this analysis as strictly physiological.

### D. Supply manual role overrides when necessary

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --identifier-columns patient_id \
  --time-columns time ICULOS HospAdmTime \
  --label-columns SepsisLabel \
  --categorical-columns Gender Unit1 Unit2 \
  --correlation-scope continuous \
  --min-pairwise-n 200
```

Manual annotations are optional: the script first attempts automatic role detection. Manual overrides take precedence for the supplied columns; values are still retained in the original data. In `all` mode, a numeric time, outcome, or binary column remains eligible for correlation even if manually annotated; only identifier and unusable columns are excluded from that mode.

### E. Specify an output base directory

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --output-dir output/profiling/sepsis_experiments \
  --correlation-scope all
```

### F. Profile other file formats

```bash
python 01_profiling_phase1_updated.py all_stays.csv.gz
python 01_profiling_phase1_updated.py input/clinical_data.parquet
python 01_profiling_phase1_updated.py input/clinical_data.xlsx
```

### G. Save a readable terminal log

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope all 2>&1 | tee profiling_console.log
```

The console prints **all calculated variable pairs**, which can produce long output for wide datasets. The CSV outputs remain the preferred source for subsequent analysis.

### H. View all options

```bash
python 01_profiling_phase1_updated.py --help
```

## 4. Command-line options

| Argument | Default | Purpose |
|---|---|---|
| `dataset` | **Required** | Input file path |
| `--output-dir` | `output/profiling` | Base folder for timestamped experiment results |
| `--threshold` | `0.95` | Flag potential Pearson redundancy when `abs(r) >= threshold` |
| `--max-correlation-columns` | `2000` | Skip pairwise correlation profiling when the number of eligible numeric columns exceeds this safeguard |
| `--top-n` | `10` | Number of largest-memory columns and top redundant pairs displayed in the terminal report |
| `--identifier-columns` | none | Add or override identifier role(s) |
| `--time-columns` | none | Annotate time-variable role(s) |
| `--label-columns` | none | Annotate outcome/label role(s) |
| `--categorical-columns` | none | Annotate categorical role(s) |
| `--correlation-scope` | `all` | `all` or `continuous`; determines correlation eligibility, **not transfer retention** |
| `--min-pairwise-n` | `100` | Minimum complete pairs required to **flag nonlinear review**; does not suppress otherwise valid correlation estimates |
| `--nonlinear-gap` | `0.20` | Exploratory gap for nonlinear review: `max(abs(Spearman), distance_correlation) - abs(Pearson) >= gap` |
| `--distance-correlation-max-rows` | `2000` | Maximum complete paired rows used for distance correlation per variable pair |
| `--distance-random-seed` | `42` | Seed for deterministic random sampling when distance correlation exceeds its row cap |

**Validation constraints:** `0 < --threshold <= 1`; `0 <= --nonlinear-gap <= 1`; `--min-pairwise-n >= 3`; `--distance-correlation-max-rows >= 3`; `--max-correlation-columns >= 2`; `--top-n >= 1`.

**Role detection:** Column-name patterns identify likely IDs (e.g. `patient_id`, `SUBJECT_ID`), time columns (e.g. `time`, `ICULOS`, `HospAdmTime`), and labels (e.g. `SepsisLabel`). The script also detects binary columns by their observed values. These are **heuristic role candidates**, not a substitute for checking each column's clinical meaning. `variable_roles.csv` records both automatic assignments and manual overrides.

## 5. Processing workflow

1. **Load once:** Read the input file into a pandas DataFrame and measure its on-disk size and load time.
2. **Profile each column:** Calculate missing count/percentage, zero count/percentage, number of distinct observed values, cardinality ratio, and estimated in-memory bytes.
3. **Check exact duplicates:** Hash columns to find candidates, then verify equality; no duplicates are deleted.
4. **Classify variable roles:** Infer automatic roles, apply manual overrides, and document correlation eligibility.
5. **Calculate pairwise dependencies:** For eligible numeric columns, compute Pearson, Spearman, and distance correlation using complete pairs.
6. **Flag candidates:** Mark high-Pearson correlations as potentially redundant and mark exploratory nonlinear-review candidates satisfying both the gap and minimum-pair rules.
7. **Record reproducibility:** Compute a source-file SHA-256 checksum and save metadata, software versions, command-line arguments, timing, and CSV results.

**No dimensionality reduction or filtering of the transferred dataset occurs during Phase 1.**

## 6. Results directory and output files

A normal run creates a folder resembling:

```text
output/
└── profiling/
    └── sepsis_1000_raw_YYYYMMDD_HHMMSS/
        ├── column_profile.csv
        ├── variable_roles.csv
        ├── numeric_variable_profile.csv
        ├── correlation_all_pairs.csv
        ├── nonlinear_dependency_pairs.csv
        ├── redundant_pairs.csv
        ├── duplicate_columns.csv
        ├── dataset_summary.csv
        └── profile_metadata.json
```

The timestamp is based on UTC. Each run normally gets its own folder; avoid launching two runs for the same dataset and base directory in the **same second**, because the folder name would collide.

| Output | Contents / how to use it |
|---|---|
| `column_profile.csv` | **All columns**; data type, missingness, zeros, cardinality, estimated in-memory storage. Useful for Research Question 1. |
| `variable_roles.csv` | **All columns**; automatic role, manual override, final role, reason for classification, correlation eligibility in each mode, and transfer-retention indicator. |
| `numeric_variable_profile.csv` | Every numeric column and whether it participated in the selected scope's correlation analysis, with reasons. |
| `correlation_all_pairs.csv` | One row per eligible numeric pair, with coefficients, complete-pair counts, sampling status, redundancy flags, nonlinear-gap status, and computation status. |
| `nonlinear_dependency_pairs.csv` | Only pairs that satisfy the exploratory nonlinear-gap **and** `min_pairwise_n` requirements. |
| `redundant_pairs.csv` | Pairs with absolute Pearson correlation at or above `--threshold`; this is **not** a removal list. |
| `duplicate_columns.csv` | Groups of verified exactly identical columns; may contain only column headers when there are none. |
| `dataset_summary.csv` | Overall dimensions, size, memory, runtime, and counts of dependencies/flags. |
| `profile_metadata.json` | Input path, SHA-256, parameters, timestamps, automatic/manual/effective roles, software environment, and experiment settings. |

## 7. Interpreting the statistics

### Storage and missingness

- **Input file size:** Actual bytes in the selected input file on disk. Comparing CSV with gzip or Parquet reflects the supplied *representation*, not an isolated per-column contribution to compressed file size.
- **DataFrame memory:** Memory occupied by the dataset after loading; not identical to file size on disk.
- **Estimated column bytes:** Pandas per-column in-memory footprint. These are useful for identifying costly columns **in memory**, but do not directly measure a column's contribution to compressed transfer bytes.
- **`pct_missing`:** Percentage of rows with missing values for a column.
- **`pct_zero`:** Percentage of *all* rows containing an observed numerical zero (missing rows are not zero). This does not measure sparse-matrix storage directly.
- **Cardinality ratio:** `n_unique / n_rows`. A high ratio is not proof that a column is an identifier.

### Pearson, Spearman, and distance correlation

| Measure | Interpretation | Limit |
|---|---|---|
| Pearson `r` | Direction and strength of **linear** association, from −1 to 1 | Can miss nonlinear dependence |
| Spearman `rho` | Direction and strength of **monotonic rank** association, from −1 to 1 | May miss non-monotonic patterns |
| Distance correlation | Nonnegative measure of more general dependence (typically 0 to 1) | A high value alone does **not** prove nonlinearity or causation |

**Important correlation fields:**

| Field | Meaning |
|---|---|
| `pairwise_n` | Count of rows where **both** variables are observed |
| `distance_pairwise_n` | Count actually used for distance correlation |
| `distance_sampled` | `True` if distance correlation used a deterministic random subset (because `pairwise_n` exceeded its row cap) |
| `above_threshold` | `abs(Pearson r) >= --threshold` |
| `nonlinear_gap_met` | Spearman/distance gap rule met, regardless of sample-size threshold |
| `nonlinear_review` | Gap rule **and** `pairwise_n >= --min-pairwise-n` |
| `nonlinear_review_status` | Whether flagged, below gap threshold, or lacking sufficient paired observations |
| `status` | Whether coefficients were calculated or why calculation was unavailable |

**Sampling example:** If 13,038 rows contain both `HR` and `Temp`, and the cap is 2,000, Pearson and Spearman use **13,038** rows, but distance correlation uses **2,000 randomly sampled complete pairs** (`distance_sampled=True`, seed 42). Sampling is of paired **rows**, not of patients. If only 1,084 complete pairs exist, distance correlation uses all 1,084 (`distance_sampled=False`).

**Computational caution:** The implemented distance-correlation estimator uses pairwise-distance matrices with approximately quadratic memory costs in the selected number of observations. Raising the cap substantially can sharply increase RAM use and runtime.

### Interpreting flagged pairs responsibly

- **High Pearson ≠ interchangeable clinical variables.** For instance, Hct and Hgb may be related but retain distinct clinical meanings.
- **Nonlinear flag ≠ proof of a nonlinear functional relationship.** It is a heuristic screening rule; inspect plots, sample size, missingness, and robustness before drawing conclusions.
- **Minimum pairwise observations affect nonlinear-review flags only.** A high Pearson pair may still appear in `redundant_pairs.csv` even if only a small number of paired measurements were available.
- **Repeated measures matter.** A 1,000-patient Sepsis file can contain tens of thousands of *hourly rows*, which are not independent patients. Correlations currently describe pooled row-level associations, not independent patient-level associations.
- **Missingness matters.** Pairwise-complete analysis uses a potentially different subset of rows for each variable pair. Strong correlations estimated from very few complete pairs should be interpreted cautiously.

## 8. Suggested thesis experiments for profiling

**Run 1 — Full baseline dependence audit**

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope all \
  --output-dir output/profiling/full_audit
```

**Run 2 — Quantitative-variable dependence audit**

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope continuous \
  --output-dir output/profiling/quantitative_audit
```

**Run 3 — Nonlinear-review robustness check**

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope all \
  --min-pairwise-n 200 \
  --output-dir output/profiling/nonlinear_sensitivity
```

Use the **same dataset file**, and compare the generated summary, role audit, and pairwise tables. Each experiment is descriptive; do not report a threshold change as if it changed the underlying clinical measurements.

## 9. Troubleshooting

| Symptom | Explanation / action |
|---|---|
| `Dataset not found` | Run from the correct working directory or supply an absolute path, e.g. `/home/kweku/philemon/thesis_code/sepsis_1000_raw.csv`. |
| `ModuleNotFoundError: pandas` (or `numpy`) | Activate the correct virtual environment and install the missing library with `python -m pip install ...`. |
| Parquet / Excel import error | Install `pyarrow`, `openpyxl`, or `xlrd` as appropriate. |
| Automatic identifiers = 1, numeric identifiers excluded = 0 | Expected when the only ID, such as `patient_id`, is stored as text. It was never part of the numeric correlation candidate list. |
| `SepsisLabel` appears in general correlation | Expected in `--correlation-scope all`; it is a retained numeric outcome, **not being used for prediction**. |
| `EtCO2` missing from correlation | Expected if entirely empty; it remains documented in the complete profile. |
| Fewer nonlinear pairs than earlier runs | The new minimum paired-observation requirement suppresses *flags*, not the corresponding available coefficients. |
| Large memory use or long runtime | Decrease `--distance-correlation-max-rows` or reduce eligible columns; the distance-matrix computation is expensive. |
| Correlation profiling skipped | The number of eligible columns exceeded `--max-correlation-columns`; check the summary and role audit. |
| Output directory already exists | Rerun after the clock advances past that second or choose a different `--output-dir`. |
| Source SHA-256 is identical across runs | Expected when profiling the same unchanged input file; the hash checks file identity/integrity, **not the original public source or license**. |

## 10. Reproducibility checklist

- [ ] Record the **source dataset's publication, version, license/access conditions, and original download location** independently of the checksum.
- [ ] Keep the original input file unchanged.
- [ ] Review `variable_roles.csv` and document any manual corrections.
- [ ] Record correlation scope, thresholds, distance-correlation row cap, and random seed.
- [ ] Keep both `pairwise_n` and `distance_pairwise_n` when interpreting dependence.
- [ ] Preserve the timestamped output folder and `profile_metadata.json` for each run.
- [ ] Distinguish **1,000 patients** from the larger number of hourly observation rows.
- [ ] Report that Phase 1 **flags potential redundancy** but **does not eliminate or compress features**.

---

### Recommended first command

For a general Phase 1 baseline on your current Sepsis data:

```bash
python 01_profiling_phase1_updated.py sepsis_1000_raw.csv \
  --correlation-scope all \
  --min-pairwise-n 100
```

Review `variable_roles.csv`, `column_profile.csv`, `correlation_all_pairs.csv`, and `profile_metadata.json` first; use them as the evidence base for the later feature-reduction and transfer phases.

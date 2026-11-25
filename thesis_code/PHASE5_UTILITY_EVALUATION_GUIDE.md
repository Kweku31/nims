# Phase 5 — Research Utility Evaluation (PCA and Autoencoder)

This phase evaluates **existing Phase 4 outputs**. It does **not** train a classification model, retrain PCA/autoencoders, create patient splits, or require FIDDLE.

## Installation

Activate the same thesis Python virtual environment used in Phase 4. Required packages:

```bash
pip install numpy pandas scipy
```

The script does **not** require scikit-learn at evaluation time; it decodes the transmitted PCA and autoencoder arrays directly from verified Phase 4 NPZ payloads.

## Execute on the 1,000-patient experiments

Run from `thesis_code` and substitute your current Phase 4 output folders if they differ:

```bash
python 06_utility_evaluation.py \
  --experiment \
    output/sepsis2019/phase4_dev/sepsis_1000_raw_20261106_141553_223997_UTC \
    sepsis_1000_raw.csv \
  --experiment \
    output/sepsis2019/phase4_dev/selected_dataset_20261106_141939_583158_UTC \
    output/sepsis2019/phase3_feature_selection/sepsis_1000_raw_20261105_140050_771243_UTC/FS_95_clinical_review/selected_dataset.csv \
  --full-reference sepsis_1000_raw.csv \
  --distance-samples 200 \
  --seed 42 \
  --output-dir output/sepsis2019/phase5_dev
```

Use `--experiment PHASE4_OUTPUT_FOLDER INPUT_CSV` again for additional runs or use it once for only the original dataset. The source CSV **must** be the identical file used for that Phase 4 run, as verified against the SHA-256 in its `phase4_metadata.json`. Each Phase 4 payload needs its adjacent `.npz.sha256` file. If any source or payload hash does not match, the evaluation **fails**.

No new reconstructed CSVs are written. Numeric reconstruction is performed in memory using the decoder transmitted with each Phase 4 payload.

## Results

Each run creates a timestamped Phase 5 directory containing:

1. `phase5_utility_summary.csv`: one row for each PCA/AE configuration and each verified lossless baseline. Reports R²-like retained variation, normalized observed-value RMSE, pairwise-distance correlations, checksum status, payload bytes and interpretability tag.
2. `phase5_per_feature_utility.csv`: error (MAE, RMSE, normalized RMSE and R²) **on originally observed measurements only**, and original-versus-reconstructed mean, median and standard deviation.
3. `phase5_feature_retention.csv`: original numeric variables retained/removed by Phase 3, hourly observation counts and patient coverage in the unfiltered reference. Dropped variables **cannot** be reconstructed.
4. `phase5_sampled_patient_rows.csv`: auditable row/patient sample for distance analysis, one row per sampled patient.
5. `phase5_metadata.json`: study definitions, caveats and parameters.

## Mathematical definitions and interpretation

**Observed-value reconstruction RMSE** excludes the cells that were missing in the input. The script also computes normalized RMSE after dividing each variable's residuals by its **observed** standard deviation.

**Retained observed variation (R²-like proxy)**:

\[R^2_{\mathrm{obs}} = 1 - \frac{\sum_j\sum_{i\in O_j} ((x_{ij}-\hat x_{ij})/s_j)^2}{\sum_j\sum_{i\in O_j} ((x_{ij}-\bar x_j)/s_j)^2}.\]

Here, \(O_j\) are originally observed entries in variable \(j\), and \(s_j\) is the observed standard deviation. Features with zero observed variance do not contribute to this normalized score. This value **can be negative**; negative means worse than reconstructing the observed feature means. It is a descriptive reconstruction score, **not** a measured downstream clinical-task outcome.

**PCA's intrinsic explained-variance ratio**, when available from Phase 4, is reported separately. It is based on PCA's trained standardized, median-imputed matrix. **Do not equate** that quantity with the R²-like observed-value score, and do not label an autoencoder score as PCA explained variance.

**Pairwise-distance preservation:** select up to 200 patients, choose one observation row randomly from each with fixed seed, compute Euclidean pairwise distances after applying the **same Phase 4 median-imputation and scaling parameters** to (a) original and (b) reconstructed clinical observations. Report Pearson and Spearman correlation between these two distance vectors. A second, **descriptive-only** result compares original distances to latent \(Z\) distances. Since PCA and autoencoders use different latent coordinate scales, do not interpret differences in this latent distance metric as definitive superiority. These metrics are proxies for geometry preservation, not a formal validation of cohort matching or clustering quality.

**Clinical interpretation:** `interpretability` is an explicitly qualitative tag; it is **not** a validated mathematical score. Phase 4's clinical-range flags are carried forward where available. Values outside these broad screening limits are **flags**, not proof of clinical invalidity; passing them is not proof of safety.

**Feature selection:** when `--full-reference` is supplied, report both how many original numeric variables are retained and how many originally observed measurements belong to retained variables. This does **not** claim all lost variables were unimportant. The total R²/RMSE computed on the selected dataset **does not measure loss from variables that were deleted**. Compare shared clinical variables per-feature when comparing original versus feature-selected pipelines.

**Lossless packaging:** Phase 4 has already verified gzip/zstd round trips byte-for-byte and Parquet's column/value/missingness/order equality. Phase 5 verifies the actual lossless files and sidecars are unchanged from those reports. Lossless utility is recorded as exact **within the columns that were transferred**, not as recovery of variables excluded in Phase 3.

## References for methodology

- Pikoula et al. (2023), *Evaluation of data processing pipelines on real-world electronic health records data for the purpose of measuring patient similarity*. PLOS ONE. https://doi.org/10.1371/journal.pone.0287264 — uses PCA and autoencoders for clinical patient representations and pairwise similarity.
- Jolliffe & Cadima (2016), *Principal component analysis: a review and recent developments*. Philosophical Transactions of the Royal Society A. https://doi.org/10.1098/rsta.2015.0202 — classical PCA and the variance principle.
- Hinton & Salakhutdinov (2006), *Reducing the dimensionality of data with neural networks*. Science. https://doi.org/10.1126/science.1127647 — bottleneck autoencoder dimensionality reduction.
- Scikit-learn documentation: [PCA explained variance](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.PCA.html) and [explained variance versus R²](https://scikit-learn.org/stable/modules/model_evaluation.html) — definitions and distinction between reconstruction measures.

## Verification performed before handoff

The script was checked with Phase 4-generated payloads for 1,200 real clinical-data rows, using PCA and autoencoders at k=2, on both the original and a Phase 3-selected subset. It correctly recovered the existing Phase 4 normalized RMSE values, computed distance correlations, and identified features lost through selection. It rejected a missing checksum and a deliberately corrupted payload. The short autoencoder training in this test was for **integration QA only**, not a thesis result. The full 20,336-patient run has not been performed here.

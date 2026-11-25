# Phase 4 — PCA versus nonlinear autoencoder (clinical data transfer)

## Scope and scientific justification

Use just two dimensionality-reduction algorithms: **principal component analysis (PCA)** and a **nonlinear autoencoder (AE)**. FIDDLE and the optional privacy-oriented independently fitted receiver model are **not** in this script. Phase 3 feature selection stays separate; no patient training/validation/test split is performed, because the present objective is transfer-size and same-cohort reconstruction, **not prediction or generalisation to unseen patients**.

Applied literature, in addition to the foundational mathematics:

1. **Pikoula, M., Kallis, C., Madjiheurem, S., Quint, J. K., Bafadhel, M., & Denaxas, S. (2023).** *Evaluation of data processing pipelines on real-world electronic health records data for the purpose of measuring patient similarity.* PLOS ONE, 18(6), e0287264. DOI: **10.1371/journal.pone.0287264**. Tested PCA-containing pipelines and autoencoders on **30,961 patients** with clinical EHR data. The downstream application was patient similarity, not network transfer; its results reinforce that representation choice is dataset-dependent.
2. **Peralta, M., Jannin, P., Haegelen, C., & Baxter, J. S. H. (2021).** *Data imputation and compression for Parkinson's disease clinical questionnaires.* Artificial Intelligence in Medicine, 114, 102051. DOI: **10.1016/j.artmed.2021.102051**. Evaluated nonlinear AE compression and imputation on clinical questionnaire data, compared with linear alternatives. This paper uses a more specialized residual AE than the present simple MLP architecture.
3. **Landi, I., et al. (2020).** *Deep representation learning of electronic health records to unlock patient stratification at scale.* npj Digital Medicine, 3, 96. DOI: **10.1038/s41746-020-0301-z**. Demonstrates AE-related representation learning using EHR data for **1,608,741 patients** and **57,464 clinical concepts**. Its ConvAE is not the simple feed-forward AE implemented here.
4. **Li, D., et al. (2025).** *Autoencoder-Based Representation Learning for Similar Patients Retrieval From Electronic Health Records: Comparative Study.* JMIR Medical Informatics, 13, e68830. DOI: **10.2196/68830**. Compared AE variants with PCA-transformed data as a reference on two EHR cohorts of **13,752** and **9,568** patients. Downstream goal was similarity retrieval, not transfer.

These studies establish that PCA and AE are applicable to **real clinical data** and justify a controlled linear/nonlinear comparison. They **do not establish** that AE always wins or that either method outperforms lossless compression for hospital-to-university transfer; that is what this thesis tests.

## Setup

```bash
python -m pip install numpy pandas scipy scikit-learn
```

Place `04_dimensionality_reduction.py` in your thesis code directory, replacing your earlier FIDDLE-enabled Phase 4 script (keep a backup if desired).

## Development run on raw 1,000-patient data

```bash
python 04_dimensionality_reduction.py \
  sepsis_1000_raw.csv \
  --methods pca autoencoder \
  --k 2 4 8 \
  --ae-hidden 32 \
  --ae-max-iter 80 \
  --output-dir output/sepsis2019/phase4_dev
```

**80 autoencoder iterations is a development setting only**. Check the `autoencoder_convergence_warning` and `autoencoder_training_loss` columns. Increase the iteration budget for final results if required; compare multiple random seeds separately if AE variability is material.

## Compare the same methods on a Phase 3 feature set

```bash
python 04_dimensionality_reduction.py \
  path/to/FS_95_clinical_review/selected_dataset.csv \
  --methods pca autoencoder \
  --k 2 4 8 \
  --ae-max-iter 300 \
  --output-dir output/sepsis2019/phase4_fs95c
```

You can repeat with the chosen FS-90/FS-95 configuration. For a fair PCA-versus-AE comparison, hold the **input feature set, k, scaling, and packaging method constant**.

For the full Set A after development, supply `sepsis_20336_raw.csv` or the Phase 3 selected dataset with the same CLI settings. Check available memory and execution times before starting many AE runs.

## Receiver-side reconstruction

Each `*_transfer_payload.npz` contains low-dimensional coordinates, decoder parameters, missingness mask, preserved fields, and a manifest. No separate model fitting occurs at the receiver.

```bash
python 04_dimensionality_reduction.py \
  --reconstruct-bundle path/to/pca_k4_transfer_payload.npz \
  --reconstructed-output output/received_pca_k4.csv
```

Optional `--expected-sha256 HEX` validates that the received payload has the expected checksum.

## Result files

A single timestamped directory contains:

- `phase4_comparison.csv`: actual payload bytes, original CSV bytes, gzip-6 bytes, size changes, model fitting/encoding/packaging times, model convergence diagnostics, reconstructed-data RMSE/MAE, and **simulated** transmission time.
- `phase4_per_feature_reconstruction.csv`: per-measurement error on observed cells.
- `phase4_metadata.json`: input checksum, configuration, environment, and method notes.
- `source_csv_gzip6.csv.gz`: lossless baseline.
- `pca_k*_transfer_payload.npz` and `autoencoder_k*_transfer_payload.npz`: portable files to send and reconstruct.

## Methodological cautions for the thesis

1. **FIDDLE is excluded.** These methods reduce numerical features directly. They currently encode **each hourly row independently**, not whole longitudinal patient sequences.
2. **No prediction and no patient splits.** The reported reconstruction errors describe the supplied data, not model generalisation to new patients.
3. The present code uses **median imputation for fitting** and preserves original missingness locations with a bitmask. Imputed values are not substituted for genuinely missing values in the reconstructed clinical table.
4. Identifiers, observation times, `SepsisLabel`, `Gender`, `Unit1`, and `Unit2` are retained losslessly. The measured numerical features are **lossy**. The dataset is not de-identified or made private by PCA/AE.
5. **Model and metadata costs are included** in the actual `payload_bytes` file size. Sending only `Z` without decoder and masks is not a fair hospital-to-university comparison.
6. **Do not compare reconstruction errors across different Phase 3 feature sets as if they have identical target variables.** The metric only measures variables retained by that input. Removed Phase 3 columns are gone and have to be separately accounted for when assessing utility.
7. `transmission_seconds_SIMULATED` assumes a fixed bit rate and excludes SSH/protocol/network latency. Run the real Phase 2 transfer benchmark on the artifacts for measured transfer times.
8. A 40-predictor sepsis dataset is not inherently high-dimensional per record even if the whole file has hundreds of thousands of rows. This is an empirical evaluation of two applicable algorithms, not a claim that advanced nonlinear compression is needed or must win.
9. `end_to_end_seconds_SIMULATED` includes input loading, preprocessing, fitting, encoding, packaging, idealized transmission, receiver loading and reconstruction. Reconstruction **metric calculation** is separately reported and excluded.

## Interpretation

Compare PCA versus AE on equal `k` and identical input. Report the trade-off between **actual payload size (relative to gzip)**, **end-to-end time**, and **reconstruction error**. Treat neither as an automatic winner. If gzip is smaller/faster and lossless, that is an important negative finding, not an experiment failure.

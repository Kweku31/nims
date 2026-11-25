# Phase 4: PCA, Autoencoder and Lossless Transfer Baselines

**Revision:** 6 November 2026. This guide accompanies `04_dimensionality_reduction.py`.

## 1. Experimental scope

The research compares **two dimensionality-reduction methods** (PCA and a nonlinear autoencoder) and **three conventional lossless packaging strategies** (gzip-6 CSV, Zstandard-3 CSV and Parquet with Zstandard compression).

FIDDLE has been excluded from the main pipeline. No patient prediction, train/validation/test splitting, or independently trained receiver is used. The same observed rows are provided to both dimensionality-reduction algorithms. All numeric reconstruction metrics are calculated only at originally observed positions. Missingness and protected structural variables are preserved exactly.

## 2. Scientific basis and limitations

* **Pikoula et al. (2023).** *Evaluation of data processing pipelines on real-world electronic health records data for the purpose of measuring patient similarity.* PLOS ONE 18(6):e0287264, doi:10.1371/journal.pone.0287264. Compared PCA and autoencoder pipelines using a clinical EHR cohort. This supports method selection but does not establish their effectiveness for network transfer.
* **Peralta et al. (2021).** *Data imputation and compression for Parkinson's disease clinical questionnaires.* Artificial Intelligence in Medicine 114:102051, doi:10.1016/j.artmed.2021.102051. Demonstrates nonlinear autoencoder-based compression of clinical questionnaire data and highlights missingness-sensitive evaluation. Its architecture and dataset differ from this implementation.
* **Li et al. (2025).** *Autoencoder-Based Representation Learning for Similar Patients Retrieval From Electronic Health Records: Comparative Study.* JMIR Medical Informatics 13:e68830, doi:10.2196/68830. Supports AE hyperparameter monitoring; does not establish an optimal architecture for our sepsis dataset.
* **Kryukov et al. (2020).** *Sequence Compression Benchmark (SCB) database—A comprehensive evaluation of reference-free compressors for FASTA-formatted sequences.* GigaScience 9(7):giaa072, doi:10.1093/gigascience/giaa072. Supports measuring compressed size, compression and decompression time, transfer-related costs and lossless round-trip integrity. It concerns genomic sequence files, not EHR tables.
* **Apache Parquet format**: https://parquet.apache.org/docs/file-format/data-pages/compression/ — columnar storage supports multiple compression codecs including Zstandard.
* **Zstandard**: https://github.com/facebook/zstd — lossless compression with configurable speed/ratio trade-offs.
* **Maleczek et al. (2024).** *A Comparison of Five Algorithmic Methods and Machine Learning Pattern Recognition for Artifact Detection in Electronic Records of Five Different Vital Signs: A Retrospective Analysis* (Anesthesiology, 2024), doi:10.1097/ALN.0000000000004971. Used screening intervals for selected vital signs (HR 5–300/min, temperature 25–45 C, SBP 20–300 mmHg, MAP 10–250 mmHg, DBP 5–225 mmHg, SpO2 0–100%). The script uses them solely as *screening flags*; not as universal clinical validity rules. SaO2 0–100% reflects percent saturation definition.

**Do not claim** that the sources establish optimal latent dimension k, a clinical error tolerance, or that PCA or autoencoders necessarily outperform lossless packaging on these records. The experiment tests those assumptions.

## 3. Environment

```bash
# In the existing thesis virtual environment:
pip install numpy pandas scipy scikit-learn pyarrow zstandard
# Or install Zstandard executable instead of Python zstandard package:
# sudo apt install zstd
```

`pyarrow` enables the Parquet baseline. If an optional codec is unavailable, the program identifies it explicitly as `unavailable_or_failed`, and **does not** invent its size or timing. For full benchmark runs, use `--strict-lossless` to require all requested lossless codecs.

## 4. Development example: original dataset

```bash
python 04_dimensionality_reduction.py \
    sepsis_1000_raw.csv \
    --methods pca autoencoder \
    --k 2 4 8 \
    --ae-max-iter 300 \
    --ae-patience 20 \
    --lossless-formats gzip zstd parquet \
    --strict-lossless \
    --output-dir output/sepsis2019/phase4_dev
```

If `pyarrow` is not installed, the command will **fail** with `--strict-lossless`. Install the package or temporarily omit `--strict-lossless`, clearly marking Parquet as unavailable.

With `--write-reconstructed`, reconstructed clinical CSVs are saved for visual inspection; without it, the script still reconstructs, checks and assesses every payload in memory.

## 5. Compare with a Phase 3 feature-selected dataset

```bash
python 04_dimensionality_reduction.py \
    sepsis_1000_raw.csv \
    --compare-with output/sepsis2019/phase3_dev/EXPERIMENT_DIR/selected_dataset.csv \
    --methods pca autoencoder \
    --k 2 4 8 \
    --ae-max-iter 300 \
    --lossless-formats gzip zstd parquet \
    --strict-lossless \
    --output-dir output/sepsis2019/phase4_comparison
```

Replace `EXPERIMENT_DIR` with the actual Phase 3 variant directory (e.g., FS-95 clinical review). Both inputs are processed with identical hyperparameters. A single `phase4_across_datasets_<UTC timestamp>.csv` is produced in the output root. **Interpretation warning:** reconstruction RMSE is computed over the columns that each input contains, so RMSE from a raw 40-predictor input is not directly comparable to RMSE from a selected 33-predictor input. The selected dataset cannot recover Phase 3-deleted variables.

## 6. Main report files (per input)

* `phase4_lossless_baselines.csv`: gzip/zstd/parquet verification status, actual on-disk bytes + checksum bytes, compression time, checksum verification, read/decompression time and idealized transfer time.
* `phase4_comparison.csv`: PCA / autoencoder size, k, RMSE, MAE, time, clinical plausibility flags, autoencoder optimizer diagnostics, best lossless reference.
* `phase4_per_feature_reconstruction.csv`: per-feature MAE, RMSE, normalized RMSE by observed standard deviation, original and reconstructed out-of-range counts, and *new* violations introduced by reconstruction.
* `phase4_autoencoder_loss_curve.csv`: per-iteration autoencoder training loss, so convergence behavior is auditable.
* `phase4_metadata.json`: source hash, preserved columns, parameters, dependency context and lossless baseline details.
* `*_transfer_payload.npz` and accompanying `*.npz.sha256`: decoder, latent data, masks, exact preserved columns and checksum.

### Metric interpretation

* Lower normalized RMSE is better, but no single threshold guarantees clinically acceptable reconstructed values.
* Plausibility flags are counted only at originally observed positions. Counts of *new* violations exclude positions that were already out-of-range in the original data. No reconstructed values are clipped.
* An autoencoder `autoencoder_convergence_warning=True` means iteration-limited training did **not** satisfy the optimizer stopping criterion. Increasing `--ae-max-iter` and checking the loss curve is necessary; stopping by tolerance also does not prove global optimality.
* The program gives only **idealized bitrate times** (`--bandwidth-mbps`). Real hospital-to-university SCP times must come from the separate transfer benchmark.
* For lossless gzip and Zstandard CSV, the decompressed CSV **must match the original SHA-256**. Parquet represents the same clinical table (same order, values, missingness and columns), but not necessarily the exact original CSV bytes.
* Every serialized artifact has a `.sha256` sidecar. The receiver refuses to reconstruct a missing, corrupted or unverified payload. SHA-256 detects corruption but does not authenticate the sender unless the checksum is conveyed over a trusted/authenticated channel.
* `input_csv_bytes` and output bytes must be compared using the same input data and without omitting the transmitted decoder, preserved fields, masks or manifest.

## 7. Test the university receiver locally

```bash
python 04_dimensionality_reduction.py \
    --reconstruct-bundle /path/to/pca_k4_transfer_payload.npz \
    --reconstructed-output reconstructed_pca_k4.csv
```

The neighboring `pca_k4_transfer_payload.npz.sha256` file is **mandatory**. The university does not fit an independent model.

## 8. Recommended experimental reporting

Run the exact same input and parameters for PCA and AE; repeat timing-sensitive work as appropriate (Kryukov et al.'s 10-run rule is one possible benchmark precedent, not a universal statistical requirement); report machine, versions, k, training settings and available codecs. Preserve unmodified source files and label any small-sample smoke-test results as software validation, not final thesis results.

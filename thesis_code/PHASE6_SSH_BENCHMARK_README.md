> **v7 SSH recovery update:** See [README_SSH_RECOVERY.md](README_SSH_RECOVERY.md) for retries, timeouts, verified destination directories, resume, timing definitions and thesis methodology wording. It supersedes older flat-destination/failure behaviour described below.

# Phase 6 SSH transfer benchmark — use with the November 12 corrected Phase 4 runs

This workflow **does not retrain** PCA or autoencoders. It packages their existing Phase 4 outputs and transfers complete TAR archives plus SHA-256 sidecars to the university server using the existing `06_transfer_package.py`.

## Files

- `06_run_phase6_ssh_benchmarks.sh` — builds and sends complete lossless, PCA and autoencoder packages for the original and/or FS-95-C datasets.
- `06_phase6_ssh_summary.py` — merges package reports with real SSH trial measurements.

Place both beside `06_transfer_package.py` in the `thesis_code` directory. The shell script is configured for the corrected **November 12, 2026** Phase 4 output folders. Update the paths at the top if you rerun Phase 4.

## 1. Verify SSH authentication first

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes researcher@server.example.org 'echo OK'
ssh researcher@server.example.org 'mkdir -p /tmp/thesis_transfer/phase6 && chmod 700 /tmp/thesis_transfer/phase6'
```

The `send` command requires key-based or other noninteractive SSH authentication; it does not prompt for a password.

## 2. Run the experiment

```bash
# All 18 primary strategies: (gzip, zstd, parquet, PCA k=2,4,8, AE k=2,4,8) x (original, FS-95-C)
REMOTE=researcher@server.example.org TRIALS=10 DATASETS=both CODECS=native bash 06_run_phase6_ssh_benchmarks.sh

# Smaller initial smoke test on original dataset, with 3 repetitions each
REMOTE=researcher@server.example.org TRIALS=3 DATASETS=original CODECS=native bash 06_run_phase6_ssh_benchmarks.sh

# Optional: full codec sensitivity for the same PCA/AE representations
REMOTE=researcher@server.example.org TRIALS=10 DATASETS=both CODECS=all bash 06_run_phase6_ssh_benchmarks.sh
```

Set REMOTE to your SSH account and hostname. The default remote directory is /tmp/thesis_transfer/phase6. Set REMOTE_DIR to choose another directory.

`CODECS=native` compares DEFLATE NPZ against the lossless baselines. `CODECS=all` additionally packages **uncompressed NPZ contents** with gzip and Zstandard, so the codec comparison does not just double-compress an already compressed payload.

Generated reports are in a unique timestamped `output/sepsis2019/phase6_ssh_..._UTC/` directory, including:

- `*.package_report.json`: packaging time and bytes for entire TAR+checksum.
- `*.transfer_trials.csv`: individual real SCP and remote SHA-256 timings.
- `phase6_ssh_comparison.csv`: descriptive package-level comparison.
- `phase6_all_ssh_trials.csv`: concatenated trial-level data.

## 3. Prove receiver-side recovery for PCA and autoencoder

To verify *the actual university-side environment*, install compatible Python dependencies on the university server and copy the Phase 4/6 programs **once** (not per dataset):

```bash
scp 06_transfer_package.py 04_dimensionality_reduction_updated.py \
  researcher@server.example.org:/tmp/thesis_transfer/phase6/
```

For example, after sending a PCA k=2 TAR archive (replace `PACKAGE_ID` with its actual filename):

```bash
ssh researcher@server.example.org
cd /tmp/thesis_transfer/phase6
python 06_transfer_package.py verify PACKAGE_ID.tar
/usr/bin/time -f 'unpack_and_npz_recovery_seconds=%e' \
  python 06_transfer_package.py unpack PACKAGE_ID.tar \
  --output-dir received --recover-npz
/usr/bin/time -f 'clinical_reconstruction_seconds=%e' \
  python 04_dimensionality_reduction_updated.py \
  --reconstruct-bundle received/PACKAGE_ID_recovered/pca_k2_transfer_payload.npz \
  --reconstructed-output received/PACKAGE_ID_pca_k2_reconstructed.csv
```

Repeat this one-time recovery test with `autoencoder_k2_transfer_payload.npz`. Choose a new output directory for each repeat: `unpack` intentionally refuses to overwrite an existing verified directory. Full clinical-data ingestion into Project 4 remains out of scope.

`send` **only** times SCP and remote archive SHA-256, not unpacking or reconstruction. To claim complete delivery time, add receiver recovery measurements and distinguish one-time fitting from recurring transfer costs.

## 4. Interpretation

Use total transmitted bytes, mean/variation of real SCP time, SHA verification and receiver recovery time. Compare like-for-like complete packages. Parquet is lossless for its **input**; FS-95-C Parquet does not restore variables removed in Phase 3. PCA/AE bundles preserve nine fields exactly, but reconstruct other measurements approximately. Do not claim clinical utility from small file size alone; use the corrected Phase 5 reports.

For scientific reporting, note that the 1,000-patient dataset produces sub-megabyte and megabyte-scale files, where SSH setup/network jitter can dominate timings. Repeat on Training Set A (20,336 patients), report trial dispersion and consider repeating/alternating methods across similar network conditions. Do not claim significance from small mean differences without uncertainty analysis.

Security: transfer only authorized/de-identified data. SHA-256 is an integrity check, not an authentication system; the SSH host key and account must be trusted. `/tmp` is used here as the established **benchmark** destination, not as a recommended persistent clinical storage location.

## Aligned repetition policy (2026-11-18)

Phase 6 now follows Phase 2: the first successful SCP duration at most 10 seconds triggers up to 10 total trials; above 10 seconds ends after one. `TRIALS` is a maximum, not a fixed count. `REPEAT_THRESHOLD_SECONDS` defaults to 10. Verification and retry overhead do not control the cutoff. Each package decides independently. Trial CSVs preserve the maximum, required count and first-transfer time; the summary rejects incomplete or inconsistent adaptive reports. Existing explicit overrides such as `REMOTE=researcher@server.example.org TRIALS=3` remain overrides.

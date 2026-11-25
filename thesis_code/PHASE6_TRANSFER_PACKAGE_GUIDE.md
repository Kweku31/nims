> **v7 SSH recovery update:** See [README_SSH_RECOVERY.md](README_SSH_RECOVERY.md) for retries, timeouts, verified destination directories, resume, timing definitions and thesis methodology wording. It supersedes older flat-destination/failure behaviour described below.

# Phase 6 — Transfer Package Design and Verification

**Script:** `06_transfer_package.py`  
**Scope:** Package, document, checksum, transfer and verify existing Phase 4 outputs for university/Project 4 handoff. **This thesis does not implement Project 4's ingestion pipeline.** No PCA/autoencoder fitting or clinical utility evaluation is repeated here.

## 1. Purpose and sequence

Phase 2 benchmarked **lossless methods**; Phase 3 selected columns; Phase 4 produced **lossless baselines and PCA/autoencoder transfer payloads**; Phase 5 assessed research utility. Phase 6 packages the existing artifacts so the destination can receive and verify them reliably.

Unlike the minimal original sample, the revised script **does not turn the PCA or autoencoder output into an ordinary CSV**. That would discard the actual reduced representation and may omit the decoder. It wraps the existing `.npz` containing `Z`, trained decoder parameters, scaler, missingness mask, exact passthrough columns, and internal manifest. A university can later reconstruct with the existing Phase 4 receiver; no model retraining is required.

The manifest JSON includes the sample's required fields: schema version, data dictionary, transformation log, compression method, per-file SHA-256 checksums and dependency versions. It additionally identifies the original/selected data source, exact decoder requirements, Phase 3 removal information when available, and all companion files.

## 2. Install

```bash
# In the thesis Python virtual environment
pip install numpy pandas scipy scikit-learn
pip install pyarrow zstandard  # required for Parquet and Python Zstandard support
# Alternatively, an installed zstd CLI works for Zstandard:
# sudo apt install zstd

python 06_transfer_package.py --help
python 06_transfer_package.py build --help
```

Use only real de-identified, authorized clinical datasets. A SHA-256 checksum does not de-identify, encrypt or authenticate a dataset by itself.

## 3. Create packages from your actual Phase 4 experiments

Run from the `thesis_code` directory. The paths below match your reported 1,000-patient development runs. The Phase 4 run folder **must** contain `phase4_metadata.json`, the selected payload, and its `.sha256` sidecar.

### A. Lossless Parquet, original dataset

```bash
python 06_transfer_package.py build \
  --phase4-run output/sepsis2019/phase4_dev/sepsis_1000_raw_20261106_141553_223997_UTC \
  --source-csv sepsis_1000_raw.csv \
  --method parquet \
  --output-dir output/sepsis2019/phase6_dev
```

Replace `parquet` with `gzip` or `zstd` to package another already-verified Phase 4 lossless baseline. These are not additional dimensionality-reduction algorithms.

### B. PCA with the existing NPZ/DEFLATE compression

```bash
python 06_transfer_package.py build \
  --phase4-run output/sepsis2019/phase4_dev/sepsis_1000_raw_20261106_141553_223997_UTC \
  --source-csv sepsis_1000_raw.csv \
  --method pca --k 2 --codec native \
  --output-dir output/sepsis2019/phase6_dev
```

### C. Autoencoder plus Zstandard on the *uncompressed NPZ member contents*

```bash
python 06_transfer_package.py build \
  --phase4-run output/sepsis2019/phase4_dev/sepsis_1000_raw_20261106_141553_223997_UTC \
  --source-csv sepsis_1000_raw.csv \
  --method autoencoder --k 2 --codec zstd \
  --output-dir output/sepsis2019/phase6_dev
```

`--codec native` copies the existing compressed `.npz`. `--codec gzip` or `--codec zstd` first reproduces **the same NPZ array members in a ZIP_STORED (uncompressed) container** and then applies gzip-6 or Zstandard-3. It verifies that every `.npy` member has exactly the same SHA-256 digest as the Phase 4 source. This permits a more meaningful compression comparison than gzip-on-an-already-DEFLATE-compressed NPZ.

The codecs **never improve PCA/autoencoder reconstruction fidelity**: they are lossless wrappers around the same lossy representation.

### D. Clinically reviewed Phase 3 selection + Phase 4 AE

```bash
python 06_transfer_package.py build \
  --phase4-run output/sepsis2019/phase4_dev/selected_dataset_20261106_141939_583158_UTC \
  --source-csv output/sepsis2019/phase3_feature_selection/sepsis_1000_raw_20261105_140050_771243_UTC/FS_95_clinical_review/selected_dataset.csv \
  --full-reference-csv sepsis_1000_raw.csv \
  --feature-selection-label FS-95-C \
  --method autoencoder --k 4 --codec native \
  --output-dir output/sepsis2019/phase6_dev
```

**Important:** If you have Phase 3 metadata for this *exact selected dataset*, add `--phase3-metadata /path/to/corresponding_metadata.json`. The script checks its source/selection hashes and incorporates documented parameters. Do **not** attach Phase 3 metadata from another threshold or run. Without that file it documents the user-provided selection label and the removed-column audit, but cannot invent missingness thresholds or the clinical-review rule.

You can also attach research reports using e.g.

```bash
--extra phase5_utility_summary.csv=/absolute/path/to/phase5_utility_summary.csv
```

If you have authoritative clinical units/descriptions, supply `--dictionary-json /path/to/clinical_dictionary.json`. Format:

```json
{
  "HR":  {"unit": "beats/min", "description": "Heart rate"},
  "SBP": {"unit": "mmHg", "description": "Systolic blood pressure"}
}
```

Unprovided unit descriptions remain `null`, rather than being guessed. The Python dtype field is **inferred from up to the first 10,000 source rows**; it is useful documentation, not a clinical schema-validation guarantee.

## 4. Output structure and what is actually transmitted

Each `build` command creates a separate timestamped directory, an uncompressed TAR archive and a mandatory TAR checksum file:

```text
output/sepsis2019/phase6_dev/
  sepsis_1000_raw_pca_k2_native_YYYYMMDD_..._UTC/
    manifest.json
    manifest.json.sha256
    data/
      pca_k2_transfer_payload.npz
      pca_k2_transfer_payload.npz.sha256
  sepsis_1000_raw_pca_k2_native_YYYYMMDD_..._UTC.tar
  sepsis_1000_raw_pca_k2_native_YYYYMMDD_..._UTC.tar.sha256
  sepsis_1000_raw_pca_k2_native_YYYYMMDD_..._UTC.package_report.json
```

Only the `.tar` **and its matching** `.tar.sha256` must travel. The `.package_report.json` is a local benchmarking record; it is not required by the receiver. The original CSV is **not** automatically included in the package, because sending it would eliminate the intended compression benefit.

The reported **total transmitted bytes** include the entire TAR archive **plus its sidecar**, including manifest, decoder and other metadata. TAR itself is **not** separately compressed, to avoid disguising codec differences. Small files may incur significant fixed TAR/manifest overhead; report the full package size, not just `.npz` bytes.

## 5. Verify and recover on the university side

After securely obtaining an archive and its `.tar.sha256`:

```bash
python 06_transfer_package.py verify /path/to/package.tar
python 06_transfer_package.py unpack /path/to/package.tar \
  --output-dir /path/to/unpacked \
  --recover-npz
```

For PCA/autoencoder packages, `--recover-npz` recreates an NPZ and **generates a new `.npz.sha256`** corresponding to the actual recovered NPZ bytes. This ensures it remains compatible with the mandatory checksum check in Phase 4. In the case of a gzip/zstd wrapper, the recovered NPZ may not be byte-for-byte identical to the original DEFLATE NPZ container, but **all internal `.npy` members are unchanged**.

To test the existing Phase 4 reconstruction on the recovered NPZ:

```bash
python 04_dimensionality_reduction_updated.py \
  --reconstruct-bundle /path/to/unpacked/PACKAGE_ID_recovered/pca_k2_transfer_payload.npz \
  --reconstructed-output /path/to/reconstructed_pca_k2.csv
```

The receiver's actual clinical ingestion into Project 4 is **not part of this thesis**. The `verify`/`unpack` tools check integrity and recover a consumable artifact; they are not a production hospital data ingestion service.

## 6. Real network transfer and scheduling

Configure SSH keys, access permissions, and a trusted host key. Example using an already-generated archive:

```bash
python 06_transfer_package.py send \
  output/sepsis2019/phase6_dev/PACKAGE_ID.tar \
  --remote user@university.example.edu \
  --remote-dir /home/user/clinical_transfer/incoming \
  --trials 10 --repeat-threshold-seconds 10
```

The command uses SCP for the archive and checksum, executes `sha256sum --check --strict` **on the remote server via SSH** after each transfer, and creates a `*.transfer_trials.csv` report with actual SCP wall-clock time, remote verification time and total transmitted bytes. Remote directory must be an existing or creatable **absolute POSIX path without spaces**. It never auto-starts Project 4 ingestion.

For a scheduled transfer, call the same `send` command from a cron job or systemd timer. For example, a cron entry that re-sends one **already prepared** archive every Sunday at 02:00:

```cron
0 2 * * 0 /home/USER/thesis/bin/python /home/USER/thesis_code/06_transfer_package.py send /ABS/PATH/TO/PACKAGE_ID.tar --remote user@university.example.edu --remote-dir /home/user/clinical_transfer/incoming --trials 1 >> /home/USER/phase6_schedule.log 2>&1
```

**Do not use a fixed archive path for a changing weekly data export.** A separately controlled source-export process must build a new Phase 4 artifact and Phase 6 package before each new scheduled delivery. This script does not fabricate future clinical exports.

## 7. Benchmark reporting

Keep Phase 6 package generation and actual network-transfer timing separate from Phase 4 model training and Phase 5 evaluation:

- `phase4_comparison.csv`: fitting/encoding and reconstruction costs from the chosen run.
- `*.package_report.json`: Phase 6 packaging time, source bytes, payload bytes, TAR bytes, and **total transmitted bytes**.
- `*.transfer_trials.csv`: observed repeated SCP and server checksum verification times.
- `phase5_utility_summary.csv`: clinical research-utility proxies and error measurements.

A conceptual total delivery time is

\[
T_\mathrm{delivery}=T_\mathrm{fit}+T_\mathrm{encode}+T_\mathrm{package}+T_\mathrm{network}+T_\mathrm{verify}+T_\mathrm{recover}.
\]

Report `T_fit` separately for models trained once and reused across repeated exports; do not count it once **per transfer** without specifying that scenario. The supplied `send` command measures **network transfer and remote SHA check**, not remote decompression, NPZ reconstruction or Project 4 ingestion. Never label `scp_seconds` alone as the full end-to-end delivery time.

Repeat trials under similar and documented network conditions. Note that these development files are only ~MB-scale; conclusions about large-scale transfer must await larger-cohort tests.

## 8. Guarantees and limitations

1. **Integrity:** rejects missing/mismatched Phase 4 payload sidecars, mismatched Phase 4 source CSV hashes, corrupted package archives, or invalid/extra internal files. The manifest also has a checksum. Checksums detect corruption but **do not authenticate an attacker-controlled manifest**; rely on authenticated SSH / trusted signatures for provenance.
2. **No invented clinical values:** exact passthrough and missingness are already encoded by Phase 4; PCA/autoencoder numerical reconstruction remains approximate. Lossless gzip/zstd is checked against original CSV bytes. Parquet is checked for exact DataFrame values/order/missingness if `pyarrow` is available.
3. **Feature selection:** columns removed in Phase 3 cannot be recovered, irrespective of lossless wrapping or checksum validation.
4. **Research utility:** the Phase 5 metrics evaluate the reconstruction; packaging itself does not improve research utility.
5. **Security/privacy:** package creation/SSH does not implement authorization policy, institutional clinical data governance, encryption at rest, or re-identification risk controls. Use de-identified/authorized data for testing.
6. **Interoperability:** the JSON manifest is *inspired by* inventory/checksum concepts in BagIt RFC 8493, **not** a fully BagIt-compliant bag. Versioned JSON metadata provides a documented Project 4 handoff contract; that project must implement its own ingestion/validation.

## 9. Software verification

Run the included synthetic unit tests without any clinical records or network connection:

```bash
python -m unittest -v test_06_transfer_package.py
```

Tests cover correct package construction, gzip byte-identical roundtrip, NPZ member preservation, receiver-side unpacking, source/Phase 3 hash mismatches, missing Phase 4 sidecars and tamper detection even when the outer archive checksum is rewritten. The revised Phase 6 script was also locally exercised with the available 39,031-row Phase 4 PCA/autoencoder payloads; an extracted Zstandard-wrapped autoencoder payload reconstructed an **identical DataFrame** to that from the original NPZ. A real remote SSH/SCP benchmark and the Parquet branch were **not tested in this environment** (no SSH destination or `pyarrow` here).

## 10. Supporting specifications and studies

- Kunze et al. (2018). **The BagIt File Packaging Format (V1.0)**, RFC 8493. https://www.rfc-editor.org/rfc/rfc8493.html. Establishes interoperable packaging principles: payload manifests and checksum verification; not a claim of BagIt compliance for this implementation.
- Apache Parquet documentation, **Compression**. https://parquet.apache.org/docs/file-format/data-pages/compression/. Details Parquet's page-level compression and supported codecs including Zstandard.
- NIST, **Secure Hash Standard (SHS)**, FIPS 180-4. https://csrc.nist.gov/pubs/fips/180-4/upd1/final. Formal standard for SHA-256 and related hashes.
- Kryukov et al. (2020), **Sequence Compression Benchmark (SCB) database**. https://doi.org/10.1093/gigascience/giaa072. Benchmark design precedent for payload size and computational costs, though applied to genomic sequences rather than clinical tables.

### Adaptive trial count (2026-11-18)

`send` defaults to a maximum of 10 trials and a 10-second first-SCP threshold, matching Phase 2. A first transfer above 10 seconds completes the benchmark after one verified trial; otherwise all 10 are required. Failure retries remain separate. The report records both `maximum_trials` and the policy-derived `requested_trials`, along with the first duration and cutoff. `--trials 1` still requests one verified transfer.

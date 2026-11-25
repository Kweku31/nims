# Thesis Phase 6 — reconstruction on the university server

This is a **drop-in source tree** based on the uploaded v7 thesis pipeline, with a new **opt-in server receiver**. The original Phase 4 PCA/autoencoder reconstruction mathematics and the original Phase 6 archive verification/unpack implementation are reused. No original clinical CSV needs to be copied to the server to reconstruct a PCA/AE package.

## What changed

- `thesis_pipeline/phase6.py`: local Phase 6 unpack/reconstruction remains for `--receiver-execution local`; `--receiver-execution remote` instead runs `receiver_reconstruct.py` over SSH **after the last checksum-verified SCP trial**.
- `receiver_reconstruct.py`: executes ON THE RECEIVING SERVER. It independently verifies archive, manifest and checksums; unpacks; reconstructs PCA/AE using the same Phase 4 decoder, or decompresses gzip/zstd / reads Parquet; checks expected row count; and writes `reconstructed.csv` and `receiver_report.json` into the server's verified transfer directory.
- `run_thesis.py`: adds receiver options and validation. Remote mode requires **strict SSH**; no simulation fallback is possible.
- `thesis_pipeline/decision.py`: labels the evidence as server-reconstruction-based, rather than calling it local recovery.
- `thesis_pipeline/core.py`: hashes the added receiver source as part of checkpoint provenance.

Other uploaded original scripts are included unchanged for easy installation. Existing Phase 5 local reconstruction for research-utility metrics remains unchanged; this change concerns the **actual Phase 6 receiving/delivery step**.

## 1. Install the same code on both computers

This archive is the project directory layout; **replace the previous unified project only after backing it up**.

On the sending machine (inside the supplied project directory):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install numpy pandas scipy scikit-learn pyarrow zstandard
```

On the university server, place the same `thesis_pipeline/` directory and `receiver_reconstruct.py` inside one directory, for example:

```text
/home/USER/thesis_receiver/
├── receiver_reconstruct.py
└── thesis_pipeline/
    ├── core.py
    ├── ssh_transport.py
    └── legacy/
        ├── 04_dimensionality_reduction_updated.py
        ├── 06_transfer_package.py
        ├── ae_runtime.py
        └── ...
```

Install the receiver-side dependencies in a server virtual environment:

```bash
cd /home/USER/thesis_receiver
python3 -m venv .venv
.venv/bin/pip install numpy pandas scipy scikit-learn pyarrow zstandard
```

**Important:** The sender and server should use compatible NumPy, pandas, and other decoder dependencies, and the same thesis decoder sources. Ensure the server has enough free storage, secure SSH keys, trusted host key, and permissions for the transfer destination. Reconstructed clinical data must be protected by the receiving institution's data-governance policy.

## 2. Run the full pipeline from the sender

Change `USER`, `SERVER`, input path, and receiver paths to your actual values:

```bash
python run_thesis.py \
  --dataset sepsis_1000_raw.csv \
  --output-dir thesis_runs \
  --transfer-mode ssh \
  --remote USER@SERVER \
  --remote-dir /tmp/thesis_transfer/phase6 \
  --receiver-execution remote \
  --remote-receiver-script /home/USER/thesis_receiver/receiver_reconstruct.py \
  --remote-python /home/USER/thesis_receiver/.venv/bin/python \
  --remote-reconstruction-timeout 900 \
  --transfer-trials 10
```

The receiver code is not automatically deployed: **it must be installed on the server first**. SSH runs it with the specified server-side Python executable. This run fails rather than pretending local or simulated recovery is a server measurement if SSH or receiver execution fails.

To retain the previous behavior for development tests, omit the new flags or use:

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv --transfer-mode simulated --receiver-execution local
```

If you use a JSON config instead of CLI flags, the new keys are `receiver_execution` (`local` or `remote`), `remote_receiver_script` (absolute server path), `remote_python`, and `remote_reconstruction_timeout` (seconds).

## 3. What runs where

**On sender:** Phase 4 fits PCA/AE, creates reduced payload including the *fitted* inverse decoder and missingness mask; Phase 6 builds/checksums the archive and SCP-transfers the fixed archive for adaptive benchmarking.

**On server:** SSH/SCP publishes a checksum-verified directory. The sender then runs `receiver_reconstruct.py` via SSH **once against the last successful transfer trial's copy**. The receiver verifies archive/member hashes again, recovers NPZ if needed, performs inverse PCA/AE or lossless decompression, verifies row count, and writes the output CSV.

**Measurements:** `unpack_seconds` and `reconstruct_or_decompress_seconds` represent **server** measurements only when `receiver_verification_location=remote_ssh`; `receiver_csv_write_seconds` separately measures writing the reconstructed table. All three contribute to the `end_to_end_seconds` additive proxy in remote mode. `receiver_report.json` on the server contains the detailed timings, output SHA-256, and output file path. The original data values never appear in the sender's remote status report.

For raw gzip and Zstandard CSV compression, the receiver streams the original CSV bytes without reserializing, and verifies the recovered bytes against the source CSV hash in the signed-by-transport manifest. PCA/AE reconstruction is **lossy**, and must not be described as byte-identical. Parquet is restored to a CSV representation of the same table, not necessarily byte-identical to the original CSV.

**Timing limitation:** Network SCP runs are repeated adaptively; remote unpack/reconstruction is measured **once per package, after the final successful trial**, not 10 times. The reported additive delivery time is a sum of stage timings, not a wall-clock observation from a synchronized timer. For a thesis claim about receiver-time variability, run additional repeated remote recovery experiments separately.

**Phase 5 still runs on the sender.** It reconstructs in memory to compute utility metrics against the original clinical values, which are available only on the sender. Do not confuse that evaluation with delivery-side server recovery.

## 4. Confirm what happened

From the sender, inspect:

```bash
cat thesis_runs/run_status.json
# Find latest consolidated integrated evidence under thesis_runs/results/
# Columns include receiver_verification_location, receiver_csv_write_seconds,
# remote_reconstructed_csv_path, and reconstruct_or_decompress_seconds.
```

On the server, find the verified trial's recovery output:

```bash
find /tmp/thesis_transfer/phase6 -name receiver_report.json -print
find /tmp/thesis_transfer/phase6 -name reconstructed.csv -print
```

Only expose server-side clinical outputs to authorized users. Prefer an institution-approved data directory rather than `/tmp/` for production retention.

## 5. Validation performed in the preparation environment

- Python compilation of the full modified tree: successful.
- Local smoke test of the receiver engine with a synthetic PCA package: passed.
- Local smoke test with a synthetic autoencoder package: passed.
- Local smoke test with a synthetic gzip package: passed, including byte-identical source SHA-256.
- Mocked SSH report / command invocation parsing in `phase6.py`: passed.
- **Actual SSH execution on a university server has not been tested**: university credentials, networking, server configuration, and time measurements are not accessible here.

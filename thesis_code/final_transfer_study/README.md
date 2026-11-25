# Reproducing the final SCP and rsync experiment

Run commands from the source or extracted publication ZIP root (the directory containing `final_transfer_study`). The release contains the sender, measurement and analysis code, a dependency list, and a copy of the recorded observations. The environment label in the tables identifies synthetic local rehearsals and real SSH measurements.

## Replay the published result

```bash
python3 final_transfer_study/study.py replay
```

With Python 3.12 on Linux, this reads `reference/observations.json`, verifies its SHA-256 digest and rebuilds `replayed_results/trials.csv` and `SUMMARY.md`. The runner checks both outputs byte for byte against the published digests. This command works without training libraries, patient data, SSH credentials or a university server. From a development checkout, supply `--reference PATH/TO/RUN/reference` to replay a particular run.

## Repeat the experiment

Use a Python 3.12 virtual environment on Linux. Install the recorded CPU dependencies with `python -m pip install -r final_transfer_study/requirements.txt`. The sender needs OpenSSH (SCP with SFTP support) and rsync on PATH. Local mode also needs OpenSSH sftp-server. In real mode provision a trusted SSH host key and noninteractive SSH access to a receiver with rsync, GNU sha256sum, mv and uptime. For the original AE backend install CuPy compatible with the installed NVIDIA driver and runtime. The recorded CUDA 11 setup used cupy-cuda11x 13.6.0.

Run all 32 scheduled deliveries on a synthetic cohort, on one machine:

```bash
python final_transfer_study/study.py run
```

Run the clinical experiment from the original patient files and an SSH receiver:

```bash
python final_transfer_study/study.py run --set-a /data/training_setA --remote researcher@university-host --remote-dir /data/thesis-transfer
```

Use the extracted Training Set A consisting of 20,336 patient PSV files. The runner consolidates them in sorted order and checks the resulting CSV against the Chapter 4 SHA-256 digest. Alternatively pass `--dataset /data/sepsis_20336_raw.csv` for an already consolidated CSV, or `--packages /data/chapter4-archives` for the three original archives and sidecars. Archive mode verifies both file digests against chapter4_inputs.json. Data source: [PhysioNet Challenge 2019, version 1.0.0](https://physionet.org/content/challenge-2019/1.0.0/).

CSV and PSV modes build the three packages using the original Phase 4 and Phase 6 programs. The AE uses k=16, seed 42, batch size 4,096, a 500-epoch cap, tolerance 0.0001 and patience 20. The default clinical backend is GPU. Explicitly select `--ae-backend cpu` to study a CPU configuration. The synthetic CPU rehearsal uses 8,192 rows, 24 predictors, seed 42 and three epochs. Timestamped packaging metadata and device arithmetic can change rebuilt archive hashes. Exact historical package identity requires archive mode.

## Protocol and outputs

One invocation runs four consecutive balanced blocks (eight deliveries per block). They sample one measurement window by default. To automate separated windows, pass `--block-gap-seconds 3600` before the first trial. The runner waits one hour from the previous block’s last recorded completion. The selected spacing and timestamps travel with the observations. Each block tests Parquet, gzip and AE-16 under clean transfer and AE-16 with a controlled first-attempt interruption. Transport order is balanced within each condition. The interruption point is measured on the sender's outgoing copy-protocol stream at half the archive size. It is recorded before SSH encryption. The endpoint is verified publication. The signed paired difference is rsync minus SCP in seconds. Failed, unknown and off-protocol outcomes are preserved. Only pairs with verified deliveries under their assigned conditions enter the timing comparison.

Each invocation creates its own timestamped directory under `output/final_transport`. The logs, `protocol.json`, trial records and summary remain there. Interruptions can be resumed with `python final_transfer_study/study.py all PATH/TO/RUN` after protocol creation. Uncertain trials keep their recorded status. The same command also finishes previously prepared four-session protocols on the original machine. The individual session command remains available for manual scheduling.

Every finished schedule writes `final_transfer_reproduction.zip` with the code and a portable observations table. The ZIP excludes clinical payloads, workstation paths, SSH usernames, keys and remote directory listings from the measurement records. The local audit stays with the experimenter. Publish the ZIP corresponding to the run cited in the thesis. The measured times can vary with CPU, storage, network and receiver load. Replaying a given set of observations reproduces its publication tables exactly.

## Comparing the five Phase 2 baseline files

From the project root, run the following command on the workstation with access to the KNUST receiver.

```bash
python3 thesis_code/final_transfer_study/baseline.py
```

This separate study reuses the original CSV, rewritten CSV, gzip, Parquet and Zstandard files from the November Phase 2 run. The runner checks all five against their recorded SHA-256 digests and reads the receiver from that run's metadata. Use `--phase2-run PATH` if the original directory has moved. This requires the retained files, SSH access to the intended receiver and rsync on both machines. The command creates a timestamped local and remote study directory.

Each file is sent once by each method in each of four consecutive blocks. Each method goes first twice per file. The original Phase 2 adaptive trial rule still describes the historical SCP benchmark. Fixed repetition here gives four matched observations per file, including the larger CSVs. Both clients send the file directly to a fresh destination over SSH. Formatting, compression and model fitting are outside the timed interval. The trial CSV records successful copy time, remote checksum time, delivery wall time and retry information. The summary uses only pairs in which both methods completed and verified on their first attempt. A positive paired difference means SCP finished sooner.

If a connection fails at preflight or the run is stopped, resume its pending deliveries with `python3 thesis_code/final_transfer_study/baseline.py --resume PATH/TO/RUN`. The protocol records the exact file hashes, code hashes, receiver and order. A stopped trial with uncertain status stays recorded as unknown. Each completed observation and its audit are retained. The original Phase 2 measurements and the separate Phase 6 archive comparison remain available in their own run directories.

If your terminal is already in `thesis_code/thesis_dashboard`, the script and output directory are one level up. For example, the following command opens the saved 24 November study from that directory.

```bash
python3 ../final_transfer_study/baseline.py --resume ../output/phase2_paired/20261124_070635_138140_UTC
```

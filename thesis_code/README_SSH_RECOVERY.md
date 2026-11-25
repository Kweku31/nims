# SSH interruption handling and thesis methods — v7 update

This update applies to the unified six-phase pipeline, the React dashboard, and the main-directory Phase 2 and Phase 6 transfer scripts. It changes transport and recovery, not PCA fitting, autoencoder architecture/training, feature selection, reconstruction metrics or clinical screening.

## What happens when a connection fails

| Situation | Behaviour |
|---|---|
| Connection reset/closed/refused, broken pipe, temporary DNS/network failure | Retry the operation, subject to a finite attempt budget. |
| A command exceeds its wall-clock deadline | Kill the local SSH/SCP process group, then retry within the same budget. |
| Authentication denied, untrusted/changed host key, full disk/quota, unknown error | Stop; do not repeatedly retry a configuration or security error. |
| Remote hash differs from the sender's hash | Stop immediately; never publish or rank that delivery. |
| Attempt budget exhausted | Show **Needs attention**, preserve logs/checkpoints, and fail strict SSH. |
| User stops a run | Terminate the pipeline and active local SSH/SCP processes. The run can be resumed manually. |
| Server or computer was interrupted | Dashboard marks previously running jobs interrupted; the user can resume them. |

The default is **three total attempts**, not three extra retries. Transient failures wait 2 seconds and then 4 seconds before the next attempt. Further delays, if the budget is increased, grow exponentially and are capped at 30 seconds. Each attempt has bounded setup, upload, verification and publication commands. There is no indefinite retry loop.

A strict SSH run never changes to simulation. For the unified `auto` mode, simulation is allowed only when `fallback_simulated` is true; the entire affected benchmark is then explicitly labelled simulated. Both the dashboard and the examples below use strict SSH or explicit simulation. Simulated results remain provisional.

## Safe delivery and verification

Each trial attempt uploads into a new private directory:

```text
REMOTE_DIR/<payload-filename>_unverified_<YYYYMMDD_HHMMSS_microseconds_UTC>_<unique-id>/
```

Phase 2 verifies the uploaded artifact. Phase 6 verifies **both the archive and its SHA-256 sidecar** against hashes calculated from the sender's bytes. The archive also passes the existing local package/content verification before sending. Only after all remote hashes match is the directory renamed, on the same remote filesystem, to:

```text
REMOTE_DIR/<payload-filename>_verified_<YYYYMMDD_HHMMSS_microseconds_UTC>_<unique-id>/
```

The filename makes the contents identifiable without opening each directory. For example:

```text
sepsis.csv.gz_verified_20261118_143025_123456_UTC_8e720bd7f51841dbaa7b860c245aa992/
sepsis.csv.gz_unverified_20261118_143019_654321_UTC_62309bc371bb4ab7b0fe7d70ec049a57/
```

The timestamp is the start of that upload attempt, in UTC, and remains unchanged on verification. A fresh identifier for every attempt and trial prevents collisions. The first non-`.sha256` filename supplies the label; Phase 6 therefore uses the archive filename, with its method/component information. Unsafe filename characters become underscores and labels are limited to 140 ASCII characters, keeping each directory name below 255 bytes. The original files inside retain their names. No patient records are read to construct the label.

`unverified` means uploading, interrupted, checksum-failed, or otherwise not published; it does not distinguish these cases by itself. The audit journal records both planned paths before setup and subsequent errors. A setup failure may leave no remote directory. A network outage needs no extra remote command to keep an incomplete upload labelled unverified.

The archive and sidecar are inside the verified directory recorded in each successful trial CSV. Receivers must use the exact published `remote_directory` and verify package integrity; if discovering directories by name, use the literal `_verified_` status segment, never a substring search for `verified` (which also matches `unverified`). Historic `verified-*` and `.partial-*` directories are not renamed by this update. Existing receiver scripts using the old glob must be updated for new deliveries. Remote commands require a POSIX environment with `sha256sum` and GNU-compatible `mv -T` (the intended Linux receiver).

Retries restart the full failed trial; **byte-level SCP resume is not implemented**. Unconfirmed partial directories are deliberately retained for inspection, with directory permissions 0700. Remove them manually after confirming no transfer is active. If publication succeeded but its SSH acknowledgement was lost, an extra verified directory can remain; it is not counted as a successful benchmark trial. Delivery does not claim exactly-once semantics.

## Aligned Phase 2 and Phase 6 trials versus network retries (2026-11-18)

Both Phase 2 and Phase 6 now use the same first-transfer rule in the main scripts and unified/dashboard pipeline. For each artifact/package independently, a first transfer of **10 seconds or less** leads to **10 total benchmark trials**, including the first; a first transfer over 10 seconds leads to one. Only the first transfer determines the count. Later slow trials do not terminate repetitions. All trials transfer the same prepared artifact.

The cutoff uses the clean successful SCP time, excluding verification, failed attempts and backoff; simulation uses its idealized transmission time and is not evidence of measured variability. A terminal failure or exhausted retry budget fails the benchmark instead of counting an unsuccessful trial as completed.

Unified options are `phase2_transfer_trials` (maximum, default 10) and `phase2_repeat_threshold_seconds` (default 10.0), also available as `--phase2-transfer-trials` and `--phase2-repeat-threshold-seconds`. `transfer_trials` / `--transfer-trials` controls the **Phase 6 maximum**, now defaulting to 10, and `phase6_repeat_threshold_seconds` / `--phase6-repeat-threshold-seconds` defaults to 10.0. The standalone Phase 6 sender uses `--trials 10 --repeat-threshold-seconds 10`; the batch script exposes `TRIALS` and `REPEAT_THRESHOLD_SECONDS` with these defaults. Existing custom configurations that used `transfer_trials` for Phase 2 must set `phase2_transfer_trials` explicitly. Existing saved configurations explicitly specifying a smaller Phase 6 `transfer_trials` value retain that override: set it to 10 for the aligned default budget. To request one trial, set the relevant phase maximum to 1. The dashboard uses the 10-trial/10-second rule for both phases and displays it when starting an experiment. Local packaging repetitions are unchanged: the unified pipeline still uses `packaging_runs`; the main script retains its existing adaptive packaging rule.

A **trial** is a planned performance measurement. An **attempt** is one try at completing that trial. For example, trial 2 can fail on its first attempt and succeed on its second: this gives one completed trial, one failed attempt, and two attempts. The default `ssh_max_attempts=3` means at most three total attempts per trial, not three extra benchmark trials. If all 10 trials each succeed on their third attempt, that means 10 completed trials and 30 attempts. Setup/preflight operations have their own retry budget. Failure time and backoff remain in the recovery audit, separate from the clean transfer time used for the threshold.

Phase 6 trial CSVs record `maximum_trials`, `requested_trials` (the count required after the first transfer), `repeat_threshold_seconds`, `first_transfer_seconds` and `trial_policy`. Results and final evidence carry the corresponding `remote_*` fields. The completeness/ranking gate recomputes the required count: a verified slow one-trial result is valid; a partial fast benchmark with one of ten required trials is not. The standalone summary checks the same rule.

The same policy need not produce the same count: a small Phase 2 artifact can require ten trials while its larger Phase 6 package requires one. One trial cannot estimate run-to-run variability; report the observed count alongside timing statistics.

`transfer_benchmark.csv` records actual completed trial counts for each artifact, `transfer_trials.csv` records individual measurements, and `transfer_metadata.json` records the configured maximum, cutoff and time basis. The unified checkpoint now checksums this metadata as well. New code/configuration fingerprints can invalidate older checkpoints; active jobs are not restarted by this update.

## Run and resume

From `thesis_code`, activate the existing environment, then run the unified pipeline:

```bash
source thesis/bin/activate
python thesis_unified/run_thesis.py --config thesis_unified/example_config.json \
  --dataset /absolute/path/to/dataset.csv --output-dir /absolute/path/to/experiment \
  --transfer-mode ssh --remote researcher@your-server --ssh-port 22
```

After fixing connectivity or a reported problem, **repeat the identical command and output directory**. Completed checkpoints are reused only when input/configuration/code fingerprints and artifact checksums still match. A failed Phase 2 reruns its benchmark; a failed Phase 6 configuration rebuilds and repeats its package trials. Other valid completed phases/configurations can be reused. Individual completed trials within a failed configuration are retained as audit evidence, but are not reused to complete a later benchmark.

Installing this code update changes the code fingerprint, so an older run can legitimately recompute phases on its first resume. Changing the dataset or settings also invalidates dependent work. Do not force old checkpoints to be accepted.

In the dashboard:

1. Start `python thesis_dashboard/server.py` in the pipeline Python environment and open `http://127.0.0.1:8765`.
2. Select **Strict SSH**. Under **Connection and recovery settings**, choose port, remote directory, maximum attempts and transfer deadline.
3. Follow the **Connecting**, **Connection lost — retrying**, and **Needs attention** messages.
4. After correcting the problem, choose **Retry / Resume** on the failed, stopped or interrupted experiment. This keeps its job ID, saved configuration, output directory and audit history.

The dashboard runs one experiment at a time. On Linux, it also checks the recorded process identity before launching or resuming: a worker that survived a dashboard restart must finish or be stopped first. Resume does not accept replacement settings; use a new experiment for a different study configuration. Existing imported report snapshots are read-only and have no Resume button. Completed invocations publish all six consolidated reports together in a new UTC-timestamped results directory, preserving earlier snapshots.

## Settings

All seven settings below are accepted in unified JSON configuration and as CLI flags (replace underscores with hyphens). They are also accepted by both root Phase 2 and Phase 6 `send` commands.

| Setting | Default | Meaning |
|---|---:|---|
| `ssh_max_attempts` | 3 | Total attempts per preflight operation or delivery trial; integer 1–10. |
| `ssh_retry_delay` | 2 | Base backoff in seconds; nonnegative finite number. |
| `ssh_connect_timeout` | 15 | Connection/handshake timeout in seconds. |
| `ssh_command_timeout` | 60 | Wall deadline for each remote setup, hash, rename or preflight command. |
| `ssh_transfer_timeout` | 300 | Wall deadline for each whole SCP upload; increase for larger files/slower links. |
| `ssh_keepalive_interval` | 15 | SSH protocol keepalive interval. |
| `ssh_keepalive_count` | 3 | Maximum unanswered keepalives before disconnecting. |

Positive timeout/keepalive values must be integers from 1 to 86400. Batch mode and strict host-key checking are always enabled. Trusted host keys and working noninteractive key authentication must already be configured. These settings follow the [OpenSSH client configuration documentation](https://man.openbsd.org/ssh_config), including its approximately 45-second unresponsive-server detection example for interval 15/count 3; the explicit wall deadline separately bounds each command.

Main-directory examples:

```bash
python 02_transfer_benchmark.py /absolute/path/to/dataset.csv \
  --transfer-mode ssh --host your-server --user researcher --port 22 \
  --remote-dir /tmp/thesis_transfer/phase2 --ssh-max-attempts 3 --ssh-transfer-timeout 600

python 06_transfer_package.py send /absolute/path/to/package.tar \
  --remote researcher@your-server --remote-dir /tmp/thesis_transfer/phase6 \
  --ssh-port 22 --trials 10 --repeat-threshold-seconds 10 --ssh-max-attempts 3 --ssh-transfer-timeout 600

REMOTE=researcher@your-server SSH_PORT=22 SSH_MAX_ATTEMPTS=3 \
  SSH_TRANSFER_TIMEOUT=600 bash 06_run_phase6_ssh_benchmarks.sh
```

The root scripts share `thesis_unified/thesis_pipeline/ssh_transport.py`; keep that directory alongside them. Their existing packaging and repetition rules are preserved, including the root Phase 2 adaptive repetition policy. The root Phase 6 summary excludes new incomplete trial reports by checking their `requested_trials` field. Historic trial CSVs without this field cannot prove an intended trial count.

## Timing and reporting for the thesis

Do not mix a failed transfer's elapsed time into a successful SCP duration or describe the resulting successful-transfer mean as total user waiting time.

- `scp_seconds`: upload time of the final successful attempt only.
- `remote_sha256_verification_seconds`: remote hash-command time for that successful attempt.
- `failed_attempts` / `attempts`: failure count and total attempt count for this delivery trial.
- `failed_attempt_seconds`: wall time spent in failed attempts, including any setup/upload/hash/publication work before failure.
- `backoff_seconds`: measured waiting time between attempts.
- `recovery_overhead_seconds`: failed-attempt time plus backoff time.
- `delivery_wall_seconds`: elapsed time across all attempts, including successful setup/publication and recovery. Sender-side file hashing occurs before this interval.

Phase 6 trial CSVs retain these fields, even when a later trial fails. A report is eligible only after the full requested trial count succeeds with remote verification. Package evidence contains mean recovery/wall times and total failed attempts; the network trial table preserves trial-level values. Phase 2 recovery details are available in the event journal; its existing trial/summary CSVs continue to describe successful benchmark timings.

For comparability with the existing study, TOPSIS delivery criteria retain the **successful-delivery timing basis**. Recovery overhead is reported separately, not silently inserted into that criterion. Consequently, those rankings do not measure outage resilience and can favour a method that needed retries. Use the failure counts, recovery overhead and wall times alongside the rankings when discussing operational suitability. A long deadline failure is an observed interrupted attempt, not an imputed successful throughput value.

The existing `end_to_end_seconds` combines package creation, local verification, successful transfer, remote hashing, and local unpack/reconstruction. It is still a proxy: receiver recovery runs locally, not on the remote machine. `end_to_end_with_network_recovery_seconds` substitutes the measured delivery wall time for the successful network component. Neither proxy is a single receiver-side stopwatch measurement. Existing fresh-data versus existing-payload scenario definitions remain unchanged.

Each unified output directory contains append-only `network_events.jsonl` and current `network_status.json`, separate from checkpoint evidence. Each published `run_manifest.json` includes a snapshot of the recovery audit (including explicitly flagged truncated journal lines), preserving it in the same timestamped results directory as the other reports. Preflight failures and unsuccessful deliveries remain visible even when final reports cannot be published. Root commands place these beside their output/report unless an experiment-wide audit destination is inherited. Protect the logs with the experiment: they contain host/path/error metadata, though no intended CSV row contents.

### Suggested methodology wording

> SSH delivery used noninteractive authentication, strict host-key checking, protocol keepalives and explicit per-command deadlines. Transient network failures triggered a bounded retry policy of up to three total attempts, with exponential backoff starting at two seconds. Each attempt transferred the full artifact into a unique temporary directory. Remote SHA-256 digests were compared with sender-side digests; Phase 6 checked both the package archive and its sidecar. Only verified directories were published, and only complete verified trial sets were eligible as measured SSH evidence. Failed-attempt durations and retry waits were retained separately from successful SCP timings. The existing decision criterion therefore describes successful delivery cost; failure counts and total delivery wall time provide complementary operational evidence. Interrupted experiments resumed from valid completed phase/configuration checkpoints, while the failed benchmark unit was repeated.

Describe this as the implemented method. Do not claim improved resilience, real-network throughput, or clinical benefit until measured experiments support those conclusions. Validation here uses synthetic data, fault injection and local SSH/SCP stand-ins; it does not establish performance on a real remote server. PCA/AE and clinical-screen algorithms are unchanged.

## Downloadable update

`thesis_v7_ssh_update.zip` contains the updated main-directory scripts, unified pipeline and dashboard, under a `thesis_code/` directory. It is an update bundle for the existing project; datasets, generated experiments and environments are excluded. The separate `thesis_unified_v7.zip` and `thesis_dashboard.zip` are also refreshed. All archives include a SHA-256 file manifest and have a sibling `.zip.sha256` checksum. From the main directory, rebuild them after `npm run build` in the dashboard using `python build_v7_ssh_update.py`.

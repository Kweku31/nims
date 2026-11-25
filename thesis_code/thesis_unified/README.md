# Unified thesis pipeline — v7: verified rankings, delivery scenarios and checkpoints

The SSH recovery update adds bounded retries, keepalives, deadlines and verified directory publication. See [README_SSH_RECOVERY.md](README_SSH_RECOVERY.md) for usage, measurement boundaries and thesis wording.

Version 7 excludes unverified SSH evidence from rankings and recommendations, adds separate `fresh_data` and `existing_payload` delivery timing, hashes selected datasets and payload artifacts, and fixes checkpoint propagation and empty reports. PCA/AE, clinical-screen, selection and utility algorithms are unchanged. See [CHANGELOG_V7.md](CHANGELOG_V7.md) for the review findings, formulas and validation procedure.

The separate, append-only log is created immediately under **`thesis_runs/pipeline.log`** (when run from `thesis_unified/`). Each successful run puts all six consolidated reports together in a new directory under `thesis_runs/results/`, named with a UTC timestamp and a unique suffix. Subsequent runs, including checkpoint resumes, preserve earlier report directories. The exact directory is printed as `RESULTS:` and saved in `run_status.json` as `results_directory`.

Both delivery scenarios run by default. To select one, use `--delivery-scenarios fresh_data` or `--delivery-scenarios existing_payload`. For a development run without SSH, use `--transfer-mode simulated`. Setting `fallback_simulated` to `false` disables fallback in `auto` mode, including failed preflight; explicit `simulated` mode is still supported.

**Commands from inside `thesis_unified/`:**

```bash
# First establish key-based access and a trusted host key.
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes researcher@server.example.org 'echo SSH_OK'

# Mandatory real network measurement; fails instead of silently simulating.
python run_thesis.py --dataset sepsis_1000_raw.csv \
    --output-dir thesis_runs \
    --remote researcher@server.example.org \
    --remote-dir /tmp/thesis_transfer/phase6 \
    --transfer-mode ssh --transfer-trials 10 \
    --minimum-feature-retention-pct '80%' \
    --minimum-measurement-retention-pct '95%' \
    --maximum-new-violation-pct '1%' \
    --violation-sensitivity '0%' '0.1%' '0.5%' '1%' '5%' \
    --topsis-weights 23 17 22 12 10 6 10

# In a second terminal, from the same working directory:
tail -n 50 -F thesis_runs/pipeline.log
```

These are *illustrative study-defined decision thresholds*, not clinical safety standards. The `--topsis-weights` example is deliberately different from the built-in balanced vector; omit the flag to select equal weights, with the named profiles retained for comparison. Use `--transfer-mode auto` for a development run that can fall back to **explicitly provisional** simulation when SSH is inaccessible.

**New evidence fields:** `remote_sha256_verified`, `remote_trials_completed`, `receiver_local_checksum_verified`, `criteria_available`, `measured_completely`, `empirical_ssh_eligible` and `effective_delivery_time_basis`. `02_decision_rankings.csv` includes `decision_evidence_status` and candidate counts. The report adds an exploratory clinical-screen threshold sensitivity table without generating another main results file.

**Standards and research references:** [STANDARDS_AND_VALIDATION.md](STANDARDS_AND_VALIDATION.md). The real SSH benchmark cannot be run inside this offline environment, and local receiver recovery is not the same as decoding on the university server.

---

# Unified clinical-data transfer thesis pipeline

Reproducible orchestration for the six research phases. **The original mathematics and algorithms are preserved** in `thesis_pipeline/legacy/`; the adapters in `thesis_pipeline/phase1.py` ... `phase6.py` delegate to them. Cross-cutting functions (hashing, metadata, subprocess logs, checkpointing, SSH detection) live in `thesis_pipeline/core.py`. No FIDDLE or predictive model is used.

## Install / run

Run these commands from the extracted `thesis_unified` folder inside `thesis_code` (with `sepsis_1000_raw.csv` in that directory for this run; otherwise supply its real path).

On Ubuntu (inside the existing thesis virtual environment):

```bash
python -m pip install numpy pandas scipy scikit-learn pyarrow zstandard
python run_thesis.py --dataset sepsis_1000_raw.csv --output-dir thesis_runs
```

The first command is a dependency prerequisite; pip requirements depend on your venv. Run with SSH if configured:

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv \
  --remote USER@SSH_HOST --remote-dir /home/USER/thesis_incoming \
  --transfer-mode auto --output-dir thesis_runs
```

`--transfer-mode auto` performs an SSH key-authentication preflight and falls back to **explicitly labeled idealized simulation** if SSH is unavailable. Remote SCP and checksum verification require the university account to have SSH key access. There is no claim of an actual network measurement when simulated.

The defaults compare the original data and FS-95 clinical-review data, with PCA/AE components k=2,4,8. All Phase 3 sensitivity experiments are still generated. Compare **all** Phase 3 feature-selection variants in downstream phases via:

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv --all-feature-sets \
  --compare-npz-codecs --remote USER@SSH_HOST --transfer-mode auto
```

This expands downstream computations considerably; it does not retrain Phase 5 or Phase 6 models. The NPZ codecs `native/gzip/zstd` compress the *same uncompressed NPY member data* without applying gzip on already-DEFLATE-compressed NPZ. All Phase 4 exact-preservation rules are retained: Age, HospAdmTime, ICULOS, plus structural/category/outcome fields.

`--dry-run` prints resolved options; `--force phase4 phase5 phase6` explicitly rebuilds those phases. Phases depending on a forced/rebuilt phase are also invalidated and rerun. On reruns with the same input bytes, options and code, a completed stage is **skipped only if checkpoint artifacts and stored SHA-256 digests still match**. If a stage fails, earlier independent completed phases remain reusable. Package configurations are checkpointed separately; failures are recorded in `run_manifest.json`. An exclusive file lock prevents concurrent writes to one run. Changing the input, settings, or code produces a new run ID.

## Output files are initialized at startup (v5)

For a normal experiment (without `--dry-run`), the runner **creates the live
`pipeline.log`, the `results/` directory, and `run_status.json` before it
validates the input or begins Phase 1**. This means you can start `tail -F`
immediately; you do not need to wait for profiling to finish. The console
retains its original messages without timestamp prefixes. A failed validation
still writes an error to the log and marks `run_status.json` as `failed`.

From the `thesis_unified` directory:

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv \
    --output-dir thesis_runs --transfer-mode auto
```

Then, from **another terminal in the same directory**:

```bash
tail -n 50 -F thesis_runs/pipeline.log
cat thesis_runs/run_status.json
```

Directory layout **as soon as the run starts**:

```text
thesis_runs/
├── pipeline.log       # immediately, append-only
├── run_status.json    # initializing / running / failed / complete
├── results/           # immediately, may be empty until publication
└── runs/<run-id>/      # checkpoint and per-run artifacts
```

**Final report CSVs are deliberately not filled with placeholder values.**
They are published atomically after all required calculations succeed. Until
`run_status.json` says `complete`, a `results/` directory may be empty or may
still hold a previous successful run's reports; do not mistake those for the
current run. Run-specific checkpoints can be inspected while a stage is active.

The root output path is resolved from `--output-dir` (or the config file), not
relative to the `run_thesis.py` location. The terminal prints the absolute log
path. If you start the command from `thesis_unified` using
`--output-dir thesis_runs`, monitor `thesis_runs/pipeline.log`.
From the parent `thesis_code` directory, monitor `thesis_runs/pipeline.log`.

## Separate terminal output and unified log (all six phases)

Every non-dry-run invocation preserves the **original, unformatted terminal output**. In parallel it appends a **single live, timestamped log** at
`<output-dir>/pipeline.log`, covering Phases 1--6, Phase 2 TOPSIS, the final
decision, subprocess stdout/stderr, resumable checkpoint decisions, warnings,
exceptions, and SSH-to-simulated fallbacks. Each line records `run=<run-id>`
and `phase=<phase-label>` so several different runs in one output directory can
be distinguished. The file is created with private user permissions (0600).

In terminal 1, start the experiment as usual:

```bash
# Working directory: thesis_unified
python run_thesis.py --dataset sepsis_1000_raw.csv \
  --output-dir thesis_runs --transfer-mode auto \
  --remote USER@SSH_HOST
```

In terminal 2, follow **all phases in real time**, including messages from
legacy scripts while they are still running. **The path is relative to your
current directory**. If you are inside `thesis_unified` and ran with
`--output-dir thesis_runs`, use:

```bash
tail -n 50 -F thesis_runs/pipeline.log
```

If your terminal is in the *parent* `thesis_code` directory instead, use:

```bash
tail -n 50 -F thesis_runs/pipeline.log
```

`-F` keeps watching if the log file is created later or rotated. At startup
`run_thesis.py` prints the **absolute LOG FILE path** so you can copy it
without guessing where the relative path resolves.

To monitor just errors, failures, or the network fallback:

```bash
tail -n 30 -F thesis_runs/pipeline.log | grep --line-buffered -E 'WARNING|ERROR|FAILED|NETWORK'
```

To use a different log location (an operational option, **not part of the
experiment fingerprint**):

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv \
  --output-dir thesis_runs --log-file ../logs/thesis_all_phases.log

tail -F ../logs/thesis_all_phases.log
```

The consolidated file is **not echoed with timestamp prefixes to the terminal**.
Original progress lines and errors appear unmodified. The consolidated log is
separate from the six concise results files and from
independent phase-specific logs retained under `_work`. On a resumed run, logs
are **appended**, not deleted; completed stages appear as `SKIP` with their
verification status. Changes to data/configuration/code still produce new run
IDs, labeled in this one file. A log records *what ran*; it is not a substitute
for SHA-256 artifact verification or the research results themselves.

Do not publish raw logs from sensitive clinical environments without reviewing
them first: subprocesses may print file names or other sensitive context.

## Optional JSON configuration

`python run_thesis.py --config example_config.json --dataset PATH/TO/INPUT.csv`

Phase 2 and Phase 6 transfer repetitions are adaptive: the first transfer taking at most 10 seconds triggers up to 10 total trials; a slower first transfer ends after one. Configure `phase2_transfer_trials` and `phase2_repeat_threshold_seconds` alongside the Phase 6 `transfer_trials` maximum (default 10) and `phase6_repeat_threshold_seconds` cutoff (default 10 seconds). Trial counts are separate from `ssh_max_attempts`, which bounds recovery attempts within a trial. See `README_SSH_RECOVERY.md` for timing and migration details.

Important fields: `feature_sets` (e.g. `["FS_95_clinical_review"]` or `"all"`), `k`, `ae_max_iter`, `distance_samples`, `compare_npz_codecs`, `strict_dependencies`, `model_reuse_count`, `remote`, `transfer_mode`, `remote_dir`, `transfer_trials`, `fallback_simulated`. CLI arguments override the config. The `model_reuse_count` controls the share of training time charged to each transfer in the final TOPSIS decision (default 1 = model trained for one transfer). Set it above 1 only if model reuse is actually part of your operating assumptions.

When `strict_dependencies=true` (default), the run stops if necessary lossless codecs are unavailable. For limited development smoke testing only, `--allow-missing-codecs` permits partial baselines; the final report must still be marked incomplete when methods are missing.

## Percentage-based controls (Phase 1, Phase 3 and final decision)

You can pass percentages **directly on the command line**; JSON configuration uses
the same syntax. For example, `75`, `75%` and `0.75` all mean **75%**.
For bare values between 0 and 1, the value is treated as a fraction; use
`1%` explicitly to mean one percent (bare `1` means 100%). The resolved
configuration is normalized and persisted in `run_manifest.json`.

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv \
  --missingness-thresholds 80 90 95 \
  --patient-coverage-min 75 \
  --correlation-threshold 95 \
  --correlation-action flag \
  --clinically-protected Lactate \
  --minimum-feature-retention-pct 80 \
  --minimum-measurement-retention-pct 95 \
  --maximum-new-violation-pct 1 \
  --topsis-weights 22 18 22 12 10 6 10 \
  --dry-run
```

Remove `--dry-run` to actually execute. The three final-decision safeguard
options are **optional**: leaving them unset does not filter lossy candidates.
They constrain only the `loss_tolerant` ranking; exact-data scenarios remain
separate. These thresholds are **study-specific policy choices, not clinical
validation or literature-established acceptance criteria**. A candidate
meeting them is still not automatically clinically suitable.

| Option | Meaning | Default |
|---|---|---|
| `--missingness-thresholds` | Hourly missingness cutoffs for Phase 3 variants | `80 90 95` |
| `--patient-coverage-min` | Minimum fraction of patients measured at least once to protect a high-missingness variable in clinical variants | `75` |
| `--correlation-threshold` | Absolute Pearson correlation cutoff in Phases 1 and 3 | `95` |
| `--phase1-correlation-threshold` | Override just Phase 1 correlation cutoff | same as above |
| `--correlation-action` | Flag high correlation (default), or opt-in to dropping | `flag` |
| `--min-correlation-observations` | Paired-observation support minimum (count, not %) | `200` |
| `--min-correlation-patients` | Paired-patient support minimum (count, not %) | `30` |
| `--clinically-protected` | Explicitly protected variable names; *not a percentage* | `Lactate` |
| `--feature-sets` | Specific Phase 3 variant labels, or `all` | `FS_95_clinical_review` |
| `--minimum-feature-retention-pct` | Optional minimum clinical predictor retention to enter loss-tolerant TOPSIS | no filter |
| `--minimum-measurement-retention-pct` | Optional minimum observed-cell retention to enter loss-tolerant TOPSIS | no filter |
| `--maximum-new-violation-pct` | Optional maximum newly flagged clinical-range violation rate in loss-tolerant TOPSIS | no filter |
| `--topsis-weights` | Optional custom weights for seven criteria in the documented order, totaling 100% | equal weights (1/7 each); named comparison profiles retained |

The seven TOPSIS weights follow this order: transmitted bytes, effective
delivery time, reconstructed R², top-5 neighbour overlap, clinical-feature
retention, observed-measurement retention, and new range violations.
Weight examples: `22 18 22 12 10 6 10` or `.22 .18 .22 .12 .10 .06 .10`.
Distinct custom weights add a profile and become the primary selection. Equal weights are the default; named profiles remain available for comparison.

For a different Phase 3 screening design, use for example:

```bash
python run_thesis.py --dataset sepsis_1000_raw.csv \
  --missingness-thresholds 70 85 95 \
  --patient-coverage-min 60 \
  --feature-sets all --transfer-mode simulated
```

Note: Phase 3 variant directories use rounded whole-percentage names (such as
`FS_85_clinical_review`). If thresholds change, specify the new name via
`--feature-sets`, or use `--feature-sets all` to avoid a mismatched name.

Percentages are **not interchangeable** with dimensionality `k`, absolute
clinical measurement bounds, or raw counts. Such settings retain their native
units.

## Outputs (one timestamped directory per completed run)

The exact report location is printed as `RESULTS: /absolute/path/...` when the
run completes. This is **not** the directory in which you launch Python. For
example, launching from `thesis_unified` with `--output-dir
thesis_runs` generates:

```text
thesis_code/thesis_unified/thesis_runs/
  pipeline.log                   <-- append-only log, never printed with prefixes
  run_status.json                 <-- points to the completed run's report directory
  results/
    20261113_120000_123456_UTC_abcd1234/  <-- all six reports for one completion
      FINAL_REPORT.md
      01_integrated_evidence.csv
      02_decision_rankings.csv
      03_phase_overview.csv
      04_network_trials.csv
      run_manifest.json
    20261113_140000_654321_UTC_efgh5678/  <-- subsequent run's reports
  runs/<run_id>/
    checkpoint.json
    results/                    <-- working reports for this checkpoint run ID
    _work/                     <-- detailed phase artifacts and phase logs
```

Each timestamped snapshot is published **only after** all six report files
have been copied successfully, using an atomic directory rename. The timestamp
records publication time in UTC; the suffix prevents collisions even for
simultaneous publications. Previous snapshots are never overwritten. Existing
reports directly under `results/` from older versions are left in place.
`--dry-run` deliberately does not execute phases or create the log/reports.

## Scientific decision policy

The integrated evidence file joins actual Phase 6 package measurements to Phase 5 utility using **absolute Phase 4 run-directory identity** (not ambiguous filenames such as `selected_dataset.csv`), and also links Phase 2 baseline context. It contains the full set of available reconstruction, nearest-neighbour, retention and cost measures, not just the seven ranking criteria.

Only verified packages with finite, in-range criteria enter TOPSIS. SSH also requires remote checksum verification and completed requested trials. Rankings are formed **separately for each dataset, network mode and delivery scenario**, for these fidelity scenarios:

1. `full_fidelity`: exact preservation of the full original source feature set; all lossy or feature-eliminating methods are disallowed.
2. `selected_columns_exact`: lossless preservation of columns actually transmitted after feature selection (with full-reference retention explicitly scored).
3. `loss_tolerant`: compare all verified methods, *without asserting that reconstruction errors are clinically acceptable*.

The TOPSIS criteria and four built-in weight profiles (equal, balanced, transfer-priority, utility-priority) are defined in `thesis_pipeline/decision.py`, with cost/benefit directions explicitly documented. Primary criteria: total sent bytes (archive + checksum); effective delivery time including allocated model fitting; observed-value standardized R²; reconstruction-space top-5 overlap; feature retention; measured-cell retention; and newly introduced clinical-range violation percentage. Other measured indicators remain visible in `01_integrated_evidence.csv` but are deliberately not counted twice in the weighted ranking.

**TOPSIS is NOT clinical validation.** The clinical range tests are screens; one per-patient hourly observation for neighbourhoods is not validation of clinical patient matching. The measured utility of a selected dataset has a different feature denominator from full data. Model training was carried out on the studied data (no out-of-sample generalization claim). Never compare simulated and real transfer times in the same ranking. A fully validated recommendation additionally needs **real university SSH transfer**, model/representation stability and the full 20,336-patient Sepsis A evaluation.

`end_to_end_seconds` is a local receiver-side timing proxy (Phase 6 package, send/idealized payload calculation, verification, unpack, decompression/reconstruction). It is **not** a university ingestion benchmark. For `existing_payload`, `effective_delivery_seconds = end_to_end_seconds`. For `fresh_data`, add `model_fit_seconds/model_reuse_count + initial_encode_seconds + initial_payload_creation_seconds`. Lossless methods have zero fit/encoding cost and use measured Phase 4 lossless compression/serialization for payload creation. PCA/AE use measured fit, encoding and initial NPZ serialization/compression. Missing preparation measurements exclude fresh-data candidates. These scoped proxies exclude CSV loading, preprocessing and feature selection. For lossy methods reconstruction is measured in memory (no automatic giant reconstructed CSV), while the receiver program is treated as installed once. Both lossless and reduced-data recovery are verified without needing the original CSV at the receiving side.

Security: checksums detect corruption but their authenticity depends on authenticated SSH or another trusted provenance channel. Use anonymized/authorized data and a protected remote directory, not unsecured temporary shared storage.

## Modules

| Module | Responsibility |
|---|---|
| `core.py` | SHA-256, JSON, live unified logging, phase-aware subprocess logs, SSH preflight, checkpoints, locking |
| `phase1.py` | Profiling + dimension/sparsity/missingness |
| `phase2.py` | Lossless baseline + repeated SSH/idealized transfers + original TOPSIS |
| `phase3.py` | FS-0, FS-80, FS-90, FS-95 + clinical review variants |
| `phase4.py` | PCA/AE, lossless baselines, exact clinical passthrough, checksums |
| `phase5.py` | Reconstruction/distance/neighbourhood/retention, no classifier |
| `phase6.py` | Build, verify, receiver recover; complete TAR+manifest+SHA256; SCP or labeled simulation |
| `decision.py` | One joined evidence matrix and sensitivity/eligibility TOPSIS |
| `run_thesis.py` | Single entry point and dependency-aware pipeline orchestration |

## Requirements and limitations

- Python 3.10+; shell `ssh`, `scp`, `sha256sum`; `zstd` executable optional if `zstandard` module is present.
- Original Phase 2 TOPSIS requires at least two compressed baselines. A missing baseline results in a warning, not a fabricated ranking.
- If a schema or a required source/checksum is missing, the dependent operation fails. Other Phase 6 configurations may continue; missing methods remain excluded from the conclusion.
- Remote end-to-end ingestion (Project 4) and scheduling are deliberately out of scope; `cron`/systemd can invoke the runner later if required.

See [New experiment controls](README_EXPERIMENT_OPTIONS.md) for required inputs, optional defaults, equal/custom TOPSIS weights and advanced settings.

## Optional autoencoder GPU execution

See [README_AE_ACCELERATION.md](README_AE_ACCELERATION.md) for GPU setup, batch-size controls, live epoch progress, measured timing/quality tradeoffs and validation. CPU remains the default. Restart the dashboard server after an active experiment finishes to load the new controls.

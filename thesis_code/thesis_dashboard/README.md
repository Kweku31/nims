# Observatory — React thesis dashboard

A separate, local React app for `../thesis_unified`. It keeps the original six-phase Python pipeline and its research algorithms intact.

## Demonstrate the thesis

Open **Thesis walkthrough** in the sidebar, or go directly to `http://127.0.0.1:8765/#thesis`. This view presents the archived Chapter 4 measurements, separately from the synthetic example and any experiment currently running. No dataset upload, GPU or SSH connection is needed for the walkthrough.

Use **Next step** to move through the six phases and the final decision. Change the hourly missingness threshold in Phase 3, then vary the latent dimension in Phases 4 and 5. In Phase 6 compare fresh data with an existing payload. In **Decide**, choose the receiver’s fidelity requirement and inspect the first-ranked format for each eligible feature set. The live results view continues to support custom weights and other experiments. When the recorded snapshot is available in the local history, **Inspect** opens its underlying phase or ranking table.

**Evidence and provenance** gives the run ID, input digest and report checksums. The full package ranking uses verified SCP measurements. The embedded rsync measurements come from the smaller paired direct-file and archive studies. Only aggregate results are distributed. The export is specific to this study.

To regenerate the browser reference and the slide values together, run this from `thesis_code` with the saved reports and slides directory present. Then rebuild the dashboard and recompile the slides.

```sh
python3 thesis_dashboard/build_thesis_reference.py thesis_dashboard/data/jobs/job-c2cbe4fe79e3/output/results/20261120_083420_390853_UTC_hy7dh134
```

The eight-slide Beamer defence and its timed speaking script are in `../thesis_slides/defence/`.

## Start

From `thesis_code/thesis_dashboard`, with Node 20.19+ and the **Python environment containing the pipeline dependencies**:

```bash
npm ci
npm run build
python server.py
```

Open **http://127.0.0.1:8765**. The Python server serves the built React app and its API. It uses its own Python executable to start experiments, so activate the thesis environment before starting the server. If needed, install its dependencies:

```bash
python -m pip install -r ../thesis_unified/requirements.txt
```

The dashboard itself needs only the Python standard library. The Settings screen checks the pipeline dependencies and shows the active interpreter. Node is needed to build/develop the app, not to serve an already-built dashboard.

For frontend development, keep `python server.py` running and use a second terminal:

```bash
npm run dev
```

Open **http://127.0.0.1:5173**. Vite forwards `/api` requests to the local Python server.

## What is included

- **Overview:** six-phase progress, elapsed time, local package counts and conditional leading configurations. Delivery-time bars and a reconstruction-versus-size plot share the selected comparison scope.
- **Dataset viewer:** use **View dataset** on the experiment bar or **Dataset viewer** in the sidebar. Browse 25 source records per page, find columns and expand a record to inspect all displayed values. Leading zeros, quoted fields and empty cells are preserved. A checksum warning identifies a source CSV changed since the experiment.
- **Pipeline phases:** profiling, transfer baseline, feature selection, PCA/AE, utility evaluation and verified delivery. Click **View** beside a measurement to expand its fields and related evidence. The **More phase information → Detail report** dropdown exposes original saved artifacts, such as flagged correlation pairs, column profiles, retained/removed columns with reasons, per-feature utility and network trials. Completed phase artifacts can be inspected before final consolidation.
- **Results:** searchable and sortable TOPSIS rankings, separated by feature set, delivery scenario, network mode, fidelity requirement and weight profile. No new rankings are computed in the frontend.
- **History:** existing timestamped result snapshots and new dashboard experiments. Open an experiment to inspect its outputs.
- **Live logs:** poll every two seconds; display the last 100 KB, with the complete log retained on disk.
- **New experiment:** select a local CSV or use **Upload CSV**, then **Preview CSV** to inspect records before starting. Choose component counts, AE iteration limit, feature sets, codecs and a **75%, 80% or 90% patient coverage criterion**. Simulated networking is the default. Strict SSH requires an explicit `user@host` and existing key authentication; simulation fallback is disabled.
- **Stop:** terminates the owned process group while preserving completed checkpoint artifacts. One dashboard experiment runs at a time.
- **Downloads:** all six original report files, including evidence, rankings, trials and the manifest.
- **Synthetic demo:** bundled aggregate results from the validated v7 synthetic run (64 rows, 16 generated patients, 18 packages). It is explicitly labeled and contains no patient records or machine-specific paths. The demo can also be viewed with only the Vite dev server.

## Existing results and new run locations

By default, the dashboard imports `../thesis_unified/thesis_runs/results/`. Point it at another pipeline **output root**, not an individual report folder:

```bash
python server.py --results-root /path/to/thesis_runs
python server.py --results-root /path/to/run_a --results-root /path/to/run_b
```

It recognizes both the v7 timestamped folders and the older flat six-report folder. Imported runs are read-only. Historical checkpoint timings reflect the available checkpoint; the original CSV measurements are read directly from each report snapshot.

New runs are stored separately:

```text
thesis_dashboard/data/jobs/job-<id>/
  config.json
  job.json
  launcher.log
  output/
    pipeline.log
    run_status.json
    runs/<fingerprint>/...
    results/<UTC timestamp>_<unique suffix>/
      FINAL_REPORT.md
      01_integrated_evidence.csv
      02_decision_rankings.csv
      03_phase_overview.csv
      04_network_trials.csv
      run_manifest.json
```

Use `--data-dir /path/to/dashboard-data` to change the dashboard storage location or `--pipeline-dir /path/to/thesis_unified` to select the pipeline. Each New experiment gets a new output root. The UI does not currently expose checkpoint resume; saved configs and checkpoints can be resumed using `run_thesis.py --config /path/to/config.json`. On server restart, previously active jobs are marked interrupted rather than assumed to be live. Keep the server running while an experiment runs; Ctrl+C stops owned runs.

Uploads are stored under `data/uploads/<unique-id>/<filename>`, with unique directories so identically named files cannot overwrite one another. The upload limit is 100 MB; larger datasets can be selected by their local path. Previews are bounded to 25 rows per page, the first 200 columns, and 1,000 characters per cell. Uploaded files stay local and are retained for subsequent experiments.

## Patient coverage and detailed records

The patient coverage dropdown passes `patient_coverage_min` to the existing pipeline as `0.75`, `0.80` or `0.90`. It controls the Phase 3 clinical-review safeguard for retaining sparse features observed in at least that fraction of patients. It does not remove or sample patient rows. To compare the criteria, start separate experiments with the same dataset and different coverage selections; each receives separate timestamped results. The active experiment bar shows the saved criterion, and the configuration and manifest record it. Existing experiments remain unchanged.

In Phase 1, a count of **4 highly correlated pairs** expands to the four pairs from `redundant_pairs.csv`, including both column names, Pearson correlation and paired-observation count. This is a pair count, not four deleted columns; Phase 1 does not remove features. Exact duplicate columns are a separate report. Missing detailed artifacts are labeled as missing rather than reconstructed from a summary count. The report selector displays up to 1,000 loaded rows, with up to 200 visible/filterable records at a time.

## Updating a running dashboard

After replacing dashboard source or rebuilding the frontend, restart `server.py` and refresh the browser. The app detects older servers using API version 2. If the UI says the **running server needs an update**, the new page is connected to an older Python process; this does not mean the CSV moved. Stop the old server in its terminal after any active experiment completes, then run `python server.py` again in the same environment and directory. **Retry preview** retries the dataset request after a restart.

If the updated API instead reports that the **source CSV is missing at its saved location**, restore that original CSV path or start a new experiment with the new location. Existing result snapshots are still readable independently of the source data.

## Research and deployment scope

This is a local, single-user application bound to `127.0.0.1`; it has no remote authentication or public hosting. Dataset paths refer to files on the server computer. CSV uploads are stored on that computer, and the Dataset viewer displays source records only when explicitly opened. Raw datasets are not included in the release or screenshots. Results and rankings remain aggregate outputs from the existing pipeline.

Network modes and timing scenarios stay separate. The v7 pipeline excludes unverified SSH evidence. Simulated comparisons remain provisional; scores, retention and clinical screening are not clinical acceptance. Receiver recovery remains locally measured. During execution, checkpoint status and logs update live; consolidated measurement tables appear after report generation. Table views cap loaded CSV rows at 20,000 and phase displays at 200; downloadable files remain complete.

## Validation

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
npm run build
```

For browser tests, start the server with a valid existing output root and a Python environment containing all pipeline dependencies. Then:

```bash
npm run test:ui
```

The tests use installed Chrome at `/usr/bin/google-chrome` (override with `CHROME_PATH`). Set `DASHBOARD_BASE_URL` to test a separate server port. They cover navigation, phase views, ranking filters, modal focus, mobile layout, downloads, dataset pagination, CSV uploads, four-pair expansion, old-server diagnostics and all three coverage options. The integration test uploads a generated synthetic CSV, runs the real pipeline at 80% patient coverage with simulated networking, checks the saved criterion and downloads the final report; allow a few minutes. It never requests SSH. Screenshots are written to `test-results/`.

Backend tests use temporary files and a fake subprocess runner to cover timestamped history, JSON-safe metrics, status aggregation, launch validation, completion, cancellation, single-job limits and HTTP download/origin rules. See `VALIDATION.md` for the completed checks.

## Project structure

```text
src/main.jsx           React views, filters, charts and controls
src/inspection.jsx     Dataset previews and expandable phase records
src/styles.css         Responsive visual design
server.py              Local API, report reader and process manager
public/demo.json       Sanitized synthetic result fixture
public/demo-*.json     Synthetic dataset and phase-detail fixtures
tests/                 Python API and Playwright browser tests
vite.config.js         React build and development API proxy
```

The existing pipeline directory and its v7 ZIP are not modified by this app.

## SSH interruptions and resume

Strict SSH experiments now expose port, remote directory, maximum attempts and transfer deadline under **Connection and recovery settings**. Transient failures show connection/retry progress; terminal failures show **Needs attention**. Correct the problem, then choose **Retry / Resume** to retain the same job, saved config, output directory and completed valid checkpoints. Failed benchmark units repeat in full. No simulation is substituted. API version 3 requires restarting an older Python server.

See [the SSH recovery and thesis-methodology guide](README_SSH_RECOVERY.md). Successful SCP timings, failed-attempt costs and overall delivery wall times have different meanings. Rankings retain the successful-delivery timing basis. The update preserves PCA/AE and clinical-screen algorithms.

See [New experiment controls](README_EXPERIMENT_OPTIONS.md) for required fields, optional settings, defaults and TOPSIS weights.

## Optional autoencoder GPU execution

See [README_AE_ACCELERATION.md](README_AE_ACCELERATION.md) for GPU setup, batch-size controls, live epoch progress, measured timing/quality tradeoffs and validation. CPU remains the default. Restart the dashboard server after an active experiment finishes to load the new controls.

## Running the complete thesis comparison

Select **New experiment → Use thesis experiment settings** and enter the dataset, SSH destination and installed server decoder path. Review the GPU setting for the machine doing the training. **Results & rankings** shows separate Phase 2 tables for the adaptive benchmark and the four-block baseline, the clean/interrupted archive results, and a transport selector for the final seven-criterion rankings. The phase inspector gives the individual follow-up trials for new experiments. Historical results show the evidence available in their own snapshot. See [the experiment protocol](../thesis_unified/README_RSYNC.md#full-thesis-experiment).

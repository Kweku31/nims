# v7 validation results

## Experiment controls and equal/custom TOPSIS — 2026-11-18

- All 62 pipeline tests passed, including equal default weights, custom-profile selection, percentage parsing (including 1% and zero), selected-profile sensitivity, and forwarding AE tolerance/patience to the unchanged engine.
- All 21 dashboard backend tests passed. Optional settings are validated before process creation; defaults, explicit percentage units, custom missingness cutoffs, protected fields, trial counts and custom weights are saved correctly.
- All 12 browser tests passed, including mandatory/optional labels, conditional SSH fields, equal/custom weight entry, invalid totals, reset behaviour, historical-report downloads and a complete uploaded synthetic experiment. That experiment saved custom weights and edited packaging/trial/AE settings, then selected the custom profile in Results & rankings.
- The separate simulated pipeline completed 18 packages, 36 evidence rows and 216 ranking rows (four built-in profiles, including equal). It verified checkpoint reuse and two distinct timestamped report snapshots, with no real SSH calls.
- The original profiling, selection, PCA/AE/clinical-screen and utility-engine hashes still match `ssh_algorithm_preservation.sha256`.
- The separate Beamer/TikZ template compiles to exactly one PDF page without overfull-box warnings and was visually inspected. It is included in the combined update ZIP.

Evidence: `validation_v7/experiment_options_tests.log`, `experiment_options_synthetic.log`, and `experiment_options_synthetic_summary.json`; dashboard logs `experiment_options_api_tests.log` and `experiment_options_ui_tests.log`. Initial development checks caught an expected profile-count assertion, a test indentation error and an unavailable temporary import fixture; these were corrected before the final passing runs. The idle user dashboard was reloaded with its existing environment after validation; no research experiment was restarted.

## Aligned Phase 2/6 repetition — 2026-11-18

- All 58 pipeline tests passed. New Phase 6 checks cover the exact 10-second boundary, subsequent slow transfers, partial-report rejection, inconsistent counts/thresholds/checksums, and eligibility of a complete slow one-trial result.
- All 18 dashboard backend tests and the targeted experiment-form browser check passed; production assets rebuilt. Testing used an isolated localhost server, which was stopped afterward.
- The local SSH/SCP stand-in pipeline completed five Phase 2 artifacts with 10 trials each and ten Phase 6 packages with 10 trials each. Two injected network failures recovered. Completeness and ranking checks passed. The standalone summary accepted all ten packages and 100 Phase 6 trials.
- The simulated pipeline completed 18 packages, 36 evidence rows and 162 ranking rows; checkpoint resume and two distinct timestamped snapshots passed. No real SSH host was contacted by either synthetic test.
- Profiling, selection, PCA/AE/clinical-screen and utility hashes still match `ssh_algorithm_preservation.sha256`.

Evidence: `validation_v7/aligned_repetition_tests.log`, `aligned_repetition_pipeline.log`, `aligned_repetition_summary.json`, `aligned_repetition_simulation.log`, `aligned_repetition_simulation_summary.json`, and `aligned_repetition_standalone.log`. Earlier sections describe the checks performed before Phase 6 was aligned.

## Phase 2 adaptive trials — 2026-11-18

All 53 pipeline tests passed, including the below/equal/above-10-second boundary in SSH and simulation modes, later slow trials, failure propagation, fallback policy forwarding, separate Phase 6 counts, and invalid settings. The full synthetic pipeline using local SSH/SCP stand-ins completed five Phase 2 artifacts with 10 trials each and ten Phase 6 packages with one trial each (configured independently for the smoke test). Two injected network failures recovered successfully. Metadata records the threshold and separate counts. No real SSH host was contacted. Logs and summary are `validation_v7/phase2_repetition_tests.log`, `phase2_repetition_pipeline.log`, and `phase2_repetition_summary.json`.

Dashboard validation: all 18 backend tests passed, the production build succeeded, and the targeted browser experiment-form test passed against an isolated localhost server. The backend tests required localhost socket access; the initial restricted-sandbox socket error was resolved by rerunning with that access. The user's running dashboard and research jobs were not restarted.

## Remote directory naming — 2026-11-18

- All 49 unit/regression tests passed (`validation_v7/remote_naming_tests.log`). Naming coverage checks readable filenames, UTC timestamps, unique retry directories, safe characters, bounded length, checksum-failure non-publication, and interrupted-upload retention using local command stand-ins.
- The six-phase synthetic SSH-path test passed with 10 Phase 6 packages and two injected connection resets, one in Phase 2 and one in Phase 6. No real SSH host was contacted. Five Phase 2 (including the standardized CSV baseline) plus ten Phase 6 verified directories and two unverified interrupted directories had the expected filename/status/timestamp names. See `validation_v7/remote_naming_pipeline.log` and `remote_naming_summary.json`.
- All five entries in `ssh_algorithm_preservation.sha256` still match, including the PCA/AE and clinical-screen engine.

## Initial validation

Validated on 2026-11-13 with Python 3.12. The dependency versions used for the final run are recorded in `validation_v7/dependency_versions.txt`.

| Check | Result |
|---|---|
| Existing test suite before edits | 24 tests passed |
| Final suite (existing + v7 regressions) | 38 tests passed |
| Real six-phase synthetic execution | Passed |
| Synthetic cohort | 64 rows, 16 generated patients; no real patient data |
| Feature sets | Original and FS-95 clinical review |
| Lossless formats | gzip, zstd, Parquet |
| Reduced representations | PCA and AE, k=2; native, gzip and zstd NPZ codecs |
| Completed packages | 18 of 18; zero package failures |
| Delivery evidence | 36 rows across `fresh_data` and `existing_payload` |
| Rankings | 162 rows, finite scores, explicitly provisional simulated evidence |
| Resume | Every non-final phase checkpoint reused unchanged; final reports regenerated |
| Timestamped report publication | Two distinct six-report folders; first snapshot unchanged after resume |
| Network | Zero real SSH/SCP attempts; preflight mocked to raise and executable sentinels installed |
| Phase 2 TOPSIS | Completed and resumed, including the expanding Parquet representation |
| Preserved research engines | SHA-256 matches the pre-edit versions; see `validation_v7/algorithm_preservation.sha256` |

At the initial v7 release, only `topsis_transfer_decision.py` changed among the legacy engines. The SSH recovery follow-up below additionally changes transport in Phase 2 and Phase 6. The initial hash file is retained as a historical baseline; `ssh_algorithm_preservation.sha256` checks the still-unchanged profiling, feature-selection, PCA/AE/clinical-screen and utility engines.

Report-publication regressions check that subsequent runs keep the previous six-report snapshot, identical timestamps still produce distinct folders, the status file points to the completed snapshot, and copy failures do not publish partial directories.

## Reproduce

From `thesis_unified/`:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tests/synthetic_pipeline_v7.py --output-dir /tmp/thesis-v7-smoke-new
python build_v7_release.py
```

Use a new output directory for the synthetic test. The test automatically executes the pipeline twice to validate checkpoint reuse. Its short AE training budget tests execution and recovery, not convergence or clinical utility. Real SSH throughput and remote decoding were not tested.

The release includes the unit-test log, synthetic pipeline log, synthetic validation summary, dependency version list and preserved-engine hashes under `validation_v7/`. Expected failure messages inside the unit-test log come from tests that deliberately exercise error handling; the final suite result is `OK`.

The ZIP builder includes source, docs, config and tests only, verifies archive CRCs and every stored file against its original bytes, and emits `SHA256SUMS` inside the archive plus a sibling ZIP `.sha256`. Local datasets, generated run payloads and virtual environments are excluded.

During setup, a temporary disk-based dependency installation exhausted available space. That temporary environment was removed, and final validation used an isolated memory-backed environment. No project dependency environment or source dataset was modified.

## SSH recovery follow-up — validated 2026-11-15

- All 48 pipeline unit/regression tests passed: the existing 38 plus 10 SSH recovery tests.
- All 18 dashboard backend tests passed, including same-job resume, saved configuration retention, SSH input bounds and exclusion of a worker surviving a server restart.
- The real six-phase simulated pipeline completed 18 packages and resumed without recomputing valid completed phases. Both timestamped six-report snapshots remained intact. SSH/SCP sentinels recorded no network attempt.
- An additional full pipeline ran through the strict-SSH adapters using **local executable stand-ins**, with one deliberately failed Phase 2 upload and one deliberately failed Phase 6 upload. Both recovered. All 10 package trials had checked archive/sidecar bytes, published verified directories, separate recovery timings, and finite rankings. These fixtures exercise the SSH code path but **are not real SSH measurements** and must never be used as empirical thesis results.
- The transport regression suite checks bounded retry budgets/backoff, terminal authentication/host-key/storage/hash failures, sidecar corruption, keepalive options, actual local subprocess deadline termination, uncached preflight, incomplete journal reporting, and identical root/unified sending logic.
- PCA/AE, clinical screening, feature selection, profiling and utility engine SHA-256 digests still match the original baseline. Only SSH transport changed inside the Phase 2/6 scripts; root Phase 2 repetition rules were preserved.

Latest evidence: `validation_v7/ssh_all_tests.log`, `ssh_synthetic_pipeline.log`, `ssh_synthetic_summary.json`, `offline_ssh_pipeline.log`, `offline_ssh_summary.json`, `ssh_dependency_versions.txt` and `ssh_algorithm_preservation.sha256`. Initial v7 logs remain in place as historical records. Dashboard validation is documented separately in `thesis_dashboard/VALIDATION.md`.

Reproduce the extra offline test with:

```bash
python tests/synthetic_ssh_recovery.py --output-dir /tmp/new-offline-ssh-test
```

This test generates all data and replaces both SSH executables on PATH. Its remote directories are local temporary files. Real host authentication, production network interruptions and receiver-side decoding performance remain untested. The 10/15-iteration AE budgets in these smoke tests validate execution, not model convergence.

## Optional GPU autoencoder — validated 2026-11-18

- Full unit/regression suite: **69 tests, OK**, including one intentionally skipped hardware test in the ordinary CPU invocation (`acceleration_all_tests.log`).
- Hardware suite with `THESIS_TEST_GPU=1`: **all 7 tests passed** on the Quadro P2000. Covers CPU optimizer equivalence, tolerance/patience, unchanged CPU weights with progress enabled, configuration forwarding, explicit GPU failure before any pipeline work, float32 GPU equivalence and CPU-readable decoder arrays (`gpu_tests.log`).
- Complete GPU synthetic pipeline: **18 packages, 36 evidence rows, 216 ranking rows**, no real SSH attempts, checkpoint reuse, two distinct timestamped report snapshots and preservation of the earlier snapshot (`gpu_synthetic.log`, `gpu_synthetic_summary.json`). A test-only report read was made explicitly UTF-8 after an initial ASCII-locale failure; the complete pipeline/resume harness was rerun successfully.
- The main-directory Phase 4 GPU entry point also passed a separate synthetic payload/checksum/reconstruction smoke test (`gpu_standalone.log`). Standalone and bundled Phase 4 ASTs match.
- `acceleration_preservation.json` compares the previous release against this one: PCA, clinical-screen constants, input preparation, payload/receiver and evaluation definitions are unchanged. The AE wrapper, experiment dispatch and CLI changed intentionally. Earlier whole-file preservation hashes above describe the earlier release, not the modified Phase 4 wrapper.
- The five-epoch, cohort-sized synthetic throughput probe measured 55.72 s CPU/batch-256, 38.70 s CPU/batch-4096 and 27.02 s GPU/batch-4096. Larger batches had worse five-epoch reconstruction. See `gpu_benchmark.json`, `gpu_benchmark.log` and `README_AE_ACCELERATION.md`; these are not converged clinical-quality or isolated-system measurements.

Reproduce hardware checks from the unified directory with the GPU-capable Python environment:

```bash
THESIS_TEST_GPU=1 python -m unittest discover -s tests -p test_ae_acceleration.py -v
python tests/synthetic_pipeline_v7.py --ae-backend gpu --output-dir /tmp/new-gpu-smoke
```

CPU remains the default. GPU uses float32; hardware, precision and batch changes can alter convergence. The active user research job was not interrupted or switched to GPU. The live dashboard was not restarted while that job was running. See the dashboard validation document for UI/API checks.

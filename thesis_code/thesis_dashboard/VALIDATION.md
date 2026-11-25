# Dashboard validation — 2026-11-15

The dashboard was built and checked locally with Node 20.20.2, Python 3.12 and Chrome. Dependency versions are pinned in `package-lock.json`.

| Check | Result |
|---|---|
| React/Vite production build | Passed |
| Python backend regressions | 18 passed |
| Browser scenarios | 10 passed (SSH recovery follow-up) |
| Desktop and mobile visual inspection | Completed at 1280px and 390px widths |
| Mobile horizontal overflow | None in overview or history |
| Imported timestamped reports | Discovered, opened and downloaded successfully |
| Real experiment launched through React | Passed |
| Synthetic experiment | 64 generated rows, 16 patients; original and FS-95 datasets; PCA/AE k=2 |
| Transfer packages | 10 completed; simulated network only |
| Report download after completion | `FINAL_REPORT.md` downloaded through the UI |
| Browser upload and dataset preview | Passed; leading zeros preserved, pagination and record expansion verified |
| Phase 1 record drill-down | Four saved correlation pairs listed when the summary record is expanded |
| Patient coverage choices | 75%, 80% and 90% accepted and persisted; full uploaded synthetic run verified at 80% |
| Outdated-server error | Restart guidance is shown separately from a missing source CSV |
| Existing local experiment | Source checksum matched; preview returned 25 rows / 43 columns; all four saved pairs available |
| Research algorithms | PCA/AE, clinical-screen, feature-selection and utility engines unchanged; SSH transport updated |

The browser integration test generated and uploaded a CSV, previewed it, selected k=2, 10 AE iterations and 80% patient coverage, launched the real `run_thesis.py`, observed running and completed states, confirmed all six completed phase cards and 10 packages, checked `patient_coverage_min=0.8` in the final manifest, and downloaded the final report. The resulting reports were published in a timestamped folder under the isolated test dashboard data directory. No real SSH connection was requested. The low AE iteration budget was used only to test execution and UI integration.

Other browser checks covered comparison filters, full-fidelity lossless-only rankings, an empty configuration search, all phase navigation, mobile navigation, strict-SSH form controls and modal focus preservation across polling updates. The backend tests exercise controlled temporary subprocesses for start, completion and cancellation, plus timestamp discovery, finite JSON metrics and download/origin/host validation.

Validation artifacts were generated outside application data: screenshots are in `test-results/`; the latest temporary synthetic run is under `/tmp/thesis-dashboard-inspection-preview/`. They are not clinical evidence or user experiments. The release archive excludes runtime jobs, uploaded patient datasets, virtual environments and `node_modules`; it includes explicitly synthetic demo fixtures and the production build.

The user's existing localhost server was confirmed to be an older API, with no active experiment. It was restarted in the same Python environment and working directory. The updated API returned the original source preview with its checksum matching the completed run; no patient values were printed in validation output. Existing experiment files were preserved.

Live SSH throughput, authentication against a real remote host, multi-user deployment and remote decoding were not tested. They remain outside this local UI validation.

## SSH recovery validation

The follow-up adds strict-SSH settings, recovery banners, and Retry / Resume for the same saved experiment. Backend regressions confirm that configuration/output/checkpoints are retained, earlier errors are kept in invocation history, and a surviving worker prevents a duplicate launch after a dashboard restart. Static JSON files are served without double encoding.

The browser suite covers the connection/recovery fields and a mocked transition from Needs attention through Retry / Resume to Connection lost — retrying, preserving the experiment ID. The full uploaded synthetic experiment still runs without SSH. The local transport stand-ins and the pipeline's independent 48-test suite are documented in `../thesis_unified/VALIDATION_V7.md`.

Final logs: `ssh_api_validation.log` and `ssh_ui_validation.log`. Recovery scenarios deliberately use generated fixtures and mocked network state. The production build includes the controls, and the existing idle localhost dashboard was restarted with API version 3 while preserving its user experiment and upload files.

The final full browser run passed nine scenarios and exposed an overly exact test locator for the transfer-deadline field (its accessible label also contains help text). The locator was corrected and the failed scenario was rerun separately; all ten scenarios then had passing checks. The appended browser log preserves the initial failure and its successful rerun. No product behaviour was changed to satisfy the locator.
# Experiment controls follow-up — 2026-11-18

All 21 backend tests and all 12 browser tests passed. The browser suite covered required dataset/conditional SSH labels, optional defaults and reset, custom TOPSIS validation, report downloads and a full uploaded synthetic pipeline with edited packaging/trial/AE settings and custom weights. The final manifest and selected ranking profile matched the submitted settings. Production assets rebuilt successfully. See `experiment_options_api_tests.log` and `experiment_options_ui_tests.log`.

The final browser run used an isolated server and newly generated synthetic reports; the user's experiment history was not used for test mutations. The idle user dashboard was then reloaded with its previous launch environment. Earlier validation notes below are historical.


## GPU/AE controls — 2026-11-18

All 21 API tests passed, including saved GPU backend, batch, CPU-thread and progress
settings and invalid-value rejection (`acceleration_api_tests.log`). The production
frontend build passed. The browser suite passed 12 scenarios, including the new
CPU/GPU selection and reset controls; the full uploaded synthetic pipeline exceeded
its original 200-second UI wait while still progressing. Its backend later completed
successfully. The test wait was increased to 400 seconds (overall test budget 480)
for this loaded laptop, without changing assertions or product behavior. Rerunning
only that scenario passed, including saved settings, custom TOPSIS weights and all
six completed phases. Thus all 13 browser scenarios have passing validation; the log
preserves the timeout and successful targeted rerun (`acceleration_ui_tests.log`).

Browser tests used a separate temporary server on port 8774. The user's server and
active research experiment were not restarted or cancelled. New controls require a
server restart after that experiment finishes; the frontend detects an old server
and provides restart guidance. GPU training itself was tested by the seven-test
hardware suite and full synthetic pipeline in the unified project.

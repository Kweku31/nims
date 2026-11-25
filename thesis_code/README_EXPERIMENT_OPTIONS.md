# New experiment: required inputs and optional settings

Updated 18 November 2026. The dashboard saves the effective settings in each job's `config.json`; final output records normalized settings and weights in `run_manifest.json`. Existing saved runs retain their settings. Start a new experiment to change them; a running fit is not updated by editing the form.

## Required and conditional inputs

| Input | Requirement |
|---|---|
| Dataset CSV | Required: select, enter a local path or upload a CSV. |
| SSH destination | Required only in strict SSH mode; use `user@host`. Existing key authentication and a trusted host key are needed. |
| Custom TOPSIS weights | Required only when custom allocation is selected: seven finite nonnegative percentages totalling 100%. Zero is permitted. |
| Delivery scenarios | Defaults to both. If edited, at least one must remain selected. |

All other exposed inputs are optional overrides. Numeric fields are prefilled; clearing an optional numeric field restores its default. Blank eligibility limits impose no additional limit. A blank Phase 1 correlation override inherits the shared cutoff. Blank protected-column and sensitivity lists mean no additional columns or no sensitivity table, as their help text states. Invalid supplied values are rejected before the pipeline starts.

## Basic defaults

- PCA/AE component counts: 2, 4, 8 (comma-separated; other counts may be entered).
- AE maximum epochs: 500. This is a cap, with loss-based stopping controlled below.
- Feature sets: original input plus the clinical-review variant at the highest selected missingness cutoff; alternatively all variants.
- Patient coverage safeguard: 75%, with 80% and 90% available.
- Network: simulated by default; strict SSH never silently falls back to simulation.
- SSH port: 22; destination directory: `/tmp/thesis_transfer/phase6`; maximum attempts: 3; transfer deadline: 300 seconds.
- Additional NPZ codec comparisons: off.

## Equal and custom TOPSIS weights

The final seven-criterion TOPSIS decision now defaults to **exactly 1/7 for each criterion** (about 14.2857%). Custom percentages are entered before launch, validated by the API and saved as normalized fractions. A numeric vector totalling 100 is interpreted as percentages, including entries such as 1%; a vector totalling 1 is interpreted as fractions.

Criterion order: transmitted bytes (cost), effective delivery time (cost), reconstruction R² (benefit), top-5 neighbourhood overlap (benefit), predictor-column retention (benefit), observed-measurement retention (benefit), new clinical-screen violations (cost).

The dashboard initially selects the experiment's chosen profile, and the report's plausibility-threshold sensitivity table uses that profile. The manifest contains `primary_weight_profile` and `decision_weights`. Equal, balanced, transfer-priority and utility-priority profiles remain available as comparisons; a distinct custom vector adds a custom profile. If a custom vector matches an existing profile, that profile is selected without duplication. Historical runs keep their saved profiles. Constant criteria do not distinguish candidates; remaining active weights are renormalized.

Phase 2's separate three-criterion baseline TOPSIS still uses equal thirds. These final-decision controls do not silently alter that baseline.

## Optional control groups

### Packaging and transfer trials

Optional. Defaults retain three packaging measurements and the aligned one-or-10 transfer rule.

| Setting | Default | Meaning |
|---|---|---|
| Phase 2 packaging runs | 3 | Fixed repetitions of serialization/compression; does not repeat AE training. |
| Phase 2 maximum transfer trials | 10 | Total trials including the first when it meets the cutoff. |
| Phase 2 first-transfer cutoff (seconds) | 10 | If the first transfer exceeds this duration, stop after one trial. |
| Phase 6 maximum transfer trials | 10 | Total trials per prepared package; failure retries are separate. |
| Phase 6 first-transfer cutoff (seconds) | 10 | Uses successful SCP time, excluding verification and retry overhead. |

### Model training and utility evaluation

Optional. Change training budgets and sampling without changing the PCA/AE algorithms.

| Setting | Default | Meaning |
|---|---|---|
| AE loss improvement tolerance | 0.0001 | Absolute training-loss improvement required to reset the patience counter. |
| AE patience (epochs) | 20 | Training stops after more than this many consecutive epochs of insufficient improvement. |
| Random seed | 42 | Used for reproducible model fitting and sampling. |
| Maximum patients for distance evaluation | 200 | Samples distinct patients for distance and neighbourhood comparisons. |
| Neighbour counts | 5, 10 | Comma-separated positive counts. Include 5 because final TOPSIS uses top-5 overlap. |

### Feature-selection rules

Optional. Review correlation deletion and protected columns before changing them.

| Setting | Default | Meaning |
|---|---|---|
| Missingness cutoffs (%) | 80, 90, 95 | Comma-separated hourly missingness cutoffs. Clinical-only runs use the highest cutoff. |
| Correlation cutoff (%) | 95 | Absolute Pearson correlation; used by Phases 1 and 3. |
| Phase 1 correlation cutoff override (%) | blank / no override | Leave blank to use the shared correlation cutoff. |
| Correlated-field action | flag | Flag retains both fields; drop enables supported automatic removal, respecting protected fields. |
| Minimum paired observations | 200 | Minimum observation support before correlated fields may be removed. |
| Minimum paired patients | 30 | Minimum patient support before correlated fields may be removed. |
| Additional protected clinical columns | Lactate | Comma-separated column names. Blank means no additional clinical columns; structural protections remain. |

### Delivery timing scenarios

Optional. These settings determine which preparation costs enter the delivery comparison.

| Setting | Default | Meaning |
|---|---|---|
| Delivery scenarios | fresh_data, existing_payload | Select at least one. Existing payload excludes initial preparation costs from its score; it does not skip experimental training. |
| Assumed model reuse count | 1 | Fresh-data scoring divides training cost by this count. Use more than 1 only when reuse is part of the experiment. |

### Simulation settings

Optional; used only for simulated transfer timings.

| Setting | Default | Meaning |
|---|---|---|
| Simulated bandwidth (Mbps) | 100 | Idealized bandwidth, not measured SSH throughput. |

### Decision eligibility and sensitivity

Optional. Blank limits apply no extra gate; these are experimental limits, not clinical safety standards.

| Setting | Default | Meaning |
|---|---|---|
| Minimum predictor retention (%) | blank / no override | Require at least this share of original eligible predictor columns for loss-tolerant rankings. |
| Minimum observed-measurement retention (%) | blank / no override | Require at least this share of the original non-missing measurements. |
| Maximum new clinical-screen violations (%) | blank / no override | Exclude candidates above this rate in loss-tolerant rankings. |
| Clinical-screen sensitivity cutoffs (%) | 0, 0.1, 0.5, 1, 5 | Comma-separated cutoffs for the sensitivity report. Blank disables this optional report. |

### Additional SSH recovery settings

Optional. These supplement the destination, port, maximum attempts and transfer deadline above.

| Setting | Default | Meaning |
|---|---|---|
| Initial retry delay (seconds) | 2 | Exponential backoff between transient failures; zero disables waiting. |
| Connection timeout (seconds) | 15 | Deadline for establishing an SSH connection. |
| Remote command timeout (seconds) | 60 | Deadline for setup, checksumming and publication commands. |
| Keepalive interval (seconds) | 15 | Interval between SSH keepalive messages. |
| Missed keepalives before disconnect | 3 | Unanswered messages allowed before the connection is considered lost. |

### Execution behaviour

Optional. Independent failures remain recorded in the final report.

| Setting | Default | Meaning |
|---|---|---|
| Continue independent configurations after a failure | on | Allow other Phase 4/6 configurations to finish when one fails. |

## Trial counts and packaging

Phase 2 packaging remains a fixed repetition count (default 3), now editable in the form. Phase 2 and Phase 6 transfers each default to a maximum of 10 trials: if the first successful transfer exceeds its 10-second cutoff, only one trial is required. Changing one phase's maximum or cutoff does not silently change the other. Failure attempts are separate from benchmark trials. Repeating transfer trials does not repeat Phase 4 training.

## Applying the update

Restart the dashboard Python server to load the updated validation and settings capability flags, then refresh the page. The interface shows restart guidance when connected to an older backend instead of accepting settings it would ignore. The v7 update archive includes the compiled React assets and the shared optional-setting schema. No real SSH connection is required for the automated tests.

The separate `thesis_slides/flowchart.tex` is a one-slide Beamer/TikZ flowchart template, accompanied by its compiled PDF and editing instructions.

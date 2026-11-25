#!/usr/bin/env bash
# Phase 6: package and benchmark real SSH/SCP transfers of existing Phase 4 outputs.
# Run inside the thesis_code folder with the thesis virtualenv activated.
# Requires 06_transfer_package.py and 06_phase6_ssh_summary.py in this folder.
# Defaults: all two dataset versions; 3 lossless + 6 NPZ-native packages per dataset.
# Set CODECS=all to additionally compare gzip and zstd on the same uncompressed
# PCA/autoencoder representation (3 codecs for every k, rather than only native).
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

: "${REMOTE:?Set REMOTE to your SSH destination (user@host)}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/thesis_transfer/phase6}"
TRIALS="${TRIALS:-10}"
SSH_TRANSPORT="${SSH_TRANSPORT:-scp}"
REPEAT_THRESHOLD_SECONDS="${REPEAT_THRESHOLD_SECONDS:-10}"
SSH_PORT="${SSH_PORT:-22}"
SSH_MAX_ATTEMPTS="${SSH_MAX_ATTEMPTS:-3}"
SSH_TRANSFER_TIMEOUT="${SSH_TRANSFER_TIMEOUT:-300}"
DATASETS="${DATASETS:-both}"   # both | original | selected
CODECS="${CODECS:-native}"     # native | all
OUTPUT="${OUTPUT:-output/sepsis2019/phase6_ssh_$(date -u +%Y%m%d_%H%M%S)_UTC}"
PYTHON="${PYTHON:-python}"

ORIGINAL_RUN="output/sepsis2019/phase4_dev/sepsis_1000_raw_20261112_105003_962858_UTC"
SELECTED_RUN="output/sepsis2019/phase4_dev/selected_dataset_20261112_105438_194209_UTC"
ORIGINAL_CSV="sepsis_1000_raw.csv"
SELECTED_CSV="output/sepsis2019/phase3_feature_selection/sepsis_1000_raw_20261105_140050_771243_UTC/FS_95_clinical_review/selected_dataset.csv"

[[ "$TRIALS" =~ ^[1-9][0-9]*$ ]] || { echo 'TRIALS must be a positive integer' >&2; exit 2; }
[[ "$DATASETS" == both || "$DATASETS" == original || "$DATASETS" == selected ]] || { echo 'DATASETS must be both, original, or selected' >&2; exit 2; }
[[ "$CODECS" == native || "$CODECS" == all ]] || { echo 'CODECS must be native or all' >&2; exit 2; }
[[ -f 06_transfer_package.py && -f 06_phase6_ssh_summary.py ]] || { echo 'Place both Phase 6 Python scripts beside this shell script.' >&2; exit 2; }

mkdir -p "$OUTPUT"

# The send subcommand insists on trusted host key and noninteractive key authentication.
# This test checks those conditions once rather than starting a multi-run experiment
# that later fails for every file.
export THESIS_NETWORK_EVENTS="$(realpath "$OUTPUT")/network_events.jsonl"
export THESIS_NETWORK_STATUS="$(realpath "$OUTPUT")/network_status.json"
"$PYTHON" -m thesis_unified.thesis_pipeline.ssh_transport --remote "$REMOTE" \
    --ssh-port "$SSH_PORT" --ssh-max-attempts "$SSH_MAX_ATTEMPTS" \
    --ssh-transfer-timeout "$SSH_TRANSFER_TIMEOUT" --output-dir "$OUTPUT"

task() {
    local dataset_label="$1" experiment_dir="$2" source_csv="$3" method="$4" k="$5" codec="$6"
    local task_id="${dataset_label}_${method}_${k}_${codec}"
    local log="$OUTPUT/${task_id}_build.log"
    local archive report
    local -a build_cmd=("$PYTHON" 06_transfer_package.py build
       --phase4-run "$experiment_dir" --source-csv "$source_csv"
       --method "$method" --output-dir "$OUTPUT")
    if [[ "$method" == pca || "$method" == autoencoder ]]; then
        build_cmd+=(--k "$k" --codec "$codec")
    fi
    if [[ "$dataset_label" == selected ]]; then
        build_cmd+=(--full-reference-csv "$ORIGINAL_CSV" --feature-selection-label FS-95-C)
    fi
    printf '\n=== %s ===\n' "$task_id"
    "${build_cmd[@]}" | tee "$log"
    archive="$(sed -n 's/^PACKAGE CREATED: //p' "$log" | tail -n 1)"
    [[ -n "$archive" && -f "$archive" && -f "$archive.sha256" ]] || {
        echo "Missing built archive/sidecar for $task_id" >&2; exit 1;
    }
    "$PYTHON" 06_transfer_package.py verify "$archive"
    report="${archive%.tar}.transfer_trials.csv"
    "$PYTHON" 06_transfer_package.py send "$archive" \
        --remote "$REMOTE" --remote-dir "$REMOTE_DIR" --ssh-port "$SSH_PORT" \
        --ssh-max-attempts "$SSH_MAX_ATTEMPTS" --ssh-transfer-timeout "$SSH_TRANSFER_TIMEOUT" \
        --ssh-transport "$SSH_TRANSPORT" --trials "$TRIALS" --repeat-threshold-seconds "$REPEAT_THRESHOLD_SECONDS" --report-csv "$report"
}

run_dataset() {
    local label="$1" run="$2" csv="$3" method k codec
    [[ -d "$run" && -f "$csv" ]] || { echo "Missing Phase 4 run or CSV: $run / $csv" >&2; exit 1; }
    for method in gzip zstd parquet; do
        task "$label" "$run" "$csv" "$method" - native
    done
    for method in pca autoencoder; do
        for k in 2 4 8; do
            task "$label" "$run" "$csv" "$method" "$k" native
            if [[ "$CODECS" == all ]]; then
                for codec in gzip zstd; do
                    task "$label" "$run" "$csv" "$method" "$k" "$codec"
                done
            fi
        done
    done
}

if [[ "$DATASETS" == original || "$DATASETS" == both ]]; then
    run_dataset original "$ORIGINAL_RUN" "$ORIGINAL_CSV"
fi
if [[ "$DATASETS" == selected || "$DATASETS" == both ]]; then
    run_dataset selected "$SELECTED_RUN" "$SELECTED_CSV"
fi

"$PYTHON" 06_phase6_ssh_summary.py --reports-dir "$OUTPUT"
printf '\nDONE. All reports and summary are in: %s\n' "$OUTPUT"
printf 'NOTE: send timing covers SCP and remote SHA-256 only; remote unpack/reconstruction\n'
printf 'and Phase 4 fitting/encoding must be reported separately.\n'

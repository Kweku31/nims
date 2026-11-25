#!/usr/bin/env bash
# Generic Phase 6 package builder
# Builds and verifies packages; does not transfer over SSH.

set -Eeuo pipefail

usage() {
    cat <<'HELP'
Usage:
  bash 06_build_all_phase6_packages.sh \
    --phase5-metadata FILE [options]

  bash 06_build_all_phase6_packages.sh \
    --experiment LABEL PHASE4_RUN SOURCE_CSV \
    [--experiment LABEL PHASE4_RUN SOURCE_CSV ...] [options]

Options:
  --phase5-metadata FILE    Read Phase 4 runs from Phase 5
  --experiment LABEL RUN CSV
                            Add an experiment manually
  --output-dir DIR          Where to save packages
  --codecs native|all       Default: native
  --full-reference-csv FILE Optional full original dataset
  --dry-run                 Preview without building
  --help                    Show help
HELP
}

PYTHON="${PYTHON:-python}"
META=""
REFERENCE=""
CODECS="native"
DRY_RUN=0

OUTPUT="output/phase6_packages_$(date -u +%Y%m%d_%H%M%S)_UTC"

declare -a LABELS=()
declare -a RUNS=()
declare -a CSVS=()

while (($#)); do
    case "$1" in
        --phase5-metadata)
            META="$2"
            shift 2
            ;;
        --experiment)
            LABELS+=("$2")
            RUNS+=("$3")
            CSVS+=("$4")
            shift 4
            ;;
        --output-dir)
            OUTPUT="$2"
            shift 2
            ;;
        --codecs)
            CODECS="$2"
            shift 2
            ;;
        --full-reference-csv)
            REFERENCE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 2
            ;;
    esac
done

[[ "$CODECS" == native || "$CODECS" == all ]] || {
    echo "Invalid codec selection" >&2
    exit 2
}

[[ -f 06_transfer_package.py ]] || {
    echo "06_transfer_package.py not found" >&2
    exit 1
}

# Read experiment definitions automatically from Phase 5.
if [[ -n "$META" ]]; then
    [[ -f "$META" ]] || {
        echo "Metadata file not found: $META" >&2
        exit 1
    }

    TEMP_FILE=$(mktemp)
    trap 'rm -f "${TEMP_FILE:-}"' EXIT

    "$PYTHON" - "$META" > "$TEMP_FILE" <<'PY'
import json
import pathlib
import re
import sys

metadata = json.loads(pathlib.Path(sys.argv[1]).read_text())

for i, exp in enumerate(metadata["experiments"], 1):
    run = exp["phase4_run"]
    csv = exp["input_csv"]
    label = re.sub(
        r"[^a-zA-Z0-9_-]", "_",
        pathlib.Path(csv).stem
    ) + f"_{i:02d}"
    print(f"{label}\t{run}\t{csv}")
PY

    while IFS=$'\t' read -r label run csv; do
        LABELS+=("$label")
        RUNS+=("$run")
        CSVS+=("$csv")
    done < "$TEMP_FILE"

    if [[ -z "$REFERENCE" ]]; then
        REFERENCE=$("$PYTHON" - "$META" <<'PY'
import json
import sys
meta = json.load(open(sys.argv[1]))
print(meta.get("full_reference") or "")
PY
)
    fi
fi

((${#LABELS[@]} > 0)) || {
    echo "No experiments specified" >&2
    exit 1
}

if [[ -n "$REFERENCE" && ! -f "$REFERENCE" ]]; then
    echo "Reference CSV does not exist: $REFERENCE" >&2
    exit 1
fi

if ((DRY_RUN == 0)); then
    mkdir -p "$OUTPUT"
    printf 'experiment\tmethod\tk\tcodec\tarchive\n' \
        > "$OUTPUT/package_index.tsv"
fi

COUNT=0

build_package() {
    local label="$1"
    local run="$2"
    local csv="$3"
    local method="$4"
    local k="$5"
    local codec="$6"

    local -a cmd=(
        "$PYTHON" 06_transfer_package.py build
        --phase4-run "$run"
        --source-csv "$csv"
        --method "$method"
        --output-dir "$OUTPUT"
    )

    if [[ "$method" == pca || "$method" == autoencoder ]]; then
        cmd+=(--k "$k" --codec "$codec")
    fi

    if [[ -n "$REFERENCE" && "$csv" != "$REFERENCE" ]]; then
        cmd+=(--full-reference-csv "$REFERENCE")
    fi

    echo ""
    echo "Building: $label | $method | k=$k | $codec"

    if ((DRY_RUN)); then
        printf ' %q' "${cmd[@]}"
        printf '\n'
        COUNT=$((COUNT + 1))
        return
    fi

    local log="$OUTPUT/${label}_${method}_${k}_${codec}.log"

    "${cmd[@]}" | tee "$log"

    local archive
    archive=$(sed -n 's/^PACKAGE CREATED: //p' "$log" | tail -n 1)

    [[ -n "$archive" && -f "$archive" && -f "$archive.sha256" ]] || {
        echo "ERROR: Package or checksum missing" >&2
        exit 1
    }

    "$PYTHON" 06_transfer_package.py verify "$archive"

    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$label" "$method" "$k" "$codec" "$archive" \
        >> "$OUTPUT/package_index.tsv"

    COUNT=$((COUNT + 1))
}

# Process every experiment.
for ((i=0; i<${#LABELS[@]}; i++)); do
    label="${LABELS[i]}"
    run="${RUNS[i]}"
    csv="${CSVS[i]}"

    [[ -d "$run" ]] || {
        echo "Phase 4 directory missing: $run" >&2
        exit 1
    }

    [[ -f "$csv" ]] || {
        echo "Dataset missing: $csv" >&2
        exit 1
    }

    [[ -f "$run/phase4_metadata.json" ]] || {
        echo "Phase 4 metadata missing: $run" >&2
        exit 1
    }

    # Discover lossless baselines.
    for method in gzip zstd parquet; do
        case "$method" in
            gzip) file="source_csv_gzip6.csv.gz" ;;
            zstd) file="source_csv_zstd3.csv.zst" ;;
            parquet) file="source_parquet_zstd.parquet" ;;
        esac

        if [[ -f "$run/$file" && -f "$run/$file.sha256" ]]; then
            build_package "$label" "$run" "$csv" \
                "$method" "-" native
        else
            echo "SKIPPED: $label / $method (payload unavailable)"
        fi
    done

    # Discover all available PCA and autoencoder k values.
    for method in pca autoencoder; do
        for payload in "$run"/"${method}"_k*_transfer_payload.npz; do
            [[ -f "$payload" ]] || continue

            filename="${payload##*/}"
            k="${filename#${method}_k}"
            k="${k%_transfer_payload.npz}"

            [[ "$k" =~ ^[0-9]+$ ]] || continue

            [[ -f "$payload.sha256" ]] || {
                echo "Missing mandatory checksum: $payload" >&2
                exit 1
            }

            build_package "$label" "$run" "$csv" \
                "$method" "$k" native

            if [[ "$CODECS" == all ]]; then
                build_package "$label" "$run" "$csv" \
                    "$method" "$k" gzip

                build_package "$label" "$run" "$csv" \
                    "$method" "$k" zstd
            fi
        done
    done
done

echo ""
echo "----------------------------------------"
echo "Packages processed: $COUNT"
echo "Output directory: $OUTPUT"

if ((DRY_RUN == 0)); then
    echo "Package index: $OUTPUT/package_index.tsv"
fi

echo "No SSH transfers performed."

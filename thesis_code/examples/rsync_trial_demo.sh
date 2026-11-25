#!/usr/bin/env bash
# Run with: bash thesis_code/examples/rsync_trial_demo.sh
# Local sender and receiver, synthetic bytes only. Requires GNU timeout and rsync.
set -euo pipefail
export LC_ALL=C
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/sender" "$work/receiver"
cd "$work/sender"
dd if=/dev/urandom of=synthetic.bin bs=1M count=8 status=none
tar -cf demo.tar synthetic.bin
sha256sum demo.tar > demo.tar.sha256
# Local rsync defaults to whole-file copies. Request the delta algorithm for this demo.
options=(-t --no-whole-file --partial-dir=.rsync-partial --stats)
for trial in 01 02; do
    stamp=$(date -u +%Y%m%d_%H%M%S_UTC)
    pending="$work/receiver/demo_trial${trial}_unverified_${stamp}"
    final="$work/receiver/demo_trial${trial}_verified_${stamp}"
    mkdir -m 700 "$pending"
    if [[ "$trial" == 01 ]]; then
        # Slow only this attempt so the interrupt happens partway through the archive.
        status=0
        timeout -s INT 3 rsync "${options[@]}" --bwlimit=512 \
            demo.tar demo.tar.sha256 "$pending/" >/dev/null || status=$?
        [[ "$status" == 124 && -s "$pending/.rsync-partial/demo.tar" ]]
        stat --printf='Partial archive saved: %s bytes\n' "$pending/.rsync-partial/demo.tar"
    fi
    echo "Trial $trial"
    rsync "${options[@]}" demo.tar demo.tar.sha256 "$pending/"
    # Verify both files against sender hashes, then check the archive sidecar.
    cmp demo.tar.sha256 "$pending/demo.tar.sha256"
    (cd "$pending" && sha256sum --check demo.tar.sha256)
    mv -T -- "$pending" "$final"
    echo "Published $(basename "$final")"
done

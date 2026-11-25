#!/usr/bin/env python3
"""Summarize Phase 6 completed package_report.json and SSH trial reports.

Uses the Python standard library only. This is a descriptive summary, not a
statistical significance test or a measurement of remote unpack/reconstruction.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from thesis_unified.thesis_pipeline import ssh_transport
from pathlib import Path


def mean(rows: list[dict], field: str) -> float:
    return statistics.mean(float(r[field]) for r in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--reports-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.reports_dir
    combined_rows: list[dict] = []
    trials_all: list[dict] = []

    for report_path in sorted(root.glob('*.package_report.json')):
        pack = json.loads(report_path.read_text())
        prefix = report_path.name.removesuffix('.package_report.json')
        trial_path = root / (prefix + '.transfer_trials.csv')
        if not trial_path.is_file():
            print(f'SKIPPING package with no completed SSH report: {prefix}')
            continue
        paths = [trial_path]
        extra = trial_path.with_suffix('.rsync.csv')
        with trial_path.open(newline='') as stream:
            first = next(csv.DictReader(stream), {})
        if first.get('transport_selection') == 'both':
            if not extra.is_file():
                print(f'SKIPPING incomplete paired comparison: {prefix}')
                continue
            paths.append(extra)
        for trial_path in paths:
            with trial_path.open(newline='') as stream:
                trials = list(csv.DictReader(stream))
            if not trials:
                print(f'SKIPPING empty/interrupted trial report: {trial_path}')
                continue
            if trials[0].get('trial_policy') == ssh_transport.TRIAL_POLICY:
                try:
                    ssh_transport.validate_trial_report(trials, int(trials[0]['maximum_trials']),
                                                        float(trials[0]['repeat_threshold_seconds']))
                except (KeyError, ValueError, TypeError, OverflowError) as exc:
                    print(f'SKIPPING incomplete/inconsistent adaptive report: {trial_path}: {exc}')
                    continue
            if 'requested_trials' in trials[0] and any(int(row['requested_trials']) != len(trials) for row in trials):
                print(f'SKIPPING incomplete trial report: {trial_path}')
                continue
            if not all(str(row['remote_sha256_verified']).lower() == 'true' for row in trials):
                raise ValueError(f'At least one remote check failed: {trial_path}')
            sizes = {int(row['transmitted_bytes']) for row in trials}
            if sizes != {pack['total_transmitted_bytes']}:
                raise ValueError(f'Sent bytes differ from package report: {trial_path}')
            for row in trials:
                trials_all.append({'dataset': 'selected' if prefix.startswith('selected_dataset_') else 'original',
                                   'method': pack['method'], 'k': pack['k'],
                                   'codec': pack['codec'], **row})
            method = trials[0].get('transport_method', 'scp')
            times = [ssh_transport.trial_seconds(row) for row in trials]
            transfer_mean = statistics.mean(times)
            checksum_mean = mean(trials, 'remote_sha256_verification_seconds')
            transfer_stdev = statistics.stdev(times) if len(trials)>1 else 0.0
            successful_plus_checksum = round(mean(trials, 'total_send_and_remote_verify_seconds'), 6)
            scp_times = [float(row['scp_seconds']) for row in trials] if method == 'scp' else []
            combined_rows.append({
                'dataset': 'selected' if prefix.startswith('selected_dataset_') else 'original',
                'package_id': pack['package_id'],
                'method': pack['method'], 'k': pack['k'] or '', 'codec': pack['codec'],
                'original_csv_bytes': pack['source_csv_bytes'],
                'total_transmitted_bytes': pack['total_transmitted_bytes'],
                'size_reduction_vs_source_pct': round(100*(1-pack['total_transmitted_bytes']/pack['source_csv_bytes']),4),
                'package_seconds': pack['package_elapsed_seconds'],
                'n_ssh_trials': len(trials),
                'transport_method': method,
                'mean_transfer_seconds': round(transfer_mean,6),
                'mean_scp_seconds': round(statistics.mean(scp_times), 6) if scp_times else None,
                'stdev_scp_seconds': round(statistics.stdev(scp_times), 6) if len(scp_times) > 1 else (0.0 if scp_times else None),
                'mean_scp_plus_sha256_seconds': successful_plus_checksum if scp_times else None,
                'sum_package_scp_verify_seconds': round(pack['package_elapsed_seconds'] + statistics.mean(scp_times) + checksum_mean, 6) if scp_times else None,
                'stdev_transfer_seconds': round(transfer_stdev,6),
                'mean_remote_sha256_seconds': round(checksum_mean,6),
                'mean_successful_send_plus_sha256_seconds': successful_plus_checksum,
                'sum_package_transfer_verify_seconds': round(pack['package_elapsed_seconds']+transfer_mean+checksum_mean,6),
                'remote_checks_all_passed': True,
                'failed_attempts': sum(int(row.get('failed_attempts', 0)) for row in trials),
                'mean_recovery_overhead_seconds': mean(trials, 'recovery_overhead_seconds') if 'recovery_overhead_seconds' in trials[0] else None,
                'mean_delivery_wall_seconds': mean(trials, 'delivery_wall_seconds') if 'delivery_wall_seconds' in trials[0] else None,
            })
    if not combined_rows:
        raise ValueError(f'No completed package+SSH trial pairs in {root}')

    columns = list(combined_rows[0])
    comparison = root / 'phase6_ssh_comparison.csv'
    with comparison.open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns); writer.writeheader(); writer.writerows(combined_rows)
    trial_output=root / 'phase6_all_ssh_trials.csv'
    columns2=list(dict.fromkeys(key for row in trials_all for key in row))
    with trial_output.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns2); writer.writeheader(); writer.writerows(trials_all)
    print(f'Wrote {comparison} ({len(combined_rows)} package/transport measurements)')
    print(f'Wrote {trial_output} ({len(trials_all)} SSH trials)')
    for dataset in ('original','selected'):
        items=[r for r in combined_rows if r['dataset']==dataset and r['codec']=='native']
        if items:
            fastest=min(items,key=lambda r:r['mean_successful_send_plus_sha256_seconds'])
            smallest=min(items,key=lambda r:r['total_transmitted_bytes'])
            print(f"{dataset}: smallest native package = {smallest['method']} k={smallest['k']} ({smallest['total_transmitted_bytes']} bytes)")
            print(f"{dataset}: fastest successful send+checksum = {fastest['transport_method']} {fastest['method']} k={fastest['k']} ({fastest['mean_successful_send_plus_sha256_seconds']}s)")
    print('These are descriptive results, not conclusions about clinical utility or full receiver recovery.')


if __name__=='__main__':
    main()

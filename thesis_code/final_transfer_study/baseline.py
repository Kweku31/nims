"""Compare SCP and rsync on the five saved, unpackaged Chapter 4 baseline files."""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
from pathlib import Path
from statistics import median
import subprocess

from study import ROOT, digest, read, save, ssh, utc

SOURCE = ROOT / 'thesis_dashboard/data/jobs/job-c2cbe4fe79e3/output/runs/66c57caa1bd63d2ea403/_work/phase2/sepsis_20336_raw_20261119_174643'
# Recorded from the retained Phase 2 files. A newly compressed file can have
# the same data and a different digest (for example, a gzip timestamp).
FILES = {
    'Source CSV': ('original_sepsis_20336_raw.csv', 'ae673cd33e720ef07bb8391389d1a2f3ee6ca15419f9f6de99f7e93f2ac83852'),
    'Rewritten CSV': ('dataset.csv', '59ff1351a9b02bc7a8470f6f173207d65fdd3e1866c28baa8bed681d1860dfda'),
    'gzip': ('dataset.csv.gz', '7048e7c0cb11bde0c32bba315224bd33ee1e520a268700a33293bdc0a1c49e8e'),
    'Parquet': ('dataset.parquet', '025552302818e21d00b49f6f69569a896d85b49265d2a1fcaa65e22b22c9be12'),
    'Zstandard': ('dataset.csv.zst', '8ec7ebbeb9ae43d6f9dadbcc6496106dd25bde57706f6cf7614c91ccfc984641'),
}


def schedule():
    formats = list(FILES)
    for block in range(4):
        for position in range(len(formats)):
            index = (block + position) % len(formats)
            methods = ('rsync', 'scp') if (block + index) % 2 else ('scp', 'rsync')
            for order, method in enumerate(methods, 1):
                yield dict(id=f'b{block+1}_{index+1}_{method}', block=block+1,
                           format=formats[index], order=order, method=method)


def prepare(source, output):
    files = {}
    for label, (name, expected) in FILES.items():
        path = source.resolve() / 'artifacts' / name
        if digest(path) != expected:
            raise ValueError(f'Phase 2 file differs from reference: {name}')
        files[label] = dict(path=str(path), bytes=path.stat().st_size, sha256=expected)
    endpoint = read(source/'transfer_metadata.json')['remote_endpoint']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    folder = output.resolve()/stamp
    folder.mkdir(parents=True, exist_ok=False)
    save(folder/'protocol.json', dict(created=utc(), files=files, schedule=list(schedule()),
         remote=endpoint['user']+'@'+endpoint['host'], port=endpoint['port'],
         remote_dir=endpoint['remote_directory'].rstrip('/')+'/phase2_paired/'+stamp,
         settings=ssh.DEFAULTS, code_sha256={p.name:digest(p) for p in
         (Path(__file__), Path(ssh.__file__), Path(__file__).with_name('study.py'))}))
    return folder


def report(folder, protocol):
    rows = []
    for spec in protocol['schedule']:
        result = folder/(spec['id']+'.json')
        row = read(result) if result.exists() else {'state':'pending'}
        rows.append({**spec, **row})
    with (folder/'trials.tmp').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)
    (folder/'trials.tmp').replace(folder/'trials.csv')
    lines = ['# Phase 2 paired SSH baseline', '',
             'Four matched blocks per format. Times in seconds are medians of clean, SHA-256-verified pairs. '
             'The paired difference is rsync minus SCP. Wall time includes setup, checking and publication.', '',
             '| Format | Complete clean pairs | SCP send | rsync send | Paired send difference | Paired wall difference |',
             '|---|---:|---:|---:|---:|---:|']
    for label in FILES:
        pairs = []
        for block in range(1, 5):
            times = {r['method']:r for r in rows if r['format']==label and r['block']==block and
                     r['state']=='verified' and r['attempts']==1}
            if len(times)==2:
                pairs.append((times['scp'], times['rsync']))
        numbers = ['—'] * 4
        if pairs:
            numbers = [f'{median(values):.2f}' for values in (
                [s['successful_send_seconds'] for s,r in pairs], [r['successful_send_seconds'] for s,r in pairs],
                [r['successful_send_seconds']-s['successful_send_seconds'] for s,r in pairs],
                [r['delivery_wall_seconds']-s['delivery_wall_seconds'] for s,r in pairs])]
        lines.append('| '+' | '.join([label,str(len(pairs)),*numbers])+' |')
    lines += ['', 'Trial counts across the 40 scheduled deliveries', '']
    for state in ('pending','unknown','failed','verified'):
        lines.append(f"- {state.capitalize()} — {sum(r['state']==state for r in rows)}")
    (folder/'SUMMARY.tmp').write_text('\n'.join(lines)+'\n')
    (folder/'SUMMARY.tmp').replace(folder/'SUMMARY.md')
    return rows


def run(folder):
    with (folder/'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol = read(folder/'protocol.json')
        for path in (Path(__file__), Path(ssh.__file__), Path(__file__).with_name('study.py')):
            if digest(path) != protocol['code_sha256'][path.name]:
                raise ValueError(f'Study code changed: {path.name}')
        for label, file in protocol['files'].items():
            if digest(Path(file['path'])) != FILES[label][1] or file['sha256'] != FILES[label][1]:
                raise ValueError(f'Source changed: {label}')
        rows = report(folder, protocol)
        if any(r['state']=='pending' for r in rows):
            ssh.configure(protocol['settings'], folder)
            ssh.ssh(protocol['remote'], protocol['port'], 'command -v rsync && command -v sha256sum && uptime')
        for spec in protocol['schedule']:
            path = folder/(spec['id']+'.json')
            if path.exists():
                continue
            file = protocol['files'][spec['format']]
            record = dict(state='unknown', started=utc(), sha256=file['sha256'], file_bytes=file['bytes'])
            save(path, record)
            try:
                audit = ssh.deliver([Path(file['path'])], protocol['remote'], protocol['port'],
                                    protocol['remote_dir'], operation=spec['id'], method=spec['method'])
                if audit['payload_sha256'] != file['sha256'] or not audit['remote_sha256_verified']:
                    raise ValueError('Delivered file failed reference verification')
                record.update(audit, state='verified')
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                record.update(state='failed', error=ssh.error_text(exc))
            save(path, {**record, 'finished':utc()})
            rows = report(folder, protocol)
        if any(r['state']!='verified' or r['attempts']!=1 for r in rows):
            raise SystemExit('Incomplete clean comparison. See trials.csv for every scheduled delivery.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase2-run', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=ROOT/'output/phase2_paired')
    parser.add_argument('--resume', type=Path, help='Continue pending trials from this run directory')
    args = parser.parse_args()
    folder = args.resume or prepare(args.phase2_run, args.output)
    print('Baseline comparison directory:', folder, flush=True)
    run(folder)

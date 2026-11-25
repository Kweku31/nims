"""Prepare, run and report the Chapter 4 follow-up on three saved packages."""
import argparse
import ast
from collections import defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from thesis_unified.thesis_pipeline import ssh_transport as ssh

REFERENCE = ROOT/'thesis_dashboard/data/jobs/job-c2cbe4fe79e3/output/results/20261120_083420_390853_UTC_hy7dh134'
CONDITIONS = [('parquet', 'clean'), ('gzip', 'clean'), ('ae16', 'clean'), ('ae16', 'interrupted')]


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, data):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


def read(path):
    return json.loads(path.read_text())


def utc():
    return datetime.now(timezone.utc).isoformat()


def schedule():
    rows = []
    for s in range(4):
        for n in range(4):
            # Rotate conditions among positions as well as balancing transport order.
            idx = (s+n) % 4
            artifact, condition = CONDITIONS[idx]
            methods = ('scp','rsync') if (s+idx)%2 == 0 else ('rsync','scp')
            for order, method in enumerate(methods, 1):
                rows.append(dict(id=f's{s+1}_{n+1}_{method}', session=s+1, artifact=artifact,
                                 condition=condition, order=order, transport=method))
    return rows


def prepare(output, reference=REFERENCE):
    manifest = read(reference/'run_manifest.json')
    config = manifest['config']
    artifacts = {}
    with (reference/'01_integrated_evidence.csv').open() as f:
        for row in csv.DictReader(f):
            if (row['dataset'], row['delivery_scenario'], row['codec']) != ('original','existing_payload','native'):
                continue
            label = row['method']
            if label == 'autoencoder' and float(row['k']) == 16:
                label = 'ae16'
            if label not in ('ae16','gzip','parquet'):
                continue
            path = Path(row['archive'])
            sidecar = Path(str(path)+'.sha256')
            hashes = ast.literal_eval(row['artifact_sha256'])
            if label in artifacts or any(digest(p) != hashes[str(p)] for p in (path, sidecar)):
                raise ValueError(f'Duplicate or changed historical archive for {label}')
            subprocess.run([sys.executable, str(ROOT/'06_transfer_package.py'), 'verify', str(path)], check=True)
            artifacts[label] = dict(path=str(path), sha256=hashes[str(path)],
                                    sidecar_sha256=hashes[str(sidecar)], bytes=path.stat().st_size)
    if set(artifacts) != {'parquet','gzip','ae16'}:
        raise ValueError('Missing a Chapter 4 package')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    folder = output.resolve()/stamp
    folder.mkdir(parents=True, exist_ok=False)
    save(folder/'protocol.json', dict(created=utc(), source_run=manifest['run_id'],
         remote=config['remote'], port=config['ssh_port'],
         remote_dir=config['remote_dir'].rstrip('/')+'/final_transport/'+stamp,
         ssh_settings={k:config[k] for k in ssh.DEFAULTS}, packages=artifacts, schedule=schedule()))
    report(folder)
    print(folder)


@contextmanager
def copy_tools(real_ssh):
    # Only child file-copy programs see these wrappers. The same measurement
    # path is used for both transports and all conditions, including retries.
    old = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory(prefix='thesis-copy-') as tmp:
            source = Path(tmp)/'relay.py'
            shutil.copyfile(HERE/'copy_shell.py', source)
            source.chmod(0o700)
            for name in ('scp','rsync'):
                binary = shutil.which(name)
                if not binary:
                    raise FileNotFoundError(name)
                os.environ['STUDY_'+name.upper()] = binary
                (Path(tmp)/name).symlink_to(source)
            relay = Path(tmp)/'copy-ssh'
            relay.symlink_to(source)
            os.environ.update(STUDY_RELAY=str(relay), STUDY_SSH=str(real_ssh), PATH=tmp+':'+old['PATH'])
            yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def trial(folder, protocol, spec):
    artifact = protocol['packages'][spec['artifact']]
    path = folder / artifact['path']
    sidecar = Path(str(path)+'.sha256')
    if digest(path) != artifact['sha256'] or digest(sidecar) != artifact['sidecar_sha256']:
        raise ValueError(f'Source changed: {path.name}')
    trial_dir = folder/spec['id']
    trial_dir.mkdir(exist_ok=False)
    result = dict(started=utc(), state='unknown', verified=False)
    save(trial_dir/'result.json', result)
    ssh.configure(protocol['ssh_settings'], trial_dir)
    trace = trial_dir/'copy.jsonl'
    cutoff = artifact['bytes']//2 if spec['condition']=='interrupted' else 0
    os.environ.update(STUDY_TRACE=str(trace), STUDY_CUTOFF=str(cutoff))
    start = time.monotonic()
    try:
        measurement = ssh.deliver([path, sidecar], protocol['remote'], protocol['port'],
                                  protocol['remote_dir'], operation=spec['id'], method=spec['transport'])
        result.update(measurement, state='completed', verified=measurement['remote_sha256_verified'])
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result.update(state='failed', error=ssh.error_text(exc), delivery_wall_seconds=time.monotonic()-start)
        events = ssh.read_events(trial_dir/'network_events.jsonl')['events']
        if events and events[-1].get('status')=='needs_attention':
            for key in ('failed_attempts','delivery_wall_seconds','backoff_seconds'):
                result[key] = events[-1][key]
            result['attempts'] = events[-1]['attempt']
    copies = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    drops = [x for x in copies if x['event']=='controlled_drop']
    result['drop_bytes'] = drops[0]['bytes_forwarded'] if drops else None
    result['target_bytes'] = cutoff or None
    # A drop on a later connection after an unrelated first-attempt failure
    # does not qualify as the intended first-attempt intervention.
    events = ssh.read_events(trial_dir/'network_events.jsonl')['events']
    failures = [e for e in events if e['status'] in ('connection_lost','needs_attention')]
    first_drop = bool(drops and failures and 'study interrupted' in failures[0].get('error',''))
    result['condition_observed'] = (len(drops)==1 and first_drop) if cutoff else bool(copies and not drops and result.get('attempts')==1 and result.get('verified'))
    later = [x for x in copies if drops and x['event']=='copy_started' and x['unix_time']>drops[0]['unix_time']]
    result['drop_to_next_copy_seconds'] = later[0]['unix_time']-drops[0]['unix_time'] if later else None
    result['finished'] = utc()
    save(trial_dir/'result.json', result)
    return result


def report(folder):
    protocol = read(folder/'protocol.json')
    rows = []
    for spec in protocol['schedule']:
        path = folder/spec['id']/'result.json'
        data = read(path) if path.exists() else {'state':'unknown' if path.parent.exists() else 'pending'}
        package = protocol['packages'][spec['artifact']]
        row = {**spec,'archive_bytes':package['bytes'],'sha256':package['sha256'],**data}
        rows.append(row)
    render(folder, rows, protocol.get('measurement_mode', 'remote SSH'))


def render(folder, rows, mode):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['artifact'],row['condition'])].append(row)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with (folder/'trials.csv.tmp').open('w',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(folder/'trials.csv.tmp',folder/'trials.csv')
    lines = ['# Transfer study results', '', 'Measurement environment — '+mode, '',
             'Wall time ends at verified publication. The paired difference is rsync minus SCP in seconds. '
             'Negative values favour rsync. Counts cover all planned deliveries, including pending sessions.', '',
             '| Package | Condition | Transport | Scheduled | Pending | Unknown | Failed | Verified | Observed controlled drops | Verified under assigned condition |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    differences = []
    for (artifact,condition), group in groups.items():
        for method in ('scp','rsync'):
            subset = [r for r in group if r['transport']==method]
            counts = [sum(r['state']==s for r in subset) for s in ('pending','unknown','failed')]
            verified = sum(bool(r.get('verified')) for r in subset)
            drops = sum(r.get('drop_bytes') is not None for r in subset)
            observed = sum(bool(r.get('verified') and r.get('condition_observed')) for r in subset)
            lines.append(f'| {artifact} | {condition} | {method} | {len(subset)} | '+ ' | '.join(map(str,[*counts,verified,drops,observed]))+' |')
        deltas = []
        for session in sorted({r['session'] for r in group}):
            times = {r['transport']:r['delivery_wall_seconds'] for r in group if r['session']==session
                     and r.get('verified') and r.get('condition_observed')}
            if len(times)==2:
                deltas.append(times['rsync']-times['scp'])
                differences.append(f'| {artifact} | {condition} | {session} | {deltas[-1]:.3f} |')
        if deltas:
            differences.append(f'| {artifact} | {condition} | median ({len(deltas)} pairs) | {statistics.median(deltas):.3f} |')
    lines += ['', '| Package | Condition | Session | Paired difference (s) |','|---|---|---|---:|', *differences]
    out = folder/'SUMMARY.md'
    out.with_suffix('.tmp').write_text('\n'.join(lines)+'\n')
    os.replace(out.with_suffix('.tmp'),out)
    print(out)


def run_session(folder, session, note, protocol=None):
    if protocol is None:
        protocol = read(folder/'protocol.json')
    todo = [s for s in protocol['schedule'] if s['session']==session and not (folder/s['id']).exists()]
    if not todo:
        report(folder)
        return
    for package in protocol['packages'].values():
        p = folder / package['path']
        if digest(p)!=package['sha256'] or digest(Path(str(p)+'.sha256'))!=package['sidecar_sha256']:
            raise ValueError('Prepared input changed')
    ssh.configure(protocol['ssh_settings'], folder)
    real_ssh = shutil.which('ssh')
    if not real_ssh:
        raise FileNotFoundError('ssh')
    with copy_tools(real_ssh):
        probe = ssh.ssh(protocol['remote'], protocol['port'],
                        'command -v rsync && command -v sha256sum && uptime')
        with (folder/'sessions.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(session=session, started=utc(), note=note,
                        sender=platform.node(), local_load=os.getloadavg(),
                        receiver=protocol['remote'], receiver_preflight=probe.stdout.strip()))+'\n')
        for spec in todo:
            print(f"Starting {spec['id']} {spec['artifact']} {spec['condition']}",flush=True)
            trial(folder, protocol, spec)
            report(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    p = sub.add_parser('prepare', help='Prepare from an existing dashboard results snapshot')
    p.add_argument('--reference-results',type=Path,default=REFERENCE,
                   help='Results snapshot with run_manifest.json and 01_integrated_evidence.csv')
    p.add_argument('--output',type=Path,default=ROOT/'output/final_transport')
    sub.add_parser('pilot',help='Exercise actual copy clients with synthetic data and local receiver processes')
    for cmd in ('session','report'):
        p = sub.add_parser(cmd)
        p.add_argument('folder',type=Path)
        if cmd=='session':
            p.add_argument('number',type=int,choices=range(1,5))
            p.add_argument('--note',default='',help='Network type and observed session conditions')
    from publication import DEMO, add_commands, dispatch, offline_receiver
    add_commands(sub)
    args = parser.parse_args()
    if args.command in ('run','all','replay'):
        dispatch(args)
        return
    if args.command=='prepare':
        prepare(args.output, args.reference_results)
    elif args.command=='pilot':
        from pilot import run
        run()
    else:
        folder = args.folder.resolve()
        with (folder/'.study.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.command=='report':
                report(folder)
            else:
                protocol = read(folder/'protocol.json')
                if protocol.get('measurement_mode')==DEMO:
                    with offline_receiver(protocol) as local_protocol:
                        run_session(folder, args.number, args.note, local_protocol)
                else:
                    run_session(folder, args.number, args.note, protocol)


if __name__=='__main__':
    main()

"""Run the published paired designs on artifacts belonging to a new experiment."""
import argparse
import csv
from pathlib import Path
import subprocess

from baseline import schedule as baseline_schedule, report as baseline_report
from study import digest, read, report, run_session, save, schedule, ssh, utc


def run_baseline(folder, protocol):
    baseline_report(folder, protocol)
    ssh.configure(protocol['ssh_settings'], folder)
    pending = [s for s in protocol['schedule'] if not (folder/(s['id']+'.json')).exists()]
    if pending:
        ssh.ssh(protocol['remote'], protocol['port'], 'command -v rsync && command -v sha256sum && uptime')
    for s in pending:
        path = folder/(s['id']+'.json')
        source = protocol['files'][s['format']]
        record = dict(state='unknown', started=utc(), sha256=source['sha256'],file_bytes=source['bytes'])
        save(path,record)
        try:
            audit = ssh.deliver([Path(source['path'])],protocol['remote'],protocol['port'],
                                protocol['remote_dir'],operation=s['id'],method=s['method'])
            if audit['payload_sha256']!=source['sha256'] or not audit['remote_sha256_verified']:
                raise ValueError('Baseline digest mismatch')
            record.update(audit,state='verified')
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            record.update(state='failed',error=ssh.error_text(exc))
        save(path,{**record,'finished':utc()})
        baseline_report(folder,protocol)


def run(folder, request):
    kind=request['kind']
    protocol={**request,'schedule':list(baseline_schedule()) if kind=='baseline' else schedule()}
    saved=folder/'protocol.json'
    if saved.exists() and read(saved)!=protocol:
        raise ValueError('Saved follow-up protocol differs from the request')
    for artifact in protocol.get('files',protocol.get('packages',{})).values():
        path=Path(artifact['path'])
        if digest(path)!=artifact['sha256'] or path.stat().st_size!=artifact['bytes']:
            raise ValueError(f'Changed follow-up input: {path.name}')
        if 'sidecar_sha256' in artifact and digest(Path(str(path)+'.sha256'))!=artifact['sidecar_sha256']:
            raise ValueError('Changed archive sidecar')
    save(saved,protocol)
    if kind=='baseline':
        run_baseline(folder,protocol)
    elif kind=='archives':
        report(folder)
        for block in range(1,5):
            run_session(folder,block,'paired archive follow-up',protocol)
    else:
        raise ValueError('Unknown study')
    # Failed or uncertain deliveries remain in the denominator. The analysis
    # only uses matched pairs that meet the protocol.
    with (folder/'trials.csv').open() as f:
        rows=list(csv.DictReader(f))
    if len(rows)!=len(protocol['schedule']) or any(r['state']=='pending' for r in rows):
        raise RuntimeError('Follow-up schedule incomplete')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path)
    args=parser.parse_args()
    run(args.request.parent,read(args.request))

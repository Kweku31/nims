"""Portable input preparation, unattended measurement and report reproduction."""
import argparse
import csv
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import fcntl
from importlib import metadata
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from study import HERE, ROOT, digest, read, render, run_session, save, schedule, ssh

DEMO = 'synthetic data, local receiver processes'
REAL = 'remote SSH'
SOURCE_FILES = [
    '04_dimensionality_reduction_updated.py', '06_transfer_package.py', 'ae_runtime.py', 'dataset_sepsis.py',
    'thesis_unified/thesis_pipeline/__init__.py', 'thesis_unified/thesis_pipeline/ssh_transport.py',
    'thesis_unified/thesis_pipeline/legacy/ae_runtime.py',
    *['final_transfer_study/'+name for name in ('study.py','publication.py','copy_shell.py','pilot.py',
                                                'requirements.txt','chapter4_inputs.json','README.md')]
]
PUBLIC_FIELDS = ('state','verified','condition_observed','attempts','failed_attempts',
                 'delivery_wall_seconds','target_bytes','drop_bytes','drop_to_next_copy_seconds',
                 'successful_send_seconds','backoff_seconds','recovery_overhead_seconds',
                 'remote_sha256_verification_seconds','started','finished')


def synthetic_csv(path):
    import numpy as np
    rng = np.random.default_rng(42)
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['patient_id','time','SepsisLabel',*[f'x{i}' for i in range(24)]])
        for i, values in enumerate(rng.integers(-10000,10000,(8192,24))):
            writer.writerow([f's{i//8:05}',i%8,0,*values])


def build_packages(folder, dataset, device, demo):
    work = folder/'build'
    phase4 = work/'phase4'
    args = [sys.executable, str(ROOT/'04_dimensionality_reduction_updated.py'),str(dataset),
            '--output-dir',str(phase4),'--methods','autoencoder','--k','16',
            '--lossless-formats','gzip','parquet','--strict-lossless','--seed','42',
            '--ae-backend',device,'--ae-batch-size','4096','--ae-max-iter', '3' if demo else '500',
            '--ae-tol','0.0001','--ae-patience','20']
    subprocess.run(args,check=True)
    metadata_file, = phase4.glob('*/phase4_metadata.json')
    packages = {}
    for label in ('gzip','parquet','ae16'):
        destination = work/label
        method = ['autoencoder','--k','16'] if label=='ae16' else [label]
        subprocess.run([sys.executable,str(ROOT/'06_transfer_package.py'),'build','--source-csv',str(dataset),
                        '--phase4-run',str(metadata_file.parent),'--output-dir',str(destination),
                        '--method',*method],check=True)
        archive, = destination.glob('*.tar')
        packages[label] = dict(path=str(archive.relative_to(folder)),bytes=archive.stat().st_size,
                               sha256=digest(archive),sidecar_sha256=digest(Path(str(archive)+'.sha256')))
    with (metadata_file.parent/'phase4_comparison.csv').open() as stream:
        row, = csv.DictReader(stream)
    observed = {k:v for k,v in row.items() if k.startswith('autoencoder_')}
    return packages, observed


def reference_packages(directory, expected):
    packages = {}
    for label, spec in expected.items():
        matches = list(directory.rglob(spec['filename']))
        if len(matches)!=1:
            raise ValueError(f"Expected one {spec['filename']} under {directory}, found {len(matches)}")
        archive = matches[0].resolve()
        if digest(archive)!=spec['sha256'] or digest(Path(str(archive)+'.sha256'))!=spec['sidecar_sha256']:
            raise ValueError('Chapter 4 digest mismatch for '+label)
        packages[label] = {**spec,'path':str(archive)}
    return packages


def environment():
    versions = {}
    for package in ('numpy','pandas','scipy','scikit-learn','pyarrow','threadpoolctl','cupy-cuda11x'):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
    for name, argv in [('openssh',['ssh','-V']),('rsync',['rsync','--version'])]:
        result = subprocess.run(argv,capture_output=True,text=True,check=True)
        versions[name]=(result.stdout or result.stderr).splitlines()[0]
    return dict(python=platform.python_version(),platform=platform.platform(),versions=versions,
                code_sha256={name:digest(ROOT/name) for name in SOURCE_FILES})


def prepare_run(args):
    expected = read(HERE/'chapter4_inputs.json')
    demo = not (args.dataset or args.set_a or args.packages)
    if demo and (args.remote or args.ae_backend):
        raise ValueError('For an SSH run supply --dataset, --set-a or --packages')
    if not demo:
        ssh.bases(args.remote,args.ssh_port)
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',args.remote_dir) or '..' in Path(args.remote_dir).parts:
            raise ValueError('--remote-dir must be an absolute safe POSIX directory')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    folder = args.output.resolve()/stamp
    folder.mkdir(parents=True)
    print('Study directory:',folder,flush=True)
    device = args.ae_backend or ('cpu' if demo else 'gpu')
    if args.packages:
        if args.ae_backend:
            raise ValueError('Archive reuse does not train an autoencoder')
        packages = reference_packages(args.packages, expected['packages'])
        origin = 'original Chapter 4 archives'
    else:
        dataset = args.dataset or folder/('synthetic.csv' if demo else 'sepsis_20336_raw.csv')
        if demo:
            synthetic_csv(dataset)
        elif args.set_a:
            from dataset_sepsis import consolidate
            consolidate(args.set_a, dataset)
        if not demo and digest(dataset)!=expected['csv_sha256']:
            raise ValueError('Combined CSV differs from the published Training Set A checksum')
        packages, observed = build_packages(folder,dataset.resolve(),device,demo)
        origin = 'seeded synthetic CSV' if demo else 'rebuilt from Training Set A'
    provenance = dict(origin=origin, csv_sha256=expected['csv_sha256'] if args.packages else digest(dataset),
                      **environment())
    if not args.packages:
        provenance['training'] = dict(backend=device,k=16,seed=42,batch_size=4096,max_epochs=3 if demo else 500,
                                      patience=20,tolerance=0.0001,observed=observed)
    save(folder/'protocol.json',dict(measurement_mode=DEMO if demo else REAL, provenance=provenance,
         remote=args.remote or 'pilot@local',port=args.ssh_port,remote_dir=args.remote_dir.rstrip('/')+'/'+stamp,
         packages=packages,schedule=schedule(),block_gap_seconds=args.block_gap_seconds,ssh_settings={**ssh.DEFAULTS,'ssh_retry_delay':0 if demo else 2.0}))
    return folder


@contextmanager
def offline_receiver(protocol):
    from pilot import LOCAL_SERVER
    candidates = [Path('/usr/lib/openssh/sftp-server'),Path('/usr/libexec/openssh/sftp-server')]
    sftp = next((str(p) for p in candidates if p.is_file()),shutil.which('sftp-server'))
    if not sftp:
        raise RuntimeError('Install OpenSSH sftp-server for the offline run')
    old = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory(prefix='study-local-') as tmp:
            remote = str(Path(tmp)/'receiver')
            host = Path(tmp)/'ssh'
            host.write_text('#!'+sys.executable+'\n'+LOCAL_SERVER)
            host.chmod(0o700)
            os.environ.update(STUDY_PILOT_REMOTE=remote, STUDY_SFTP=sftp, PATH=tmp+':'+old['PATH'])
            yield {**protocol,'remote':'pilot@local','remote_dir':remote}
    finally:
        os.environ.clear()
        os.environ.update(old)


def public_rows(folder, protocol):
    rows = []
    for spec in protocol['schedule']:
        path = folder/spec['id']/'result.json'
        result = read(path) if path.is_file() else {'state':'unknown' if path.parent.exists() else 'pending'}
        package = protocol['packages'][spec['artifact']]
        rows.append({**spec,'archive_bytes':package['bytes'],'sha256':package['sha256'],
                     **{k:result[k] for k in PUBLIC_FIELDS if k in result}})
    return rows


def publication(folder, protocol):
    public = folder/'reference'
    public.mkdir(exist_ok=True)
    rows = public_rows(folder,protocol)
    mode = protocol.get('measurement_mode',REAL)
    evidence = dict(schema=1, measurement_mode=mode, observations=rows,
                    block_gap_seconds=protocol.get('block_gap_seconds',0), ssh_settings=protocol['ssh_settings'],
                    packages={k:{f:p[f] for f in ('sha256','sidecar_sha256','bytes')}
                              for k,p in protocol['packages'].items()},
                    provenance=protocol.get('provenance',{'origin':'previously prepared study'}))
    save(public/'observations.json',evidence)
    render(public,rows,mode)
    names = ['observations.json','trials.csv','SUMMARY.md']
    save(public/'checksums.json',{name:digest(public/name) for name in names})
    target = folder/'final_transfer_reproduction.zip'
    with zipfile.ZipFile(target.with_suffix('.tmp'),'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in SOURCE_FILES:
            z.write(ROOT/name,name)
        for name in [*names,'checksums.json']:
            z.write(public/name,'reference/'+name)
    os.replace(target.with_suffix('.tmp'),target)
    print('Publication ZIP:',target,flush=True)
    return rows


def block_delay(folder, protocol, session):
    gap = protocol.get('block_gap_seconds',0)
    if not gap or session==1:
        return 0
    previous_end = []
    for spec in protocol['schedule']:
        path = folder/spec['id']/'result.json'
        if spec['session']==session and path.parent.exists():
            return 0  # This block has already started.
        if spec['session']==session-1 and path.exists():
            record = read(path)
            previous_end.append(datetime.fromisoformat(record.get('finished') or record['started']).timestamp())
    return max(0, max(previous_end)+gap-time.time()) if previous_end else 0


def run_all(folder, gap_override=None):
    with (folder/'.study.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        protocol = read(folder/'protocol.json')
        if protocol['schedule']!=schedule():
            raise ValueError('Expected the published 32-position schedule')
        if gap_override is not None and protocol.get('block_gap_seconds',0)!=gap_override:
            if any((folder/s['id']).exists() for s in protocol['schedule']):
                raise ValueError('Block spacing must be selected before the first trial')
            protocol['block_gap_seconds']=gap_override
            save(folder/'protocol.json',protocol)
        if 'provenance' not in protocol:
            started = any((folder/s['id']).exists() for s in protocol['schedule'])
            protocol['provenance'] = dict(origin='previously prepared study', environment_recorded_at=(
                'continued run' if started else 'first automated block'), **environment())
            expected = read(HERE/'chapter4_inputs.json')
            if all(protocol['packages'][k]['sha256']==p['sha256'] for k,p in expected['packages'].items()):
                protocol['provenance']['csv_sha256'] = expected['csv_sha256']
            save(folder/'protocol.json',protocol)
        for name, value in protocol['provenance']['code_sha256'].items():
            if digest(ROOT/name)!=value:
                raise ValueError('Study code has changed since preparation: '+name)
        print('Study directory:',folder,flush=True)
        local = protocol.get('measurement_mode')==DEMO
        with offline_receiver(protocol) if local else nullcontext(protocol) as effective:
            for session in range(1,5):
                delay = block_delay(folder, protocol, session)
                if delay:
                    print(f'Waiting {delay:.1f} seconds for block {session}', flush=True)
                    time.sleep(delay)
                run_session(folder,session,'automated four-block schedule',effective)
        rows = publication(folder,protocol)
        if any(r['state']!='completed' or not r.get('condition_observed') for r in rows):
            raise SystemExit('Study recorded incomplete or off-protocol observations. See the published counts.')


def replay(reference, output):
    hashes = read(reference/'checksums.json')
    evidence_file = reference/'observations.json'
    if digest(evidence_file)!=hashes['observations.json']:
        raise ValueError('Published observations failed SHA-256 verification')
    evidence = read(evidence_file)
    rows = evidence['observations']
    if evidence['schema']!=1 or [{k:r[k] for k in s} for r,s in zip(rows,schedule(),strict=True)]!=schedule():
        raise ValueError('Unexpected observations or schedule')
    folder = output.resolve()
    folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        work = Path(tmp)
        render(work,rows,evidence['measurement_mode'])
        for name in ('trials.csv','SUMMARY.md'):
            if digest(work/name)!=hashes[name]:
                raise ValueError('Replay differed from published '+name)
        for name in ('trials.csv','SUMMARY.md'):
            os.replace(work/name,folder/name)
    print('Exact replay verified:',folder)


def nonnegative_seconds(value):
    seconds = int(value)
    if seconds<0:
        raise argparse.ArgumentTypeError('Block gap must be nonnegative')
    return seconds


def add_commands(sub):
    p = sub.add_parser('run',help='Build or verify inputs, run four balanced blocks and publish the measurements')
    inputs = p.add_mutually_exclusive_group()
    inputs.add_argument('--dataset',type=Path,help='Combined Chapter 4 CSV')
    inputs.add_argument('--set-a',type=Path,help='Directory of original Training Set A patient PSV files')
    inputs.add_argument('--packages',type=Path,help='Directory containing the original three Chapter 4 archives and sidecars')
    p.add_argument('--block-gap-seconds',type=nonnegative_seconds,default=0)
    p.add_argument('--remote',help='SSH user@host used for real measurements')
    p.add_argument('--remote-dir',default='/tmp/final_transport')
    p.add_argument('--ssh-port',type=int,default=22)
    p.add_argument('--ae-backend',choices=['cpu','gpu'])
    p.add_argument('--output',type=Path,default=Path('output/final_transport'))
    p=sub.add_parser('all',help='Complete all remaining blocks of an existing study and produce its publication ZIP')
    p.add_argument('folder',type=Path)
    p.add_argument('--block-gap-seconds',type=nonnegative_seconds)
    p=sub.add_parser('replay',help='Recalculate published table and summary and verify their SHA-256 hashes')
    p.add_argument('--reference',type=Path,default=ROOT/'reference')
    p.add_argument('--output',type=Path,default=Path('replayed_results'))


def dispatch(args):
    if args.command=='run':
        run_all(prepare_run(args))
    elif args.command=='all':
        run_all(args.folder.resolve(), args.block_gap_seconds)
    else:
        replay(args.reference,args.output)

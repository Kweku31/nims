"""Phase 6: verified packages, local receiver checks, real SCP or tagged simulation.

Every configuration is independent and checkpointed by the orchestrator.
"""
from __future__ import annotations

import gzip
import json
import functools
import importlib.util
import sys
import shutil
import subprocess
import statistics
import shlex
import tempfile
import time
from pathlib import Path

import pandas as pd

from . import ssh_transport
from .core import legacy_run, load_json, ssh_preflight, sha256, LEGACY

@functools.lru_cache(maxsize=1)
def _decoder_module():
    path = LEGACY / '04_dimensionality_reduction_updated.py'
    spec = importlib.util.spec_from_file_location('thesis_phase4_decoder',path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CODECS = {'gzip':'source_csv_gzip6.csv.gz',
          'zstd':'source_csv_zstd3.csv.zst',
          'parquet':'source_parquet_zstd.parquet'}


REMOTE_MARKER = 'THESIS_RECEIVER_RESULT_JSON='


def reconstruct_on_server(trials: pd.DataFrame, archive: Path, expected_rows: int,
                          remote: str, port: int, config: dict) -> dict:
    """Run receiver code via SSH against the last verified SCP trial.

    Receiver script and matching thesis decoder must already be installed on
    the server. The sender's original source file is never used for recovery.
    """
    if trials.empty or not trials['remote_sha256_verified'].eq(True).all():
        raise RuntimeError('Server reconstruction requires verified SSH trials')
    receiver_script = config.get('remote_receiver_script')
    if not receiver_script:
        raise ValueError('Set --remote-receiver-script to the absolute server script path')
    target_dir = str(trials.iloc[-1]['remote_directory'])
    receiver_archive = target_dir.rstrip('/') + '/' + archive.name
    recover_dir = target_dir.rstrip('/') + '/receiver_recovery'
    python_binary = config.get('remote_python', 'python3')
    args = [python_binary, receiver_script,
            '--archive', receiver_archive,
            '--output-dir', recover_dir,
            '--expected-rows', str(expected_rows)]
    ssh_base, _ = ssh_transport.bases(remote, port)
    timeout = int(config.get('remote_reconstruction_timeout', 900))
    result = ssh_transport.command([*ssh_base, shlex.join(args)], timeout=timeout)
    markers = [line[len(REMOTE_MARKER):] for line in result.stdout.splitlines()
               if line.startswith(REMOTE_MARKER)]
    if len(markers) != 1:
        raise RuntimeError('Receiver returned no unique result marker: ' + result.stdout[-1500:])
    report = json.loads(markers[0])
    package_id = load_json(archive.with_suffix('.package_report.json'))['package_id']
    if (report.get('receiver_execution_role') != 'receiver_host' or
        report.get('receiver_recovery_passed') is not True or
        report.get('receiver_package_sha256_verified') is not True or
        report.get('reconstructed_rows') != expected_rows or
        report.get('package_id') != package_id):
        raise RuntimeError('Remote receiver report failed provenance/row-count validation')
    for key in ('unpack_seconds_MEASURED_ON_SERVER',
                'reconstruct_or_decompress_seconds_MEASURED_ON_SERVER',
                'csv_write_seconds_MEASURED_ON_SERVER'):
        val = float(report[key])
        if not 0 <= val < float('inf'):
            raise ValueError('Invalid measured server time: ' + key)
    return report


def configurations(info: dict, config: dict):
    maximum = config.get('transfer_trials', 10)
    threshold = config.get('phase6_repeat_threshold_seconds', 10.0)
    required = ssh_transport.required_trials(0, maximum, threshold)
    first_seconds = None
    root = Path(info['run'])
    out = []
    for method, fname in CODECS.items():
        payload = root / fname
        if payload.exists() and (root / (fname+'.sha256')).exists():
            out.append((method, None, 'native'))
    codes = ('native','gzip','zstd') if config.get('compare_npz_codecs', False) else ('native',)
    for method in ('pca','autoencoder'):
        for payload in sorted(root.glob(f'{method}_k*_transfer_payload.npz')):
            try:
                k = int(payload.name.split('_')[1].removeprefix('k'))
            except (ValueError, IndexError):
                continue
            if not (root / (payload.name+'.sha256')).exists():
                raise FileNotFoundError(f'Phase 4 payload checksum missing: {payload}')
            out.extend((method,k,codec) for codec in codes)
    return out


def package_and_benchmark(label: str, info: dict, method: str, k: int | None,
                          codec: str, base: Path, config: dict) -> dict:
    maximum = config.get('transfer_trials', 10)
    threshold = config.get('phase6_repeat_threshold_seconds', 10.0)
    required = ssh_transport.required_trials(0, maximum, threshold)
    first_seconds = None
    root = Path(info['run'])
    source = Path(info['source'])
    requested = config.get('transfer_mode','auto')
    remote = config.get('remote')
    online = requested != 'simulated' and ssh_preflight(remote, int(config.get('ssh_port',22)))
    if requested == 'ssh' and not online:
        raise RuntimeError('Strict SSH requested but SSH preflight failed. No simulated fallback is permitted.')
    if requested != 'simulated' and not online and not config.get('fallback_simulated', True):
        raise RuntimeError('Phase 6 SSH preflight failed and simulation fallback is disabled.')
    slug = f'{label}_{method}_{"none" if k is None else k}_{codec}'
    root_out = base / slug
    root_out.mkdir(parents=True, exist_ok=True)
    cmd = ['build','--phase4-run',str(root),'--source-csv',str(source),
           '--method',method,'--output-dir',str(root_out),
           '--package-name',slug]
    if k is not None:
        cmd += ['--k',str(k),'--codec',codec]
    reference = config.get('_input_dataset')
    if reference and sha256(source) != sha256(Path(reference)):
        cmd += ['--full-reference-csv',str(reference), '--feature-selection-label',label]
    text = legacy_run('06_transfer_package.py',cmd,root_out/'build.log')
    matches = [x.split('PACKAGE CREATED:',1)[1].strip() for x in text.splitlines() if 'PACKAGE CREATED:' in x]
    if not matches:
        raise RuntimeError(f'Phase 6 builder did not emit package path: {slug}')
    archive = Path(matches[-1])
    if not archive.is_absolute():
        archive = (Path.cwd() / archive).resolve()
    if not archive.exists():
        raise FileNotFoundError(archive)
    report_file = archive.with_suffix('.package_report.json')
    report = load_json(report_file)
    t = time.perf_counter()
    legacy_run('06_transfer_package.py',['verify',str(archive)],root_out/'verify.log')
    local_check = time.perf_counter()-t

    receiver_mode = config.get('receiver_execution', 'local')
    if receiver_mode not in ('local', 'remote'):
        raise ValueError('receiver_execution must be local or remote')
    if receiver_mode == 'remote' and (requested != 'ssh' or not online):
        raise RuntimeError('Remote reconstruction requires explicit working SSH; simulation is not a receiver')
    unpack_time = decode_time = write_seconds = None
    local_receiver_verified = False
    server_report = None
    if receiver_mode == 'local':
        # Test that receiver can unpack and actually restore data, without needing
        # the original source. Temporary decoded CSV is deleted after validation.
        with tempfile.TemporaryDirectory(prefix='thesis_receiver_') as tmp:
            temp = Path(tmp)
            t = time.perf_counter()
            args = ['unpack',str(archive),'--output-dir',str(temp)]
            if k is not None:
                args += ['--recover-npz']
            legacy_run('06_transfer_package.py',args,root_out/'unpack.log')
            unpack_time = time.perf_counter()-t
            # Decoder is installed once at the receiver; module import is not
            # charged against the data-specific reconstruction time.
            decoder = _decoder_module() if k is not None else None
            t = time.perf_counter()
            if k is not None:
                rec = sorted(p for p in temp.rglob(f'{method}_k{k}_transfer_payload.npz')
                             if p.parent.name.endswith('_recovered'))
                if len(rec) != 1:
                    raise RuntimeError(f'Expected one recovered NPZ, found {len(rec)}')
                # Mandatory sidecar verified again by the Phase 4 decoder.
                decoder.verify_payload_checksum(rec[0], None)
                data = decoder.reconstruct_bundle(rec[0])
            else:
                mfiles = list(temp.rglob('manifest.json'))
                if not mfiles:
                    raise RuntimeError('No manifest in verified receiver output')
                manifest = load_json(mfiles[0]); payload = mfiles[0].parent / manifest['data_file']
                if method == 'gzip':
                    with gzip.open(payload,'rt',encoding='utf-8') as f:
                        data = pd.read_csv(f,low_memory=False)
                elif method == 'zstd':
                    try:
                        import zstandard as zstd
                    except ImportError:
                        if not shutil.which('zstd'):
                            raise RuntimeError('Missing zstandard Python module AND zstd executable')
                        dest = temp / 'decoded_zstd.csv'
                        with dest.open('wb') as out:
                            subprocess.run(['zstd','-q','-d','-c',str(payload)],stdout=out,check=True)
                        data = pd.read_csv(dest,low_memory=False)
                    else:
                        with payload.open('rb') as f:
                            with zstd.ZstdDecompressor().stream_reader(f) as reader:
                                data = pd.read_csv(reader,low_memory=False)
                elif method == 'parquet':
                    data = pd.read_parquet(payload)
            decode_time = time.perf_counter()-t
            if len(data) != int(load_json(root/'phase4_metadata.json')['rows']):
                raise AssertionError('Recovered row count differs from Phase 4 source')

        local_receiver_verified = True

    net_mode = 'ssh' if online else 'simulated_ideal'
    net_reason = '' if online or requested == 'simulated' else 'SSH unavailable; idealized simulation fallback'
    print(f'NETWORK: Phase 6 {slug} mode={net_mode}; requested={requested}; reason={net_reason or "none"}', flush=True)
    transfer_mean, remote_check_mean = None, None
    scp_median = scp_std = scp_p95 = None
    recovery_mean = delivery_wall_mean = failed_attempts = None
    trials_file = root_out / 'transfer_trials.csv'
    selection = config.get('ssh_transport', 'scp')
    primary = ssh_transport.methods(selection)[0]
    comparison_files = []
    if online:
        try:
            legacy_run('06_transfer_package.py',
                       ['send',str(archive),'--remote',remote,'--remote-dir',
                        config.get('remote_dir','/tmp/thesis_transfer/phase6'),
                        '--ssh-transport',selection, '--trials',str(maximum),
                        '--repeat-threshold-seconds',str(threshold),
                        '--ssh-port',str(config.get('ssh_port',22)),
                        '--report-csv',str(trials_file)],root_out/'transfer.log')
            trials = pd.read_csv(trials_file)
            required = ssh_transport.validate_trial_report(trials.to_dict('records'), maximum, threshold)
            if selection == 'both':
                other = trials_file.with_suffix('.rsync.csv')
                rsync_trials = pd.read_csv(other)
                ssh_transport.validate_trial_report(rsync_trials.to_dict('records'), maximum, threshold)
                if not rsync_trials.transport_method.eq('rsync').all() or not trials.transport_method.eq('scp').all():
                    raise ValueError('Transport labels do not match requested comparison')
                digests = set(trials.payload_sha256) | set(rsync_trials.payload_sha256)
                if digests != {sha256(archive)}:
                    raise ValueError('Transport trials must use the same Phase 6 archive')
                comparison_files.append(str(other))
            first_seconds = ssh_transport.cutoff_seconds(trials.iloc[0])
            times = trials['transfer_seconds'] if 'transfer_seconds' in trials else trials['scp_seconds']
            transfer_mean = float(times.mean())
            scp_median = float(times.median())
            scp_std = float(times.std(ddof=1)) if len(trials) > 1 else None
            scp_p95 = float(times.quantile(.95))
            remote_check_mean = float(trials.remote_sha256_verification_seconds.mean())
            recovery_mean = float(trials.recovery_overhead_seconds.mean())
            delivery_wall_mean = float(trials.delivery_wall_seconds.mean())
            failed_attempts = int(trials.failed_attempts.sum())
        except Exception as e:
            if requested == 'ssh' or not config.get('fallback_simulated',True):
                raise
            net_mode='simulated_ideal'
            net_reason=f'SSH transfer failed; no real trials mixed into ranking: {e}'[:300]
            print(f'WARNING: NETWORK FALLBACK Phase 6 {slug}: {net_reason}', flush=True)
    if net_mode != 'ssh':
        transfer_mean = report['total_transmitted_bytes']*8/(float(config.get('bandwidth_mbps',100))*1e6)
        remote_check_mean = None
        first_seconds = transfer_mean
        required = ssh_transport.required_trials(first_seconds, maximum, threshold)
        pd.DataFrame([{'trial':j+1,'network_mode':net_mode,
                       'transfer_seconds_SIMULATED_IDEAL':transfer_mean,
                       'remote_verified':False, 'requested_trials':required, 'maximum_trials':maximum,
                       'repeat_threshold_seconds':threshold, 'first_transfer_seconds':first_seconds,
                       'trial_policy':ssh_transport.TRIAL_POLICY} for j in range(required)]).to_csv(trials_file,index=False)

    if receiver_mode == 'remote':
        if net_mode != 'ssh':
            raise RuntimeError('Refusing to claim server reconstruction for simulated delivery')
        expected_rows = int(load_json(root / 'phase4_metadata.json')['rows'])
        server_report = reconstruct_on_server(trials, archive, expected_rows,
                                              remote, int(config.get('ssh_port', 22)), config)
        unpack_time = float(server_report['unpack_seconds_MEASURED_ON_SERVER'])
        decode_time = float(server_report['reconstruct_or_decompress_seconds_MEASURED_ON_SERVER'])
        write_seconds = float(server_report['csv_write_seconds_MEASURED_ON_SERVER'])
        print('RECEIVER: remotely reconstructed on university server; '
              f'rows={server_report["reconstructed_rows"]}; '
              f'unpack={unpack_time:.6f}s, reconstruct={decode_time:.6f}s, '
              f'persist={write_seconds:.6f}s', flush=True)
    local_total = (float(report['package_elapsed_seconds']) + local_check +
                   unpack_time + decode_time + (write_seconds or 0.0))
    # Do not call idealized simulation full end-to-end observed time.
    remote_verified = bool(net_mode == 'ssh' and online and
                           len(trials) == required and
                           trials['remote_sha256_verified'].eq(True).all()) if net_mode == 'ssh' else False
    result = {'dataset':label,'phase4_run_directory':str(root),'source':str(source),
              'method':method,'k':k,'codec':codec,'lossless':k is None,
              'package_id':report['package_id'],'archive':str(archive),
              'total_transmitted_bytes':int(report['total_transmitted_bytes']),
              'payload_bytes':int(report['payload_bytes']),
              'packaging_seconds':float(report['package_elapsed_seconds']),
              'verify_local_seconds':local_check,'unpack_seconds':unpack_time,
              'reconstruct_or_decompress_seconds':decode_time,
              'receiver_csv_write_seconds':write_seconds,
              'remote_verify_seconds':remote_check_mean,
              'transfer_seconds':transfer_mean,'network_mode':net_mode,
              'transfer_median_seconds_MEASURED':scp_median,
              'scp_median_seconds_MEASURED':float(trials.scp_seconds.median()) if remote_verified and primary == 'scp' else None,
              'transfer_std_seconds_MEASURED':scp_std,
              'scp_std_seconds_MEASURED':float(trials.scp_seconds.std(ddof=1)) if remote_verified and primary == 'scp' and len(trials)>1 else None,
              'transfer_p95_seconds_MEASURED':scp_p95,
              'scp_p95_seconds_MEASURED':float(trials.scp_seconds.quantile(.95)) if remote_verified and primary == 'scp' else None,
              'network_note':net_reason,
              'recovery_overhead_seconds':recovery_mean if net_mode == 'ssh' else None,
              'delivery_wall_seconds':delivery_wall_mean if net_mode == 'ssh' else None,
              'failed_attempts':failed_attempts if net_mode == 'ssh' else None,
              'end_to_end_with_network_recovery_seconds':local_total+delivery_wall_mean if net_mode == 'ssh' else None,
              'transport_selection':selection,'transport_method':primary if net_mode == 'ssh' else None,
              'transport_comparison_files':comparison_files,
              'network_time_basis': ('observed_'+primary.upper() if remote_verified else 'idealized_bytes_over_bandwidth'),
              'remote_sha256_verified': remote_verified,
              'remote_trials_completed':int(len(trials)) if net_mode == 'ssh' else 0,
              'remote_trials_requested':required,
              'remote_trials_maximum':maximum,
              'remote_repeat_threshold_seconds':threshold,
              'remote_first_transfer_seconds':first_seconds,
              'remote_trial_policy':ssh_transport.TRIAL_POLICY,
              'receiver_recovery_passed': bool(server_report['receiver_recovery_passed']) if server_report else local_receiver_verified,
              'checksum_passed':True,
              'receiver_verification_location': 'remote_ssh' if server_report else 'local',
              'remote_reconstructed_csv_path': server_report['reconstructed_csv_path'] if server_report else None,
              'remote_reconstructed_csv_sha256': server_report['reconstructed_csv_sha256'] if server_report else None,
              'remote_receiver_report': server_report,
              'end_to_end_seconds':local_total + transfer_mean + (remote_check_mean or 0),
              'trials_file':str(trials_file),
              'artifacts':[str(archive),str(archive)+'.sha256',str(report_file),str(trials_file),*comparison_files]}
    return result

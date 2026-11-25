"""Bounded, audited SSH delivery. No modelling or ranking algorithms live here."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

DEFAULTS = {'ssh_max_attempts': 3, 'ssh_retry_delay': 2.0,
            'ssh_connect_timeout': 15, 'ssh_command_timeout': 60,
            'ssh_transfer_timeout': 300, 'ssh_keepalive_interval': 15,
            'ssh_keepalive_count': 3}

TRIAL_POLICY = 'first_transfer_threshold'


def methods(selection):
    if selection not in ('scp', 'rsync', 'both'):
        raise ValueError('ssh_transport must be scp, rsync or both')
    return ('scp', 'rsync') if selection == 'both' else (selection,)


def trial_seconds(row):
    """Successful command duration for old reports, or recovery-inclusive cost."""
    if 'transfer_seconds' in row:
        return float(row['transfer_seconds'])
    return float(row['scp_seconds'])


def cutoff_seconds(row):
    if row.get('transport_method') and int(row.get('failed_attempts', 0)):
        return float(row['delivery_wall_seconds'])
    return trial_seconds(row)


def required_trials(first_seconds, maximum=10, threshold=10.0):
    """Apply the adaptive trial threshold to the supplied first observation."""
    if type(maximum) is not int or maximum < 1:
        raise ValueError('Maximum trials must be a positive integer')
    for value, name in ((first_seconds, 'First transfer time'), (threshold, 'Repeat threshold')):
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(name+' must be finite')
    if float(first_seconds) < 0 or float(threshold) <= 0:
        raise ValueError('First transfer time must be nonnegative and threshold positive')
    return 1 if float(first_seconds) > float(threshold) else maximum


def validate_trial_report(rows, maximum, threshold):
    """Fail closed on incomplete, unverified or inconsistent adaptive trial reports."""
    if not rows:
        raise ValueError('Empty SSH trial report')
    first = cutoff_seconds(rows[0])
    required = required_trials(first, maximum, threshold)
    if len(rows) != required:
        raise ValueError('Incomplete SSH trial report')
    for number, row in enumerate(rows, 1):
        if (row.get('trial_policy') != TRIAL_POLICY
                or str(row.get('remote_sha256_verified')).lower() != 'true'
                or float(row['trial']) != number
                or float(row['requested_trials']) != required
                or float(row['maximum_trials']) != maximum
                or float(row['repeat_threshold_seconds']) != threshold
                or float(row['first_transfer_seconds']) != first):
            raise ValueError('Inconsistent or unverified SSH trial report')
        required_trials(trial_seconds(row), maximum, threshold)  # Validate every timing.
    return required


def settings(config=None):
    values = {**DEFAULTS, **json.loads(os.environ.get('THESIS_SSH_SETTINGS', '{}'))}
    if config is not None:
        values.update({k: config[k] for k in DEFAULTS if k in config})
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        maximum = 10 if key == 'ssh_max_attempts' else 86400
        minimum = 0 if key == 'ssh_retry_delay' else 1
        if not minimum <= value <= maximum or (key != 'ssh_retry_delay' and int(value) != value):
            raise ValueError(f'{key} must be between {minimum} and {maximum}' + (' (integer)' if key != 'ssh_retry_delay' else ''))
    return values


def configure(config, directory):
    values = settings(config)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ['THESIS_SSH_SETTINGS'] = json.dumps(values)
    os.environ['THESIS_NETWORK_EVENTS'] = str(directory/'network_events.jsonl')
    os.environ['THESIS_NETWORK_STATUS'] = str(directory/'network_status.json')
    return values


def add_arguments(parser):
    parser.add_argument('--ssh-transport', choices=['scp', 'rsync', 'both'], help='SSH file transfer method (default scp)')
    for key, default in DEFAULTS.items():
        parser.add_argument('--'+key.replace('_', '-'), type=float if key == 'ssh_retry_delay' else int,
                            default=None, help=f'SSH recovery setting (default {default})')


def configure_args(args, directory):
    values = {k: getattr(args, k) for k in DEFAULTS if getattr(args, k, None) is not None}
    # Unified invocations inherit the experiment-wide audit destination.
    configure(values, Path(os.environ['THESIS_NETWORK_STATUS']).parent
              if os.environ.get('THESIS_NETWORK_STATUS') else directory)


def event(status, **fields):
    record = {'status': status, 'updated_utc': datetime.now(timezone.utc).isoformat(), **fields}
    for variable, append in (('THESIS_NETWORK_EVENTS', True), ('THESIS_NETWORK_STATUS', False)):
        target = os.environ.get(variable)
        if not target:
            continue
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with path.open('a') as stream:
                stream.write(json.dumps(record, allow_nan=False)+'\n')
        else:
            temp = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
            temp.write_text(json.dumps(record, allow_nan=False))
            os.replace(temp, path)
    print('NETWORK: '+json.dumps(record), flush=True)


def read_events(path):
    """A hard interruption may leave a truncated journal line; report it explicitly."""
    events, errors = [], []
    path = Path(path)
    if path.is_file():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                errors.append(f'Unreadable network audit record at line {number}')
    return {'events': events, 'errors': errors}


def command(argv, timeout):
    """Enforce a wall deadline and kill SSH's descendants on timeout/cancellation."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True,
                            env={**os.environ, 'LC_ALL': 'C'})
    def kill_group():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    def cancelled(signum, frame):
        kill_group()
        raise SystemExit(128+signum)
    handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            handlers[sig] = signal.signal(sig, cancelled)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group()
            proc.communicate()
            raise
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, argv, stdout, stderr)
        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    finally:
        if proc.poll() is None:
            kill_group()
            proc.wait()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def transient(exc):
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    if not isinstance(exc, subprocess.CalledProcessError):
        return False
    message = str(exc.stderr or '').lower()
    if any(s in message for s in ('permission denied', 'host key', 'identification has changed',
                                  'no space left', 'quota exceeded', 'not found', 'checksum')):
        return False
    return any(s in message for s in ('connection reset', 'connection unexpectedly closed', 'connection closed', 'connection timed out',
                                      'connection refused', 'broken pipe', 'network is unreachable',
                                      'no route to host', 'temporary failure in name resolution',
                                      'timeout, server', 'connection to', 'lost connection'))


def error_text(exc):
    if isinstance(exc, subprocess.TimeoutExpired):
        return f'Command exceeded its {exc.timeout}s deadline'
    return str(getattr(exc, 'stderr', None) or exc).strip()[-1500:]


def retry(operation, action, config=None):
    cfg = settings(config)
    total_start = time.perf_counter()
    failed_seconds = backoff_seconds = 0.0
    for attempt in range(1, int(cfg['ssh_max_attempts'])+1):
        event('connecting' if attempt == 1 else 'retrying', operation=operation, attempt=attempt,
              max_attempts=cfg['ssh_max_attempts'])
        start = time.perf_counter()
        try:
            result = action()
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            elapsed = time.perf_counter()-start
            failed_seconds += elapsed
            can_retry = transient(exc) and attempt < cfg['ssh_max_attempts']
            delay = min(cfg['ssh_retry_delay'] * 2**(attempt-1), 30) if can_retry else 0
            event('connection_lost' if can_retry else 'needs_attention', operation=operation,
                  attempt=attempt, max_attempts=cfg['ssh_max_attempts'], error=error_text(exc),
                  transient=transient(exc), failed_attempt_seconds=elapsed,
                  failed_attempts=attempt, cumulative_failed_attempt_seconds=failed_seconds,
                  backoff_seconds=backoff_seconds, recovery_overhead_seconds=failed_seconds+backoff_seconds,
                  delivery_wall_seconds=time.perf_counter()-total_start,
                  retry_in_seconds=delay, next_attempt=attempt+1 if can_retry else None)
            if not can_retry:
                raise
            tick = time.perf_counter()
            time.sleep(delay)
            backoff_seconds += time.perf_counter()-tick
        else:
            recovery = {'attempts': attempt, 'failed_attempts': attempt-1,
                        'failed_attempt_seconds': failed_seconds, 'backoff_seconds': backoff_seconds,
                        'recovery_overhead_seconds': failed_seconds+backoff_seconds,
                        'delivery_wall_seconds': time.perf_counter()-total_start}
            event('connected', operation=operation, **recovery)
            return result, recovery


def bases(remote, port, config=None):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9_][A-Za-z0-9_.-]*', remote or ''):
        raise ValueError('SSH requires a safe user@host destination')
    if isinstance(port, bool) or not 1 <= int(port) <= 65535:
        raise ValueError('SSH port must be between 1 and 65535')
    cfg = settings(config)
    options = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f"ConnectTimeout={int(cfg['ssh_connect_timeout'])}",
               '-o', f"ServerAliveInterval={int(cfg['ssh_keepalive_interval'])}",
               '-o', f"ServerAliveCountMax={int(cfg['ssh_keepalive_count'])}"]
    return ['ssh', '-p', str(port), *options, remote], ['scp', '-B', '-P', str(port), *options]


def ssh(remote, port, remote_command):
    cfg = settings()
    base, _ = bases(remote, port, cfg)
    result, _ = retry('ssh preflight/setup', lambda: command([*base, remote_command], cfg['ssh_command_timeout']), cfg)
    return result


def delivery_directories(files, remote_dir):
    """Readable, shell-safe, bounded directory names for one upload attempt."""
    payload = next((p for p in files if not p.name.endswith('.sha256')), files[0])
    label = re.sub(r'[^A-Za-z0-9_.-]+', '_', payload.name).strip('._-')[:140] or 'payload'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    suffix = stamp+'_'+uuid4().hex
    base = remote_dir.rstrip('/')+'/'+label
    return base+'_unverified_'+suffix, base+'_verified_'+suffix


def deliver(files, remote, port, remote_dir, operation='delivery', method='scp'):
    """Restart a whole failed trial; atomically publish a verified directory."""
    cfg = settings()
    ssh_base, scp_base = bases(remote, port, cfg)
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', remote_dir) or '..' in PurePosixPath(remote_dir).parts:
        raise ValueError('Remote directory must be an absolute safe POSIX path')
    files = [Path(p).resolve() for p in files]
    if not files or len({p.name for p in files}) != len(files):
        raise ValueError('Delivery requires files with distinct names')
    digests = []
    for path in files:
        with path.open('rb') as stream:
            digests.append(hashlib.file_digest(stream, 'sha256').hexdigest())
    if method not in ('scp', 'rsync'):
        raise ValueError('Select one transport per delivery')
    stable = None

    # If SSH loses the acknowledgement of a rename, retry the publication
    # idempotently, with the verified final path as proof of completion.
    def action():
        nonlocal stable
        pending, final = stable or delivery_directories(files, remote_dir)
        event('connecting', operation=operation, remote_pending_directory=pending,
              remote_verified_directory=final)
        q = shlex.quote
        if stable is None:
            command([*ssh_base, f'mkdir -p -- {q(remote_dir)} && mkdir -m 700 -- {q(pending)}'], cfg['ssh_command_timeout'])
            if method == 'rsync':
                stable = pending, final
        sender = scp_base if method == 'scp' else [
            'rsync', '--partial-dir=.rsync-partial', '-e', shlex.join(ssh_base[:-1]), '--']
        tick = time.perf_counter()
        command([*sender, *map(str, files), f'{remote}:{pending}/'], cfg['ssh_transfer_timeout'])
        send_seconds = time.perf_counter()-tick
        tick = time.perf_counter()
        result = command([*ssh_base, 'sha256sum -- '+' '.join(q(pending+'/'+p.name) for p in files)], cfg['ssh_command_timeout'])
        observed = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
        if observed != digests:
            raise RuntimeError('Remote SHA-256 mismatch; delivery remains unpublished')
        verify_seconds = time.perf_counter()-tick
        # A rename within this directory exposes the complete verified set together.
        publish = f'mv -T -- {q(pending)} {q(final)}'
        if method == 'rsync':
            try:
                command([*ssh_base, publish], cfg['ssh_command_timeout'])
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                if not transient(exc):
                    raise
                # A lost reply may mean the atomic rename already succeeded.
                check = 'if test -d '+q(final)+'; then sha256sum -- '+ ' '.join(
                    q(final+'/'+p.name) for p in files)+'; fi'
                reply = command([*ssh_base, check], cfg['ssh_command_timeout'])
                if not reply.stdout.strip():
                    raise
                if [line.split()[0] for line in reply.stdout.splitlines()] != digests:
                    raise RuntimeError('Published directory failed digest verification')
        else:
            command([*ssh_base, publish], cfg['ssh_command_timeout'])
        return {'transport_method': method, method+'_seconds': send_seconds,
                'successful_send_seconds': send_seconds, 'payload_sha256': digests[0], 'remote_sha256_verification_seconds': verify_seconds,
                'remote_sha256_verified': True, 'remote_directory': final,
                'total_send_and_remote_verify_seconds': send_seconds+verify_seconds}
    report, recovery = retry(operation, action, cfg)
    return {**report, **recovery, 'transfer_seconds': report['successful_send_seconds'] + recovery['recovery_overhead_seconds']}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Audited SSH preflight; never simulates a connection')
    parser.add_argument('--remote', required=True)
    parser.add_argument('--ssh-port', type=int, default=22)
    parser.add_argument('--output-dir', type=Path, default=Path('output/ssh_preflight'))
    add_arguments(parser)
    args = parser.parse_args()
    configure_args(args, args.output_dir)
    ssh(args.remote, args.ssh_port, 'true')

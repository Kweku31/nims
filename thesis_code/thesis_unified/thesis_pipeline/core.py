"""Shared provenance, checksums, subprocess execution, resumable stages and I/O.

The older research implementations in legacy/ remain untouched: shared plumbing
lives here, and phase adapters all use this module.
"""
from __future__ import annotations

import contextlib
import functools
import fcntl
import hashlib
import json
import logging
import threading
from contextvars import ContextVar
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
LEGACY = ROOT / 'legacy'



# Exactly one append-only, live log for the complete pipeline.  It deliberately
# lives outside checkpointed artifacts, so logging does not invalidate reuse.
_LOGGER = logging.getLogger('thesis.unified')
_LOGGER.propagate = False
_CURRENT_PHASE = ContextVar('thesis_phase', default='PIPELINE')
_CURRENT_RUN = ContextVar('thesis_run', default='initializing')
_CURRENT_LOG_FILE = ContextVar('thesis_log_file', default=None)


class _RecordContext(logging.Filter):
    def filter(self, record):
        record.phase = _CURRENT_PHASE.get()
        record.run_id = _CURRENT_RUN.get()
        return True


class _TeeStream:
    """Preserve the user's console text verbatim and log a copy to the file.

    Never send formatted log records to stdout/stderr.  Each completed line
    becomes one timestamped record only in pipeline.log.  A partial line is
    copied to the console immediately and logged on flush/stream exit.
    """
    def __init__(self, original, level: int):
        self.original = original
        self.level = level
        self.pending = ''
        self.encoding = getattr(original, 'encoding', 'utf-8')

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        self.original.write(text)  # Unchanged original terminal output.
        self.pending += text.replace('\r\n', '\n').replace('\r', '\n')
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            self._record(line)
        return len(text)

    def _record(self, line):
        if not line.strip():
            return
        level = self.level
        if line.startswith(('WARNING:', 'WARNING ', 'WARN:')):
            level = logging.WARNING
        elif line.startswith(('ERROR:', 'ERROR ', 'Traceback ', 'Traceback(')):
            level = logging.ERROR
        _LOGGER.log(level, line)

    def flush(self):
        self.original.flush()
        if self.pending:
            self._record(self.pending)
            self.pending = ''

    def isatty(self):
        return bool(getattr(self.original, 'isatty', lambda: False)())

    def __getattr__(self, name):
        return getattr(self.original, name)


@contextmanager
def phase_context(name: str):
    """Label everything in a stage, including child-process output."""
    token = _CURRENT_PHASE.set(name.upper())
    try:
        yield
    finally:
        _CURRENT_PHASE.reset(token)


def log_run_id(run_id: str):
    """Attach a stable checkpoint run identifier to every subsequent line."""
    _CURRENT_RUN.set(str(run_id))


def current_log_path() -> str | None:
    """Return the active consolidated log location for run metadata."""
    p = _CURRENT_LOG_FILE.get()
    return str(p) if p else None


@contextmanager
def unified_logging(file_path: Path):
    """Record full pipeline output in a separate append-only file.

    Console print/stderr text stays exactly as before unified logging.  The
    file gets UTC timestamps, run IDs and phase labels. The log file is made
    before phases start and lives OUTSIDE run-specific checkpoint directories.
    """
    log_path = Path(file_path).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    formatter = logging.Formatter(
        '%(asctime)s UTC | %(levelname)-7s | run=%(run_id)s | phase=%(phase)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    is_new_file = not log_path.exists()
    file_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
    if is_new_file:
        log_path.chmod(0o600)
    file_handler.setLevel(logging.INFO)
    file_handler.addFilter(_RecordContext())
    file_handler.setFormatter(formatter)
    previous_handlers = _LOGGER.handlers[:]
    previous_level = _LOGGER.level
    _LOGGER.handlers = [file_handler]  # IMPORTANT: no log formatter on console.
    _LOGGER.setLevel(logging.INFO)
    run_token = _CURRENT_RUN.set('initializing')
    phase_token = _CURRENT_PHASE.set('PIPELINE')
    file_token = _CURRENT_LOG_FILE.set(log_path)
    out, err = _TeeStream(original_stdout, logging.INFO), _TeeStream(original_stderr, logging.ERROR)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _LOGGER.info('===== PIPELINE INVOCATION START =====')
            _LOGGER.info('Unified log file: %s', log_path)
            try:
                yield log_path
            except BaseException:
                _LOGGER.exception('PIPELINE ABORTED')
                raise
            else:
                _LOGGER.info('===== PIPELINE INVOCATION END =====')
            finally:
                out.flush()
                err.flush()
    finally:
        file_handler.flush()
        file_handler.close()
        _LOGGER.handlers = previous_handlers
        _LOGGER.setLevel(previous_level)
        _CURRENT_PHASE.reset(phase_token)
        _CURRENT_RUN.reset(run_token)
        _CURRENT_LOG_FILE.reset(file_token)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for buf in iter(lambda: f.read(1024 * 1024), b''):
            h.update(buf)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='._atomic_',
                                     dir=path.parent, delete=False) as fh:
        json.dump(data, fh, indent=2, allow_nan=False, default=str)
        tmp = Path(fh.name)
    os.replace(tmp, path)


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def fingerprint(*values: Any) -> str:
    blob = json.dumps(values, sort_keys=True, separators=(',', ':'), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def find_new_run(parent: Path, required_file: str) -> Path:
    paths = [p for p in parent.iterdir() if p.is_dir() and (p / required_file).exists()]
    if not paths:
        raise FileNotFoundError(f'No {required_file} under {parent}')
    return max(paths, key=lambda p: p.stat().st_mtime_ns)


def subprocess_run(argv: list[str], log_file: Path, *, timeout: int | None = None,
                   env: dict | None = None) -> str:
    """Stream child output live to the console, unified log and phase log.

    Child Python processes are unbuffered so tail -f follows long-running
    operations rather than receiving only a seven-line summary at the end.
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(a) for a in argv]
    print('RUN:', shlex.join(argv), flush=True)
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    child_env['PYTHONUNBUFFERED'] = '1'
    lines = []
    with log_file.open('w', encoding='utf-8') as out:
        out.write('COMMAND: ' + shlex.join(argv) + '\n')
        out.flush()
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, encoding='utf-8', errors='replace',
                                env=child_env)
        timed_out = threading.Event()
        timer = None
        if timeout is not None:
            def kill_child():
                timed_out.set()
                proc.kill()
            timer = threading.Timer(timeout, kill_child)
            timer.daemon = True
            timer.start()
        try:
            for line in proc.stdout:
                out.write(line)
                out.flush()
                lines.append(line)
                print(line.rstrip('\n'), flush=True)
            return_code = proc.wait()
        finally:
            if timer:
                timer.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
    output = ''.join(lines)
    if timed_out.is_set():
        raise subprocess.TimeoutExpired(argv, timeout, output=output)
    if return_code:
        raise RuntimeError(f'Command failed ({return_code}). See {log_file}\n'+
                           '\n'.join(output.splitlines()[-15:]))
    return output


def legacy_run(script: str, args: list[str], log: Path) -> str:
    return subprocess_run([sys.executable, str(LEGACY / script), *map(str, args)], log)


def ssh_preflight(remote: str | None, port: int = 22) -> bool:
    if not remote or not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+', remote):
        return False
    from . import ssh_transport
    try:
        ssh_transport.ssh(remote, port, 'true')
        return True
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
        return False


def validate_artifacts(obj: Any, *, require_checksums: bool = False) -> bool:
    if isinstance(obj, dict):
        if 'artifacts' in obj:
            if require_checksums and set(obj['artifacts']) != set(obj.get('artifact_sha256', {})):
                return False
            if not all(Path(p).is_file() for p in obj['artifacts']):
                return False
            for path,digest in obj.get('artifact_sha256',{}).items():
                if not Path(path).is_file() or sha256(Path(path)) != digest:
                    return False
            return True
        return True
    return False


def code_fingerprints() -> dict[str, str]:
    """Use relative paths to avoid collisions between adapters and legacy files."""
    paths = [*ROOT.rglob('*.py'), ROOT.parent / 'run_thesis.py', ROOT.parent / 'receiver_reconstruct.py']
    hashes = {str(p.relative_to(ROOT.parent)): sha256(p) for p in sorted(paths)}
    companion = ROOT.parents[1]/'final_transfer_study'
    for name in ('study.py','baseline.py','copy_shell.py','new_experiment.py'):
        if (companion/name).is_file():
            hashes['../final_transfer_study/'+name]=sha256(companion/name)
    return hashes


def dependency_fingerprint(result: dict) -> str:
    """Capture content and stage generation, even when output paths are reused."""
    return fingerprint(result)


class Checkpoint:
    """A stage is reused only after full success and surviving artifact checks.

    A changed source/config/code yields a new run ID; steps resume in-place after
    interruptions. Output paths are recorded atomically when a step succeeds.
    """
    def __init__(self, base: Path, config: dict, dataset: Path, *, resume_run_id: str | None = None, phase6_replay_id: str | None = None):
        code_hashes = code_fingerprints()
        self.input_sha256 = sha256(dataset)
        computed_key = fingerprint(self.input_sha256, config, code_hashes)[:20]
        if phase6_replay_id is not None:
            # Explicit, audited receiver-only replay. Preserve original provenance:
            # runner/core may differ solely to add this orchestration; every research
            # stage implementation and decoder must still match byte-for-byte.
            if resume_run_id is not None or not re.fullmatch(r'[0-9a-f]{20}', phase6_replay_id):
                raise ValueError('Phase 6 replay requires one valid existing run ID')
            prior = Path(base) / 'runs' / phase6_replay_id / 'checkpoint.json'
            if not prior.is_file():
                raise RuntimeError(f'Existing Phase 6 replay checkpoint not found: {prior}')
            old = load_json(prior)
            if (old.get('run_id') != phase6_replay_id or old.get('input_sha256') != self.input_sha256
                    or old.get('config') != config):
                raise RuntimeError('Cannot replay Phase 6: original input or configuration has changed')
            old_hashes = old.get('code_sha256', {})
            acceptable = {'run_thesis.py', 'thesis_pipeline/core.py'}
            migration = load_json(ROOT.parent/'rsync_replay_hashes.json')
            if set(old_hashes) != set(code_hashes) or any(
                    old_hashes[k] != code_hashes[k] and migration.get(k) != [old_hashes[k], code_hashes[k]]
                    for k in code_hashes if k not in acceptable):
                raise RuntimeError('Cannot replay Phase 6: a pipeline implementation or decoder changed. '
                                   'Only the Phase 6 orchestration runner/core may differ.')
            computed_key = phase6_replay_id
        # Explicit resume must NEVER create another computational run.  A changed
        # dataset, option or source file is an error, not a cache miss.
        if resume_run_id is not None:
            if not re.fullmatch(r'[0-9a-f]{20}', resume_run_id):
                raise ValueError('Invalid --resume-run-id')
            if resume_run_id != computed_key:
                raise RuntimeError('Cannot resume: input, configuration or pipeline code changed. '
                                   'Restore the original environment or start a NEW experiment explicitly.')
            prior = Path(base) / 'runs' / resume_run_id / 'checkpoint.json'
            if not prior.is_file():
                raise RuntimeError(f'Cannot resume: checkpoint is absent: {prior}')
            old = load_json(prior)
            if (old.get('run_id') != resume_run_id or old.get('input_sha256') != self.input_sha256
                    or old.get('config') != config or old.get('code_sha256') != code_hashes):
                raise RuntimeError('Cannot resume: stored checkpoint provenance differs from this invocation')
        self.key = computed_key
        self.root = Path(base) / 'runs' / self.key
        self.work = self.root / '_work'
        self.results = self.root / 'results'
        self.work.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)
        self.state_file = self.root / 'checkpoint.json'
        self.state = load_json(self.state_file) if self.state_file.exists() else {'run_id': self.key, 'stages': {}}
        self.state['input_sha256'] = self.input_sha256
        self.state['config'] = config
        if phase6_replay_id is None:
            self.state['code_sha256'] = code_hashes
        else:
            # Never rewrite the hash used to establish the original experiment.
            self.phase6_replay_code_sha256 = code_hashes
        self._lock_fh = None

    def __enter__(self):
        self._lock_fh = (self.root / 'LOCK').open('w')
        fcntl.flock(self._lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, *args):
        if self._lock_fh:
            fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
            self._lock_fh.close()

    def stage(self, name: str, function, *, force: bool = False, dependencies: dict | None = None):
        with phase_context(name):
            prev = self.state['stages'].get(name, {})
            deps = dependencies or {}
            if (not force and prev.get('status') == 'complete'
                    and prev.get('dependencies',{}) == deps
                    and validate_artifacts(prev.get('result'), require_checksums=True)):
                print(f'SKIP {name}: verified completed checkpoint', flush=True)
                return prev['result']
            print(f'START {name}: ' + ('forced recomputation' if force else 'executing'), flush=True)
            generation = int(prev.get('generation', 0)) + 1
            self.state['stages'][name] = {'status': 'running', 'started_utc': utc_now(),
                                          'generation': generation}
            atomic_json(self.state_file, self.state)
            started = time.perf_counter()
            try:
                value = function()
                if not validate_artifacts(value):
                    raise RuntimeError(f'{name} did not return a valid artifact list')
                value['artifact_sha256'] = {p:sha256(Path(p)) for p in value['artifacts']}
                value['checkpoint_generation'] = generation
                elapsed = time.perf_counter()-started
                self.state['stages'][name] = {'status': 'complete', 'started_utc': self.state['stages'][name]['started_utc'],
                                              'completed_utc': utc_now(), 'seconds': elapsed,
                                              'dependencies':deps,'result': value, 'generation': generation}
                atomic_json(self.state_file, self.state)
                print(f'COMPLETE {name}: {elapsed:.3f}s', flush=True)
                return value
            except Exception as exc:
                self.state['stages'][name] = {'status': 'failed', 'error': str(exc), 'failed_utc': utc_now(),
                                              'generation': generation}
                atomic_json(self.state_file, self.state)
                print(f'ERROR: FAILED {name}: {type(exc).__name__}: {exc}', flush=True)
                raise


def as_fraction(value, *, name: str, allow_zero: bool = True) -> float:
    """Parse 75, '75%', or 0.75 as the same 0..1 fraction.

    Bare numbers in [0,1] are fractions, bare numbers in (1,100] are
    percentages. An explicit percent sign always denotes percent units.
    Thus '1%' is 0.01, whereas numeric 1 is 1.0 (100%).
    """
    import math
    if isinstance(value, bool):
        raise ValueError(f'{name}: Boolean is not a percentage')
    token = str(value).strip()
    explicit = token.endswith('%')
    try:
        x = float(token[:-1].strip() if explicit else token)
    except ValueError as exc:
        raise ValueError(f'{name}: expected a percentage such as 75, 75%, or 0.75') from exc
    if not math.isfinite(x):
        raise ValueError(f'{name}: percentage must be finite')
    if explicit or x > 1.0:
        x /= 100.0
    if not ((0.0 <= x <= 1.0) if allow_zero else (0.0 < x <= 1.0)):
        raise ValueError(f'{name}: must be in the range {"0..100%" if allow_zero else "(0,100]%"}')
    return x


def as_percent(value, *, name: str) -> float:
    """As above, but return percentage points in [0,100]."""
    return 100.0 * as_fraction(value, name=name)


def percentage_weights(values: list, *, name: str) -> list[float]:
    """Accept seven nonnegative weights that sum to 1 or 100%.

    Each entry may be a fraction (0.25), a whole percent (25), or '25%'.
    There must be at least one positive weight.
    """
    import math
    if not isinstance(values, (list, tuple)) or len(values) != 7:
        raise ValueError(f'{name}: expected exactly 7 weights (one per TOPSIS criterion)')
    if any(isinstance(x, bool) for x in values):
        raise ValueError(f'{name}: Boolean weights are not allowed')
    # Interpret numeric vectors as a whole so a 1% entry is not mistaken for 100%.
    if not any(isinstance(x, str) and x.strip().endswith('%') for x in values):
        try:
            weights = [float(x) for x in values]
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{name}: weights must be numeric') from exc
        if any(not math.isfinite(x) or x < 0 for x in weights):
            raise ValueError(f'{name}: weights must be finite and nonnegative')
        if math.isclose(sum(weights), 100., rel_tol=0, abs_tol=1e-5):
            weights = [x / 100 for x in weights]
    else:
        weights=[as_fraction(x, name=f'{name}[{i}]') for i,x in enumerate(values)]
    if not math.isclose(sum(weights),1.0, rel_tol=0, abs_tol=1e-7):
        raise ValueError(f'{name}: normalized weights must total 100% (got {sum(weights)*100:.4f}%)')
    return weights

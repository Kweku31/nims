#!/usr/bin/env python3
"""Local dashboard API and static server. No third-party Python dependencies."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import itertools
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse, parse_qs
from uuid import uuid4
from experiment_options import validate_options

ROOT = Path(__file__).resolve().parent
REPORTS = ('FINAL_REPORT.md', '01_integrated_evidence.csv', '02_decision_rankings.csv',
           '03_phase_overview.csv', '04_network_trials.csv', 'run_manifest.json')
FOLLOWUP_FILES = ('paired_baseline_topsis.csv','paired_baseline_trials.csv','paired_archives_trials.csv')
TABLES = {'evidence': REPORTS[1], 'rankings': REPORTS[2], 'overview': REPORTS[3], 'trials': REPORTS[4]}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def sha256_file(path):
    """Hash the whole input without loading clinical data into RAM."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def pipeline_code_fingerprints(pipeline):
    """Freeze exactly the code inputs used by the updated pipeline checkpoint."""
    pipeline = Path(pipeline).resolve()
    root = pipeline/'thesis_pipeline'
    sources = [*root.rglob('*.py'), pipeline/'run_thesis.py', pipeline/'receiver_reconstruct.py']
    absent = [str(p) for p in sources if not p.is_file()]
    if absent:
        raise ValueError('Missing pipeline code required for reproducible resume: '+', '.join(absent))
    hashes = {str(p.relative_to(pipeline)): sha256_file(p) for p in sorted(sources)}
    companion = pipeline.parent/'final_transfer_study'
    for name in ('study.py','baseline.py','copy_shell.py','new_experiment.py'):
        if (companion/name).is_file():
            hashes['../final_transfer_study/'+name]=sha256_file(companion/name)
    return hashes


def checkpoint_run_id(output):
    """Locate the SINGLE existing computational run, never choose a new run ID."""
    output = Path(output)
    status = load(output/'run_status.json')
    rid = status.get('run_id')
    if isinstance(rid, str) and re.fullmatch(r'[0-9a-f]{20}', rid):
        if (output/'runs'/rid/'checkpoint.json').is_file():
            return rid
    checkpoints = sorted((output/'runs').glob('*/checkpoint.json'))
    checkpoints = [p for p in checkpoints if re.fullmatch(r'[0-9a-f]{20}', p.parent.name)]
    if len(checkpoints) > 1:
        raise ValueError('Multiple checkpoint runs exist in this job; refusing an ambiguous resume')
    return checkpoints[0].parent.name if checkpoints else None


def missingness_label(value):
    """Accept fractions, percentages and strings without mislabeling the feature set."""
    token = str(value).strip()
    number = float(token[:-1] if token.endswith('%') else token)
    if not token.endswith('%') and 0 <= number <= 1:
        number *= 100
    return round(number)


def validate_topsis_weights(values):
    if values is None:
        return [1 / 7] * 7
    if not isinstance(values, list) or len(values) != 7:
        raise ValueError('TOPSIS requires seven weights')
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in values):
        raise ValueError('TOPSIS weights must be finite, nonnegative numbers')
    total = sum(values)
    if not (math.isclose(total, 1., rel_tol=0, abs_tol=1e-7) or
            math.isclose(total, 100., rel_tol=0, abs_tol=1e-5)):
        raise ValueError('TOPSIS weights must total 100% (or 1 as fractions)')
    return [x / total for x in values]


PHASES = [
    ('phase1', 'Data profiling', 'Understand shape, missingness and correlations.'),
    ('phase2', 'Transfer baseline', 'Compare lossless formats and delivery costs.'),
    ('phase3', 'Feature selection', 'Review missingness and preserve clinical predictors.'),
    ('phase4', 'PCA & autoencoder', 'Build reduced representations and portable payloads.'),
    ('phase5', 'Utility evaluation', 'Measure reconstruction, retention and neighborhood overlap.'),
    ('phase6', 'Verified delivery', 'Package, verify and benchmark each configuration.'),
]


def load(path, fallback=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if fallback is None else fallback


def worker_identity(pid):
    """Linux start ticks distinguish a saved worker from a reused process ID."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (OSError, IndexError):
        return None


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False))
    tmp.replace(path)


def read_table(path, limit=20000):
    if not path.is_file():
        return []
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        rows = []
        for i, row in enumerate(reader):
            if i >= limit:
                break
            clean = {}
            for key, value in row.items():
                if not key:
                    continue
                if value in ('', None, 'nan', 'NaN', 'inf', '-inf'):
                    clean[key] = None
                elif value in ('True', 'False'):
                    clean[key] = value == 'True'
                else:
                    try:
                        number = float(value)
                        clean[key] = number if math.isfinite(number) else None
                    except (ValueError, TypeError):
                        clean[key] = value
            rows.append(clean)
        return rows


def preview_csv(path, offset=0, limit=25):
    """Read only one page; preserve CSV text, including identifiers and empty cells."""
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != '.csv' or not path.is_file():
        raise ValueError('Choose an existing CSV file')
    if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 10000000 or not 1 <= limit <= 100:
        raise ValueError('Preview offset must be 0–10000000 and page size 1–100')
    try:
        with path.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.reader(stream, strict=True)
            columns = next(reader, [])
            if not columns or not any(c.strip() for c in columns):
                raise ValueError('CSV needs a nonempty header row')
            page = list(itertools.islice(reader, offset, offset+limit+1))
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('Use a valid UTF-8 CSV with a header row') from exc
    rows = page[:limit]
    return {'name': path.name, 'path': str(path), 'bytes': path.stat().st_size,
            'columns': columns[:200], 'column_count': len(columns), 'offset': offset,
            'limit': limit, 'has_more': len(page)>limit, 'rows': [[cell[:1000] for cell in row[:200]] for row in rows],
            'row_width_mismatch': any(len(row) != len(columns) for row in rows),
            'columns_truncated': len(columns)>200,
            'cells_truncated': any(len(cell)>1000 for row in rows for cell in row[:200])}


def phase_summary(checkpoint, complete=False):
    stages = checkpoint.get('stages', {})
    output = []
    for key, title, description in PHASES:
        members = {k: v for k, v in stages.items() if k == key or k.startswith(key+'_')}
        statuses = [v.get('status') for v in members.values()]
        state = ('failed' if 'failed' in statuses else 'running' if 'running' in statuses else
                 'complete' if statuses and all(s == 'complete' for s in statuses) else
                 'complete' if complete and not statuses else 'pending')
        output.append({'id': key, 'title': title, 'description': description, 'status': state,
                       'seconds': sum(float(v.get('seconds', 0)) for v in members.values()),
                       'completed': statuses.count('complete'), 'total': len(statuses),
                       'stages': [{'name': k, 'status': v.get('status'), 'seconds': v.get('seconds'),
                                   'error': v.get('error')} for k, v in members.items()]})
    return output


class Dashboard:
    def __init__(self, pipeline, results_roots, data_dir):
        self.pipeline = Path(pipeline).resolve()
        self.roots = [Path(p).resolve() for p in results_roots]
        self.data = Path(data_dir).resolve()
        self.jobs = self.data/'jobs'
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.processes = {}
        self.dataset_hashes = {}
        self.lock = threading.Lock()
        # An API restart must not mislabel a still-running pipeline as stopped.
        for record in self.jobs.glob('*/job.json'):
            self.refresh_job_status(record)

    def refresh_job_status(self, record):
        job = load(record)
        if job.get('status') == 'running':
            identity = job.get('worker_identity')
            if identity and worker_identity(job.get('worker_pid')) == identity:
                return job
            run_status = load(record.parent/'output/run_status.json')
            if run_status.get('status') == 'complete':
                job.update(status='complete', error=None)
            else:
                job.update(status='interrupted', error=run_status.get('error') or
                           'The previous worker exited; Resume will reuse verified checkpoints.')
            save(record, job)
        return job

    def catalog(self):
        found = {}
        for root in self.roots:
            for folder in [root/'results', *sorted((root/'results').glob('*'))]:
                if folder.name.startswith('.') or not (folder/'run_manifest.json').is_file():
                    continue
                key = hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:16]
                found[key] = folder
        return found

    def run_list(self):
        rows = []
        for key, folder in self.catalog().items():
            meta = load(folder/'run_manifest.json')
            rows.append({'id': key, 'name': Path(meta.get('input', 'Experiment')).name,
                         'created': datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat(),
                         'status': 'complete', 'snapshot': folder.name, 'run_id': meta.get('run_id'),
                         'mode': ', '.join(meta.get('network_modes', []))})
        for path in self.jobs.glob('*/job.json'):
            job = self.refresh_job_status(path)
            item = {k: job.get(k) for k in ('id', 'name', 'created', 'status', 'mode', 'error')}
            snapshots = sorted((path.parent/'output/results').glob('*/run_manifest.json'))
            item['snapshot'] = snapshots[-1].parent.name if snapshots else None
            rows.append(item)
        rows.sort(key=lambda r: r.get('created') or '', reverse=True)
        return rows

    def job_path(self, key):
        if not re.fullmatch(r'job-[a-f0-9]{12}', key):
            raise ValueError('Unknown experiment')
        path = self.jobs/key
        if not (path/'job.json').is_file():
            raise FileNotFoundError('Experiment not found')
        return path

    def locations(self, key):
        if key.startswith('job-'):
            path = self.job_path(key)
            status = load(path/'output/run_status.json')
            # Derive paths from our output tree; never serve a path supplied by a browser.
            output = path/'output'
            snapshots = sorted((output/'results').glob('*/run_manifest.json'))
            reports = snapshots[-1].parent if snapshots else None
            run_id = status.get('run_id') or checkpoint_run_id(output)
            checkpoint = output/'runs'/run_id/'checkpoint.json' if re.fullmatch(r'[a-f0-9]{20}', run_id or '') else None
            return reports, checkpoint, output/'pipeline.log', self.refresh_job_status(path/'job.json')
        reports = self.catalog().get(key)
        if reports is None:
            raise FileNotFoundError('Experiment not found')
        meta = load(reports/'run_manifest.json')
        output = reports.parent.parent if reports.parent.name == 'results' else reports.parent
        run_id = str(meta.get('run_id') or '')
        checkpoint = output/'runs'/run_id/'checkpoint.json' if re.fullmatch(r'[a-f0-9]{20}', run_id) else None
        # Shared historical logs mix invocations; show only matching run records.
        return reports, checkpoint, output/'pipeline.log', {'status': 'complete', 'run_id': run_id}

    def detail(self, key):
        if key == 'demo':
            return load(ROOT/'public/demo.json')
        reports, cp, log, job = self.locations(key)
        checkpoint = load(cp) if cp else {}
        meta = load(reports/'run_manifest.json') if reports else {}
        phase_list = phase_summary(checkpoint, job.get('status') == 'complete')
        for phase in phase_list:
            if phase['status'] == 'running' and job.get('status') in ('failed', 'cancelled', 'interrupted'):
                phase['status'] = job['status']
        # Historical studies can be attached to an immutable published snapshot.
        if reports and (reports/'transport_studies.json').is_file():
            extra=load(reports/'transport_studies.json')
            if extra.get('run_id')==meta.get('run_id') and extra.get('input_sha256')==meta.get('input_sha256'):
                meta={**meta,'transport_studies':extra['studies']}
        tables = {name: read_table(reports/file) if reports else [] for name, file in TABLES.items()}
        return {'id': key, 'demo': False, 'name': job.get('name') or Path(meta.get('input', 'Experiment')).name,
                'status': job.get('status'), 'error': job.get('error'), 'manifest': meta,
                'network': load(self.job_path(key)/'output/network_status.json') if key.startswith('job-') else {},
                'resume_count': job.get('resume_count', 0),
                'snapshot': reports.name if reports else None, 'phases': phase_list, **tables,
                'report': (reports/'FINAL_REPORT.md').read_text() if reports and (reports/'FINAL_REPORT.md').is_file() else '',
                'files': [p for p in (*REPORTS,*FOLLOWUP_FILES) if reports and (reports/p).is_file()],
                'table_limit': 20000,
                'configuration': meta.get('config') or checkpoint.get('config') or
                    (load(self.job_path(key)/'config.json') if key.startswith('job-') else {})}

    def dataset_preview(self, key, offset=0, limit=25):
        if key == 'demo':
            demo = load(ROOT/'public/demo-dataset.json')
            rows = demo.get('rows', [])
            return {**demo, 'rows': rows[offset:offset+limit], 'offset': offset, 'limit': limit,
                    'has_more': offset+limit < len(rows), 'demo': True}
        reports, cp, _, _ = self.locations(key)
        meta = load(reports/'run_manifest.json') if reports else {}
        checkpoint = load(cp) if cp else {}
        config = load(self.job_path(key)/'config.json') if key.startswith('job-') else checkpoint.get('config', {})
        path = meta.get('input') or config.get('dataset')
        if not path:
            raise ValueError('The source CSV path is not available for this experiment')
        if not Path(path).expanduser().is_file():
            raise ValueError(f'The source CSV is missing at its saved location: {path}. Restore that file to preview this experiment.')
        result = preview_csv(path, offset, limit)
        expected = meta.get('input_sha256') or checkpoint.get('input_sha256')
        if expected:
            source = Path(result['path'])
            stat = source.stat()
            cache_key = (str(source), stat.st_mtime_ns, stat.st_size)
            if cache_key not in self.dataset_hashes:
                with source.open('rb') as stream:
                    self.dataset_hashes = {cache_key: hashlib.file_digest(stream, 'sha256').hexdigest()}
            result['matches_run_input'] = self.dataset_hashes[cache_key] == expected
        return result

    def upload(self, stream, filename, length):
        if not 0 < length <= MAX_UPLOAD_BYTES:
            raise ValueError('Upload a CSV between 1 byte and 100 MB, or use a local path for larger files')
        filename = Path(filename.replace('\\', '/')).name
        if not filename.lower().endswith('.csv'):
            raise ValueError('Only CSV files can be uploaded')
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', filename)[:150]
        if not name.lower().endswith('.csv'):
            name = name[:146]+'.csv'
        folder = self.data/'uploads'/uuid4().hex
        folder.mkdir(parents=True)
        target = folder/name
        try:
            with target.open('xb') as output:
                target.chmod(0o600)
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024*1024, remaining))
                    if not chunk:
                        raise ValueError('Upload ended before the file was complete')
                    output.write(chunk); remaining -= len(chunk)
            return preview_csv(target)
        except Exception:
            target.unlink(missing_ok=True); folder.rmdir()
            raise

    def phase_details(self, key, phase):
        if phase not in {p[0] for p in PHASES}:
            raise ValueError('Unknown phase')
        if key == 'demo':
            return load(ROOT/'public/demo-phases.json').get(phase, {'groups': [], 'note': 'No detailed demo artifact available.'})
        reports, cp, _, _ = self.locations(key)
        meta = load(reports/'run_manifest.json') if reports else {}
        checkpoint = load(cp) if cp else {}
        stages = checkpoint.get('stages', {})
        groups = []
        def phase_root(name):
            value = meta.get('phase_directories', {}).get(name) or stages.get(name, {}).get('result', {}).get('run')
            return Path(value) if value else None
        def add(name, title, root, filename, description=''):
            if root is None:
                return
            path = root/filename
            available = path.is_file()
            rows = read_table(path, limit=1001) if available else []
            columns = list(rows[0]) if rows else []
            if available and not columns:
                with path.open(newline='', encoding='utf-8-sig') as stream:
                    columns = next(csv.reader(stream), [])
            groups.append({'id': name, 'title': title, 'description': description,
                           'source': filename, 'available': available, 'columns': columns,
                           'rows': rows[:1000], 'truncated': len(rows)>1000})
        root = phase_root(phase)
        if phase == 'phase1':
            add('summary', 'Dataset summary', root, 'dataset_summary.csv')
            add('redundant', 'Flagged correlation pairs', root, 'redundant_pairs.csv',
                'Potential redundancy at the recorded Pearson threshold. These are pairs, not a list of removed columns. Phase 1 does not remove features.')
            add('columns', 'Column profiles and missingness', root, 'column_profile.csv')
            add('duplicates', 'Exact duplicate column groups', root, 'duplicate_columns.csv')
            add('numeric', 'Numeric variables and excluded identifiers', root, 'numeric_variable_profile.csv')
        elif phase == 'phase2':
            if reports and (reports/'paired_baseline_trials.csv').is_file():
                add('paired','Four-block baseline trials',reports,'paired_baseline_trials.csv')
                add('paired-topsis','Four-block TOPSIS by transport',reports,'paired_baseline_topsis.csv')
            else:
                add('paired','Four-block baseline trials',phase_root('phase2_paired'),'trials.csv')
            add('transports', 'Verified transport trials', root, 'transport_comparison.csv')
            add('baseline', 'Format benchmarks', root, 'transfer_benchmark.csv')
            add('trials', 'Individual transfer trials', root, 'transfer_trials.csv')
            add('topsis', 'Phase 2 TOPSIS', phase_root('phase2_topsis'), 'topsis_ranking.csv')
        elif phase == 'phase3':
            add('summary', 'Feature-set comparison', root, 'threshold_comparison.csv')
            add('availability', 'Feature availability', root, 'feature_availability_full.csv')
            if root and root.is_dir():
                for variant in sorted(p for p in root.iterdir() if p.is_dir()):
                    add('selection-'+variant.name, variant.name+' · column decisions', variant,
                        'feature_selection_report.csv', 'Lists retained and removed columns with the recorded reason and clinical safeguards.')
        elif phase == 'phase4':
            runs = meta.get('phase4_runs') or {k.removeprefix('phase4_'):v['result']['run'] for k,v in stages.items()
                                              if k.startswith('phase4_') and v.get('result', {}).get('run')}
            for name, path in runs.items():
                for suffix, title, filename in [('comparison','Model comparison','phase4_comparison.csv'),
                     ('lossless','Lossless baselines','phase4_lossless_baselines.csv'),
                     ('features','Per-feature reconstruction','phase4_per_feature_reconstruction.csv'),
                     ('training','Autoencoder training curve','phase4_autoencoder_loss_curve.csv')]:
                    add(name+'-'+suffix, name+' · '+title, Path(path), filename)
        elif phase == 'phase5':
            for name,title,filename in [('summary','Utility summary','phase5_utility_summary.csv'),
                ('features','Per-feature utility','phase5_per_feature_utility.csv'),
                ('retention','Feature retention','phase5_feature_retention.csv'),
                ('neighbors','Nearest-neighbor overlap','phase5_nearest_neighbor_overlap.csv')]:
                add(name,title,root,filename)
        elif phase == 'phase6':
            if reports and (reports/'paired_archives_trials.csv').is_file():
                add('paired','Paired archive transfers and controlled interruptions',reports,'paired_archives_trials.csv')
            else:
                add('paired','Paired archive transfers and controlled interruptions',phase_root('phase6_paired'),'trials.csv')
            add('evidence','Package integrity and delivery evidence',reports,'01_integrated_evidence.csv')
            add('trials','Individual network trials',reports,'04_network_trials.csv')
            if not reports:
                for name, stage in stages.items():
                    result = stage.get('result', {})
                    if name.startswith('phase6_') and result.get('trials_file'):
                        file = Path(result['trials_file'])
                        add(name, name+' · trials', file.parent, file.name)
        return {'phase': phase, 'groups': groups, 'note': 'Details come from the saved phase artifacts. Missing files are reported explicitly.'}

    def logs(self, key):
        if key == 'demo':
            return {'text': 'Synthetic demonstration · no active process.\nAll six phases completed and 18 packages verified locally.\nNetwork transfer was simulated. No SSH connection was made.', 'truncated': False}
        _, _, path, job = self.locations(key)
        if not path.is_file() and key.startswith('job-'):
            path = self.job_path(key)/'launcher.log'
        if not path.is_file():
            return {'text': 'Waiting for pipeline output…', 'truncated': False}
        with path.open('rb') as stream:
            size = path.stat().st_size
            stream.seek(max(0, size-100000))
            text = stream.read().decode('utf-8', errors='replace')
        if not key.startswith('job-') and job.get('run_id'):
            text = '\n'.join(line for line in text.splitlines() if f"run={job['run_id']}" in line)
        return {'text': text, 'truncated': size > 100000}

    def settings(self):
        datasets = sorted({str(p.resolve()) for base in (self.pipeline, self.pipeline.parent)
                           for p in base.glob('*.csv') if p.is_file()})
        datasets += sorted(str(p) for p in (self.data/'uploads').glob('*/*.csv'))
        dependencies = ['numpy', 'pandas', 'scipy', 'sklearn', 'pyarrow', 'zstandard']
        missing = [name for name in dependencies if importlib.util.find_spec(name) is None]
        return {'datasets': datasets, 'pipeline': str(self.pipeline), 'python': sys.executable,
                'missing_dependencies': missing, 'results_roots': [str(p) for p in self.roots],
                'api_version': 4, 'patient_coverage_choices': [0.75, 0.80, 0.90],
                'topsis_weight_controls': True, 'experiment_options_controls': True, 'transport_controls': True,
                'ae_acceleration_controls': True, 'remote_reconstruction_controls': True,
                'checkpoint_resume_controls': True}

    def has_active_worker(self):
        if any(p.poll() is None for p in self.processes.values()):
            return True
        for record in self.jobs.glob('*/job.json'):
            job = load(record)
            identity = job.get('worker_identity')
            if identity and worker_identity(job.get('worker_pid')) == identity:
                return True
        return False

    def launch(self, body):
        if not isinstance(body, dict):
            raise ValueError('Expected experiment settings')
        dataset = Path(str(body.get('dataset', ''))).expanduser().resolve()
        if not dataset.is_file() or dataset.suffix.lower() != '.csv':
            raise ValueError('Choose an existing CSV file on this computer')
        mode = body.get('transfer_mode', 'simulated')
        if mode not in ('simulated', 'ssh'):
            raise ValueError('Choose simulated or strict SSH transfer')
        remote = body.get('remote', '')
        if mode == 'ssh' and not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+', remote):
            raise ValueError('SSH requires a user@host destination')
        ssh_options = {}
        for key, default, maximum in (('ssh_port', 22, 65535), ('ssh_max_attempts', 3, 10),
                                      ('ssh_transfer_timeout', 300, 86400)):
            value = body.get(key, default)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{key} must be an integer from 1 to {maximum}')
            ssh_options[key] = value
        remote_dir = body.get('remote_dir', '/tmp/thesis_transfer/phase6')
        if not isinstance(remote_dir, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', remote_dir) or '..' in Path(remote_dir).parts:
            raise ValueError('Remote directory must be an absolute POSIX path without spaces or shell characters')
        ssh_options['remote_dir'] = remote_dir
        receiver_execution = body.get('receiver_execution', 'local')
        if receiver_execution not in ('local', 'remote'):
            raise ValueError('Receiver execution must be local or remote')
        if receiver_execution == 'remote' and mode != 'ssh':
            raise ValueError('University-server reconstruction requires strict SSH transfer')
        remote_receiver_script = body.get('remote_receiver_script')
        remote_python = body.get('remote_python', 'python3')
        remote_reconstruction_timeout = body.get('remote_reconstruction_timeout', 900)
        if type(remote_reconstruction_timeout) is not int or not 1 <= remote_reconstruction_timeout <= 86400:
            raise ValueError('Remote reconstruction timeout must be 1–86400 seconds')
        if receiver_execution == 'remote':
            if (not isinstance(remote_receiver_script, str) or
                    not re.fullmatch(r'/[A-Za-z0-9_./-]+', remote_receiver_script) or
                    '..' in Path(remote_receiver_script).parts):
                raise ValueError('Server receiver script must have a safe absolute path')
            if (not isinstance(remote_python, str) or
                    not re.fullmatch(r'[A-Za-z0-9_./-]+', remote_python)):
                raise ValueError('Server Python must be a safe executable name or absolute path')
        else:
            remote_receiver_script = None
            remote_python = 'python3'
        k = body.get('k', [2, 4, 8])
        if not isinstance(k, list) or not 1 <= len(k) <= 12 or any(type(v) is not int or not 1 <= v <= 256 for v in k):
            raise ValueError('Components must be 1–12 integer values between 1 and 256')
        iterations = body.get('ae_max_iter', 500)
        topsis_weights = validate_topsis_weights(body.get('topsis_weights'))
        optional = validate_options(body)
        transport = body.get('ssh_transport', 'scp')
        if transport not in ('scp', 'rsync', 'both') or (mode != 'ssh' and transport != 'scp'):
            raise ValueError('Choose scp, rsync or both for strict SSH')
        paired=body.get('paired_transport_studies',False)
        if type(paired) is not bool or (paired and (transport!='both' or mode!='ssh' or 16 not in k or ssh_options['ssh_max_attempts']<2)):
            raise ValueError('Full paired studies require strict SSH, both transports, k=16 and at least two attempts')
        if type(iterations) is not int or not 1 <= iterations <= 10000:
            raise ValueError('AE iteration limit must be an integer from 1 to 10000')
        features = body.get('feature_sets', 'clinical')
        if features == 'clinical':
            highest = max(missingness_label(x) for x in optional['missingness_thresholds'])
            features = [f'FS_{highest:02d}_clinical_review']
        else:
            highest = 95
        if features not in ('all', [f'FS_{highest:02d}_clinical_review']):
            raise ValueError('Choose the clinical-review feature set or all feature sets')
        if features != 'all' and highest not in [missingness_label(x) for x in optional['missingness_thresholds']]:
            raise ValueError('The selected clinical feature set must be included in the missingness cutoffs')
        coverage = body.get('patient_coverage_min', 0.75)
        if isinstance(coverage, bool):
            raise ValueError('Patient coverage must be 75%, 80% or 90%')
        try:
            token = str(coverage).strip()
            coverage = float(token.rstrip('%'))
            if token.endswith('%') or coverage > 1:
                coverage /= 100
        except (TypeError, ValueError) as exc:
            raise ValueError('Patient coverage must be 75%, 80% or 90%') from exc
        if coverage not in (0.75, 0.80, 0.90):
            raise ValueError('Patient coverage must be 75%, 80% or 90%')
        if self.settings()['missing_dependencies']:
            raise ValueError('Pipeline dependencies are missing from the server Python environment. See Settings.')
        if not (self.pipeline/'run_thesis.py').is_file():
            raise ValueError('Pipeline runner was not found')
        with self.lock:
            if self.has_active_worker():
                raise ValueError('An experiment is already running. Wait or stop it first; a worker can survive a dashboard restart.')
            key = 'job-'+uuid4().hex[:12]
            path = self.jobs/key; path.mkdir()
            config = {'dataset': str(dataset), 'output_dir': str(path/'output'), 'transfer_mode': mode,
                      'fallback_simulated': False, 'remote': remote if mode == 'ssh' else None,
                      'k': list(dict.fromkeys(k)), 'ae_max_iter': iterations, 'feature_sets': features,
                      'compare_npz_codecs': body.get('compare_npz_codecs') is True,
                      'patient_coverage_min': coverage, **ssh_options,
                      'topsis_weights': topsis_weights, **optional,
                      'ssh_transport':transport, 'paired_transport_studies':paired, 'receiver_execution': receiver_execution,
                      'remote_receiver_script': remote_receiver_script,
                      'remote_python': remote_python,
                      'remote_reconstruction_timeout': remote_reconstruction_timeout}
            fingerprints = pipeline_code_fingerprints(self.pipeline)
            dataset_sha = sha256_file(dataset)
            save(path/'config.json', config)
            job = {'id': key, 'name': dataset.name, 'created': datetime.now(timezone.utc).isoformat(),
                   'status': 'running', 'mode': mode,
                   'input_sha256': dataset_sha, 'code_sha256': fingerprints}
            save(path/'job.json', job)
            try:
                with (path/'launcher.log').open('w') as stream:
                    process = subprocess.Popen([sys.executable, str(self.pipeline/'run_thesis.py'),
                                                '--config', str(path/'config.json')], cwd=self.pipeline,
                                               stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                job.update(status='failed', error=str(exc)); save(path/'job.json', job)
                raise
            self.processes[key] = process
            job.update(worker_pid=process.pid, worker_identity=worker_identity(process.pid))
            save(path/'job.json', job)
            threading.Thread(target=self.watch, args=(key, process), daemon=True).start()
            return job

    def watch(self, key, process):
        code = process.wait()
        with self.lock:
            if self.processes.get(key) is not process:
                return
            path = self.jobs/key
            job = load(path/'job.json')
            if job.get('status') != 'cancelled':
                state = load(path/'output/run_status.json')
                completed = code == 0 and state.get('status') == 'complete'
                job.update(status='complete' if completed else 'failed', exit_code=code,
                           run_id=state.get('run_id') or job.get('run_id'),
                           error=None if completed else (state.get('error') or f'Pipeline exit code {code}'))
                save(path/'job.json', job)
            self.processes.pop(key, None)

    def resume(self, key):
        """Resume THIS job's verified stages, never initialize a different run."""
        with self.lock:
            path = self.job_path(key)
            job = self.refresh_job_status(path/'job.json')
            if job.get('status') == 'running':
                raise ValueError('This experiment is already running')
            if job.get('status') not in ('failed', 'interrupted', 'cancelled'):
                raise ValueError('Only a failed, interrupted or stopped experiment can be resumed')
            if self.has_active_worker():
                raise ValueError('A pipeline worker is still active. It must finish or stop before retrying.')
            config_path = path/'config.json'
            config = load(config_path)
            dataset = Path(str(config.get('dataset', '')))
            if not dataset.is_file():
                raise ValueError('Restore the saved source CSV before resuming this experiment')
            if not (self.pipeline/'run_thesis.py').is_file() or self.settings()['missing_dependencies']:
                raise ValueError('The pipeline runner and its dependencies must be available')
            output = path/'output'
            if Path(config.get('output_dir', '')).resolve() != output.resolve():
                raise ValueError('Saved output directory does not match this experiment')
            # This is deliberately read BEFORE restarting the runner, which writes
            # an initializing run_status.json. Keep the computational run ID fixed.
            original_run_id = checkpoint_run_id(output)
            if job.get('run_id') and original_run_id and job['run_id'] != original_run_id:
                raise ValueError('The recorded run ID differs from this experiment checkpoint')
            if job.get('input_sha256') and sha256_file(dataset) != job['input_sha256']:
                raise ValueError('The source CSV changed; restore original bytes before resuming')
            if job.get('code_sha256') and pipeline_code_fingerprints(self.pipeline) != job['code_sha256']:
                raise ValueError('Pipeline code changed; restore original code before resuming this experiment')
            # Existing checkpoints also embed the normalized config and source/code
            # hashes; --resume-run-id rechecks them in the runner itself.
            output.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc).isoformat()
            command = [sys.executable, '-u', str(self.pipeline/'run_thesis.py'), '--config', str(config_path)]
            if original_run_id:
                command += ['--resume-run-id', original_run_id]
            try:
                with (path/'launcher.log').open('a') as stream:
                    stream.write(f'\nRESUME {now}; checkpoint={original_run_id or "none (before first checkpoint)"}\n')
                    stream.flush()
                    process = subprocess.Popen(command, cwd=self.pipeline,
                                               stdout=stream, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                # Leave the job as failed/interrupted if a new worker cannot start.
                raise ValueError(f'Could not resume the existing experiment: {exc}') from exc
            job.setdefault('previous_invocations', []).append({k: job.get(k) for k in ('status', 'error', 'exit_code')})
            job.update(status='running', error=None, exit_code=None, resumed_utc=now,
                       resume_count=job.get('resume_count', 0)+1,
                       resume_checkpoint_id=original_run_id,
                       worker_pid=process.pid, worker_identity=worker_identity(process.pid))
            save(path/'job.json', job)
            save(path/'output/network_status.json',
                 {'status': 'idle', 'operation': 'Resuming verified checkpoints', 'updated_utc': now})
            self.processes[key] = process
            threading.Thread(target=self.watch, args=(key, process), daemon=True).start()
            return {**job, 'checkpoint_run_id': original_run_id,
                    'resume_note': 'Verified completed stages are reused; failed stages execute again'}

    def rerun_phase6(self, key, body):
        """Re-evaluate only Phase 6 under real SSH; keep the same dashboard job."""
        if not isinstance(body, dict):
            raise ValueError('Expected Phase 6 receiver settings')
        with self.lock:
            path = self.job_path(key)
            job = self.refresh_job_status(path/'job.json')
            if self.has_active_worker() or job.get('status') == 'running':
                raise ValueError('Stop or finish the current pipeline worker before replaying Phase 6')
            config_path = path/'config.json'
            original = load(config_path)
            source = Path(str(original.get('dataset', '')))
            output = path/'output'
            if not source.is_file() or not (self.pipeline/'run_thesis.py').is_file():
                raise ValueError('Original dataset and run_thesis.py must still exist')
            if Path(original.get('output_dir', '')).resolve() != output.resolve():
                raise ValueError('Saved output location does not match this experiment')
            run_id = checkpoint_run_id(output)
            if not run_id:
                raise ValueError('No existing Phase 1–5 checkpoint for this experiment')
            prior = load(output/'runs'/run_id/'checkpoint.json')
            if not all(prior.get('stages', {}).get(name, {}).get('status') == 'complete'
                       for name in ('phase1','phase2','phase3','phase5')):
                raise ValueError('Phases 1–5 must finish successfully before Phase 6 replay')
            if not all(stage.get('status') == 'complete' for name, stage in prior.get('stages', {}).items()
                       if name.startswith('phase4_')):
                raise ValueError('Phase 4 has incomplete configurations')
            if not any(k.startswith('phase4_') for k in prior.get('stages', {})):
                raise ValueError('No completed Phase 4 outputs to deliver')
            if sha256_file(source) != prior.get('input_sha256'):
                raise ValueError('The original dataset bytes changed; cannot reuse research measurements')
            # Only the runner/checkpoint-orchestration files may differ from the
            # original run. PCA, AE, Phase 5 and receiver decoder must be identical.
            old_hashes = prior.get('code_sha256', {})
            new_hashes = pipeline_code_fingerprints(self.pipeline)
            permitted = {'run_thesis.py','thesis_pipeline/core.py'}
            migration = load(self.pipeline/'rsync_replay_hashes.json')
            if set(old_hashes) != set(new_hashes) or any(
                    old_hashes[name] != digest and migration.get(name) != [old_hashes[name],digest]
                    for name,digest in new_hashes.items() if name not in permitted):
                raise ValueError('Research pipeline/decoder code changed; cannot safely replay Phase 6 on this checkpoint')
            if self.settings()['missing_dependencies']:
                raise ValueError('Required Python dependencies are missing')
            transport = body.get('ssh_transport', original.get('ssh_transport', 'scp'))
            if transport not in ('scp', 'rsync', 'both'):
                raise ValueError('Choose scp, rsync or both')
            remote = body.get('remote') or original.get('remote')
            if not isinstance(remote, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+', remote):
                raise ValueError('Enter a valid SSH user@host')
            script = body.get('remote_receiver_script') or original.get('remote_receiver_script')
            if not isinstance(script, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', script) or '..' in Path(script).parts:
                raise ValueError('Enter the absolute receiver_reconstruct.py path on the university server')
            remote_python = body.get('remote_python') or original.get('remote_python') or 'python3'
            if not isinstance(remote_python, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', remote_python):
                raise ValueError('Invalid server Python executable')
            remote_dir = body.get('remote_dir') or original.get('remote_dir') or '/tmp/thesis_transfer/phase6'
            if not isinstance(remote_dir, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', remote_dir) or '..' in Path(remote_dir).parts:
                raise ValueError('Invalid server destination directory')
            port = body.get('ssh_port', original.get('ssh_port', 22))
            timeout = body.get('remote_reconstruction_timeout', original.get('remote_reconstruction_timeout', 900))
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('SSH port must be 1–65535')
            if type(timeout) is not int or not 1 <= timeout <= 86400:
                raise ValueError('Server reconstruction timeout must be 1–86400 seconds')
            command = [sys.executable, '-u', str(self.pipeline/'run_thesis.py'),
                       '--config', str(config_path), '--resume-run-id', run_id,
                       '--replay-phase6', '--ssh-transport',transport, '--transfer-mode', 'ssh',
                       '--receiver-execution', 'remote', '--remote', remote,
                       '--remote-dir', remote_dir, '--ssh-port', str(port),
                       '--remote-receiver-script', script,
                       '--remote-python', remote_python,
                       '--remote-reconstruction-timeout', str(timeout)]
            now = datetime.now(timezone.utc).isoformat()
            try:
                with (path/'launcher.log').open('a') as stream:
                    stream.write(f'\nPHASE6 REMOTE REPLAY {now}; original checkpoint={run_id}\n')
                    stream.flush()
                    process = subprocess.Popen(command, cwd=self.pipeline,
                                               stdout=stream, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                raise ValueError(f'Could not start Phase 6 replay: {exc}') from exc
            job.setdefault('previous_invocations', []).append({k:job.get(k) for k in ('status','error','exit_code')})
            job.update(status='running', error=None, exit_code=None,
                       run_id=run_id, worker_pid=process.pid,
                       worker_identity=worker_identity(process.pid),
                       phase6_replay={'started_utc':now,'receiver_execution':'remote',
                                      'remote':remote,'remote_receiver_script':script,
                                      'checkpoint_run_id':run_id})
            save(path/'job.json', job)
            self.processes[key] = process
            threading.Thread(target=self.watch, args=(key,process), daemon=True).start()
            return {**job,'message':'Replaying Phase 6 on server, then re-running TOPSIS in this experiment'}

    def cancel(self, key):
        with self.lock:
            path = self.job_path(key)
            process = self.processes.get(key)
            if not process or process.poll() is not None:
                raise ValueError('This experiment is not running in this dashboard')
            job = load(path/'job.json'); job['status'] = 'cancelled'; save(path/'job.json', job)
            os.killpg(process.pid, signal.SIGTERM)
            def finish():
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            threading.Thread(target=finish, daemon=True).start()
            return job


class Handler(BaseHTTPRequestHandler):
    def local_host(self):
        try:
            return urlparse('http://'+self.headers.get('Host', '')).hostname in ('127.0.0.1', 'localhost', '::1')
        except ValueError:
            return False

    def log_message(self, fmt, *args):
        if not args or '200' not in str(args):
            super().log_message(fmt, *args)

    def send(self, status, body, content_type='application/json', download=None):
        data = json.dumps(body, allow_nan=False).encode() if content_type == 'application/json' and not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{download}"')
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if not self.local_host():
            return self.send(403, {'error': 'Use a localhost address'})
        app = self.server.app
        parts = unquote(urlparse(self.path).path).strip('/').split('/')
        try:
            if parts == ['api', 'settings']:
                return self.send(200, app.settings())
            if parts == ['api', 'runs']:
                return self.send(200, app.run_list())
            if len(parts) >= 3 and parts[:2] == ['api', 'runs']:
                key = parts[2]
                if len(parts) == 3:
                    return self.send(200, app.detail(key))
                if parts[3:] == ['logs']:
                    return self.send(200, app.logs(key))
                if parts[3:] == ['dataset']:
                    query = parse_qs(urlparse(self.path).query)
                    offset = int(query.get('offset', ['0'])[0])
                    limit = int(query.get('limit', ['25'])[0])
                    if not 0 <= offset <= 10000000 or not 1 <= limit <= 100:
                        raise ValueError('Invalid preview page')
                    return self.send(200, app.dataset_preview(key, offset, limit))
                if len(parts) == 5 and parts[3] == 'phases':
                    return self.send(200, app.phase_details(key, parts[4]))
                if len(parts) == 5 and parts[3] == 'files' and parts[4] in (*REPORTS,*FOLLOWUP_FILES) and key != 'demo':
                    folder, _, _, _ = app.locations(key)
                    if folder and (folder/parts[4]).is_file():
                        return self.send(200, (folder/parts[4]).read_bytes(), 'application/octet-stream', parts[4])
                raise FileNotFoundError('Report not found')
            if parts[0] == 'api':
                raise FileNotFoundError('Endpoint not found')
            dist = ROOT/'dist'
            path = (dist/'/'.join(parts)).resolve()
            if not path.is_relative_to(dist.resolve()):
                raise FileNotFoundError('File not found')
            if not path.is_file():
                path = dist/'index.html'
            if not path.is_file():
                return self.send(503, {'error': 'Build the React app with npm run build, or run npm run dev.'})
            return self.send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        except (ValueError, FileNotFoundError) as exc:
            self.send(404, {'error': str(exc)})
        except OSError as exc:
            self.send(500, {'error': str(exc)})

    def do_POST(self):
        if not self.local_host():
            return self.send(403, {'error': 'Use a localhost address'})
        # Requests require an explicit content type and a browser-local origin.
        origin = self.headers.get('Origin')
        allowed = {f'http://{self.headers.get("Host")}', 'http://127.0.0.1:5173', 'http://localhost:5173'}
        if origin and origin not in allowed:
            return self.send(403, {'error': 'Cross-origin requests are not allowed'})
        parts = urlparse(self.path).path.strip('/').split('/')
        if parts == ['api', 'datasets', 'upload']:
            if self.headers.get('Content-Type', '').split(';')[0] != 'text/csv':
                return self.send(415, {'error': 'Use text/csv for dataset uploads'})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if length > MAX_UPLOAD_BYTES:
                    return self.send(413, {'error': 'Upload limit is 100 MB; use a local CSV path for larger files'})
                return self.send(201, self.server.app.upload(self.rfile, unquote(self.headers.get('X-Filename', 'dataset.csv')), length))
            except (ValueError, OSError) as exc:
                return self.send(400, {'error': str(exc)})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send(415, {'error': 'Use application/json'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 16000:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            parts = urlparse(self.path).path.strip('/').split('/')
            if parts == ['api', 'datasets', 'preview']:
                return self.send(200, preview_csv(body.get('path', ''), body.get('offset', 0), body.get('limit', 25)))
            if parts == ['api', 'runs']:
                return self.send(201, self.server.app.launch(body))
            if len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'cancel':
                return self.send(200, self.server.app.cancel(parts[2]))
            if len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'resume':
                return self.send(200, self.server.app.resume(parts[2]))
            if len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'rerun-phase6':
                return self.send(200, self.server.app.rerun_phase6(parts[2], body))
            return self.send(404, {'error': 'Endpoint not found'})
        except (ValueError, OSError) as exc:
            self.send(400, {'error': str(exc)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--pipeline-dir', type=Path, default=ROOT.parent/'thesis_unified')
    parser.add_argument('--results-root', type=Path, action='append', help='Pipeline output root; repeat to import multiple histories')
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    args = parser.parse_args()
    app = Dashboard(args.pipeline_dir, args.results_root or [args.pipeline_dir/'thesis_runs'], args.data_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.app = app
    print(f'Observatory: http://127.0.0.1:{args.port} · Python: {sys.executable}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for key, process in app.processes.items():
            if process.poll() is None:
                app.cancel(key)
        server.server_close()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Build source-only v7 pipeline, dashboard, and combined update ZIPs.

Runtime datasets, experiment outputs and installed environments are excluded.
The combined archive overlays the updated files in an existing thesis_code tree.
"""
from pathlib import Path
import hashlib
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def archive(destination, contents):
    contents = dict(contents)
    contents['SHA256SUMS'] = ''.join(
        f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(contents.items())
    ).encode()
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            out.writestr(info, data)
    with zipfile.ZipFile(destination) as out:
        assert out.testzip() is None
        for name, data in contents.items():
            assert out.read(name) == data
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{digest}  {destination.name}\n')
    print(f'{destination.name}: {len(contents)} files; {destination.stat().st_size:,} bytes; SHA-256 {digest}')


def read_regular(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Unexpected release source: {path}')
    return path.read_bytes()


def main():
    subprocess.run([sys.executable, str(ROOT/'thesis_unified/build_v7_release.py')], check=True)
    dashboard = ROOT/'thesis_dashboard'
    fixed = ['README.md', 'README_AE_ACCELERATION.md', 'acceleration_api_tests.log', 'acceleration_ui_tests.log', 'README_SSH_RECOVERY.md', 'README_EXPERIMENT_OPTIONS.md', 'VALIDATION.md', 'server.py', 'build_thesis_reference.py', 'experiment_options.py', 'index.html',
             'package.json', 'package-lock.json', 'vite.config.js', 'playwright.config.js', '.gitignore',
             'ssh_api_validation.log', 'ssh_ui_validation.log',
             'phase2_repetition_api_tests.log', 'phase2_repetition_ui_tests.log',
             'aligned_repetition_api_tests.log', 'aligned_repetition_ui_tests.log',
             'experiment_options_api_tests.log', 'experiment_options_ui_tests.log']
    files = [dashboard/name for name in fixed]
    files += [p for folder in ('src', 'public', 'dist', 'tests') for p in (dashboard/folder).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    data = {'thesis_dashboard/'+p.relative_to(dashboard).as_posix(): read_regular(p, dashboard) for p in files}
    archive(ROOT/'thesis_dashboard_rsync.zip', data)
    updated = ['examples/rsync_trial_demo.sh', 'README_AE_ACCELERATION.md', '04_dimensionality_reduction_updated.py', 'ae_runtime.py', '02_transfer_benchmark.py', '06_transfer_package.py', '06_run_phase6_ssh_benchmarks.sh',
               '06_phase6_ssh_summary.py', 'README_SSH_RECOVERY.md', 'README_thesis_code.md',
               'PHASE6_SSH_BENCHMARK_README.md', 'PHASE6_TRANSFER_PACKAGE_GUIDE.md', 'build_v7_ssh_update.py',
               'README_EXPERIMENT_OPTIONS.md', 'thesis_slides/flowchart.tex',
               'thesis_slides/flowchart.pdf', 'thesis_slides/README.md']
    updated += ['thesis_slides/defence/'+name for name in
                ('defence.tex', 'defence.pdf', 'results.tex', 'speaker_notes.tex', 'speaker_notes.pdf', 'README.md')]
    combined = {'thesis_code/'+name: read_regular(ROOT/name, ROOT) for name in updated}
    for zipname in ('thesis_unified_v7_rsync.zip', 'thesis_dashboard_rsync.zip'):
        with zipfile.ZipFile(ROOT/zipname) as source:
            for name in source.namelist():
                if name == 'SHA256SUMS':
                    continue
                combined['thesis_code/'+name] = source.read(name)
    archive(ROOT/'thesis_v7_rsync_update.zip', combined)


if __name__ == '__main__':
    main()

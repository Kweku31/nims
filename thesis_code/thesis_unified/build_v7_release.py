#!/usr/bin/env python3
"""Build a source-only v7 ZIP, with internal and external SHA-256 manifests."""
import hashlib
from pathlib import Path
import zipfile


def build_release():
    root = Path(__file__).resolve().parent
    names = ['README.md', 'CHANGELOG_V7.md', 'STANDARDS_AND_VALIDATION.md',
             'VALIDATION_V7.md', 'README_SSH_RECOVERY.md', 'README_EXPERIMENT_OPTIONS.md', 'requirements.txt', 'requirements-gpu-cuda11.txt', 'README_AE_ACCELERATION.md', 'example_config.json',
             'run_thesis.py', 'receiver_reconstruct.py', 'rsync_replay_hashes.json', 'README_RSYNC.md', 'README_SERVER_RECONSTRUCTION.md', 'build_v7_release.py']
    files = [root/name for name in names]
    files += [p for folder in ('thesis_pipeline', 'tests') for p in (root/folder).rglob('*.py')]
    files += [root/'validation_v7'/name for name in (
        'unit_tests.log', 'synthetic_pipeline.log', 'synthetic_summary.json',
        'dependency_versions.txt', 'algorithm_preservation.sha256',
        'ssh_all_tests.log', 'ssh_synthetic_pipeline.log', 'ssh_synthetic_summary.json',
        'offline_ssh_pipeline.log', 'offline_ssh_summary.json', 'ssh_dependency_versions.txt',
        'ssh_algorithm_preservation.sha256', 'remote_naming_tests.log',
        'remote_naming_pipeline.log', 'remote_naming_summary.json',
        'phase2_repetition_tests.log', 'phase2_repetition_pipeline.log',
        'phase2_repetition_summary.json', 'aligned_repetition_tests.log',
        'aligned_repetition_pipeline.log', 'aligned_repetition_summary.json',
        'aligned_repetition_simulation.log', 'aligned_repetition_simulation_summary.json',
        'aligned_repetition_standalone.log', 'experiment_options_tests.log',
        'experiment_options_synthetic.log', 'experiment_options_synthetic_summary.json',
        'acceleration_all_tests.log', 'gpu_tests.log', 'gpu_benchmark.json', 'gpu_benchmark.log',
        'rsync_validation.json', 'gpu_synthetic.log', 'gpu_synthetic_summary.json', 'gpu_standalone.log', 'acceleration_preservation.json')]
    contents = {}
    for path in sorted(files):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Release inputs must be regular project files: {path}')
        contents[path.relative_to(root).as_posix()] = path.read_bytes()
    study_files = {name:(root.parent/'final_transfer_study'/name).read_bytes() for name in
                   ('study.py','baseline.py','copy_shell.py','new_experiment.py','attach_results.py')}
    manifest = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n'
                       for name, data in sorted(contents.items()))
    contents['SHA256SUMS'] = manifest.encode()
    contents['SHA256SUMS'] += ''.join(f'{hashlib.sha256(data).hexdigest()}  ../final_transfer_study/{name}\n' for name,data in sorted(study_files.items())).encode()
    destination = root.parent/'thesis_unified_v7_rsync.zip'
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name,data in sorted(study_files.items()):
            info=zipfile.ZipInfo('final_transfer_study/'+name,date_time=(2026,11,15,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo('thesis_unified/'+name, date_time=(2026, 11, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name, data in contents.items():
            assert archive.read('thesis_unified/'+name) == data
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{digest}  {destination.name}\n')
    print(f'{destination}\n{len(contents)} files; {destination.stat().st_size:,} bytes\nSHA-256: {digest}')


if __name__ == '__main__':
    build_release()

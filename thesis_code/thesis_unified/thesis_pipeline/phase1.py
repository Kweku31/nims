"""Phase 1 adapter: original profiling math, shared execution/checkpoint I/O."""
from pathlib import Path
from .core import legacy_run, find_new_run


def run(dataset: Path, base: Path, config: dict):
    base.mkdir(parents=True, exist_ok=True)
    legacy_run('01_profiling_updated.py', [str(dataset), '--output-dir', str(base),
               '--threshold', str(config.get('phase1_correlation_threshold', .95))], base/'phase1.log')
    folder = find_new_run(base, 'dataset_summary.csv')
    return {'run': str(folder), 'artifacts': [str(folder/'dataset_summary.csv'), str(folder/'column_profile.csv')]}

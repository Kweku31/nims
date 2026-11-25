"""Phase 5 adapter: reconstruct from verified bundles; no extra classifiers."""
from pathlib import Path
from .core import legacy_run, find_new_run


def run(experiments: dict, source: Path, base: Path, config: dict):
    base.mkdir(parents=True, exist_ok=True)
    argv = ['--output-dir',str(base), '--full-reference',str(source),
            '--distance-samples',str(config.get('distance_samples',200)),
            '--neighbor-k', *[str(k) for k in config.get('neighbor_k',[5,10])],
            '--seed',str(config.get('seed',42))]
    for label, info in experiments.items():
        argv += ['--experiment', info['run'],info['source']]
    legacy_run('06_utility_evaluation_updated.py', argv, base/'phase5.log')
    folder = find_new_run(base, 'phase5_utility_summary.csv')
    return {'run':str(folder),
            'artifacts':[str(folder/'phase5_utility_summary.csv'),
                         str(folder/'phase5_feature_retention.csv'),
                         str(folder/'phase5_nearest_neighbor_overlap.csv')]}

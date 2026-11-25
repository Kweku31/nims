"""Phase 4 adapter: do not reimplement PCA or AE; use verified legacy engine."""
from pathlib import Path
from .core import legacy_run, find_new_run


def run(dataset: Path, base: Path, config: dict):
    base.mkdir(parents=True, exist_ok=True)
    argv = [str(dataset), '--output-dir', str(base), '--methods','pca','autoencoder',
            '--k', *[str(k) for k in config.get('k',[2,4,8])],
            '--ae-backend',config.get('ae_backend','cpu'),
            '--ae-batch-size',str(config.get('ae_batch_size',256)),
            '--ae-cpu-threads',str(config.get('ae_cpu_threads',0)),
            '--ae-progress-interval',str(config.get('ae_progress_interval',10)),
            '--ae-max-iter',str(config.get('ae_max_iter',500)),
            '--ae-tol',str(config.get('ae_tol',1e-4)),
            '--ae-patience',str(config.get('ae_patience',20)),
            '--seed', str(config.get('seed',42)),
            '--lossless-formats','gzip','zstd','parquet',
            '--bandwidth-mbps',str(config.get('bandwidth_mbps',100))]
    if config.get('strict_dependencies', True):
        argv += ['--strict-lossless']
    legacy_run('04_dimensionality_reduction_updated.py', argv, base/'phase4.log')
    folder = find_new_run(base, 'phase4_comparison.csv')
    return {'run': str(folder), 'source': str(dataset),
            'artifacts':[str(folder/'phase4_comparison.csv'),str(folder/'phase4_lossless_baselines.csv'),
                         str(folder/'phase4_metadata.json'),
                         *[str(p) for p in sorted(folder.iterdir()) if p.is_file() and
                           p.name.endswith(('.npz', '.sha256', '.csv.gz', '.csv.zst', '.parquet'))]]}

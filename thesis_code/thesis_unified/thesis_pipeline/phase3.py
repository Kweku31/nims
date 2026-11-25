"""Phase 3 adapter: all seven full-cohort missingness/clinical-review variants."""
from pathlib import Path
from .core import legacy_run, find_new_run


def run(dataset: Path, base: Path, config: dict):
    base.mkdir(parents=True, exist_ok=True)
    argv = [str(dataset), '--output-dir', str(base),
            '--correlation-action', str(config.get('correlation_action','flag')),
            '--correlation-threshold',str(config.get('correlation_threshold',.95)),
            '--min-correlation-observations',str(config.get('min_correlation_observations',200)),
            '--min-correlation-patients',str(config.get('min_correlation_patients',30)),
            '--patient-coverage-min',str(config.get('patient_coverage_min',.75)),
            '--missingness-thresholds', *[str(x) for x in config.get('missingness_thresholds',[.8,.9,.95])],
            '--clinically-protected', *config.get('clinically_protected',['Lactate'])]
    legacy_run('03_feature_selection_all_thresholds_clinical.py', argv, base/'phase3.log')
    folder = find_new_run(base, 'threshold_comparison.csv')
    selected = {}
    for d in sorted(folder.iterdir()):
        if d.is_dir() and (d/'selected_dataset.csv').is_file():
            selected[d.name] = str(d/'selected_dataset.csv')
    return {'run': str(folder), 'selected': selected,
            'artifacts':[str(folder/'threshold_comparison.csv'), str(folder/'run_metadata.json'),
                         *selected.values()]}

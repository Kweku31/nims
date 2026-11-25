"""Run the real six-phase pipeline and resume it, using synthetic data and no SSH.

Usage from project root: python tests/synthetic_pipeline_v7.py --output-dir /tmp/v7-smoke
The output directory must be new. SSH/SCP executables are replaced with failing
sentinels; preflight is also patched to fail if invoked in the main process.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_thesis
from thesis_pipeline import core, phase2, phase6


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--ae-backend', choices=['cpu','gpu'], default='cpu')
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(20261113)
    n_patients, hours = 16, 4
    n = n_patients * hours
    data = pd.DataFrame({'patient_id': np.repeat(np.arange(n_patients), hours),
                         'time': np.tile(np.arange(hours), n_patients),
                         'SepsisLabel': np.repeat(np.arange(n_patients) % 2, hours),
                         'Age': np.repeat(rng.integers(25, 80, n_patients), hours),
                         'ICULOS': np.tile(np.arange(1, hours+1), n_patients),
                         'HospAdmTime': np.repeat(-rng.uniform(1, 20, n_patients), hours)})
    for name, center, spread in [('HR', 85, 10), ('O2Sat', 96, 1), ('Temp', 37, .3),
                                  ('SBP', 120, 12), ('MAP', 80, 7), ('DBP', 65, 6),
                                  ('Resp', 18, 2), ('Lactate', 1.5, .25), ('Glucose', 110, 15)]:
        data[name] = rng.normal(center, spread, n)
        data.loc[rng.choice(n, 4, replace=False), name] = np.nan
    data['SparseLab'] = np.nan
    data.loc[[0, 9], 'SparseLab'] = [1.1, 1.3]
    source = root/'synthetic.csv'; data.to_csv(source, index=False)
    config = {
        'ae_backend':args.ae_backend, 'ae_batch_size':16, 'ae_progress_interval':5,
        'dataset': str(source), 'output_dir': str(root/'run'), 'k': [2], 'ae_max_iter': 15,
        'feature_sets': ['FS_95_clinical_review'], 'transfer_mode': 'simulated',
        'fallback_simulated': False, 'transfer_trials': 2, 'packaging_runs': 1,
        'distance_samples': n_patients, 'neighbor_k': [5, 10], 'compare_npz_codecs': True,
        'model_reuse_count': 4, 'continue_independent_errors': False,
        'min_correlation_observations': 10, 'min_correlation_patients': 3,
    }
    config_path = root/'config.json'; core.atomic_json(config_path, config)
    blocked = root/'no_network'; blocked.mkdir()
    marker = root/'unexpected_network_attempt'
    for name in ('ssh', 'scp'):
        script = blocked/name
        script.write_text('#!/bin/sh\necho blocked >> "'+str(marker)+'"\nexit 97\n')
        script.chmod(0o755)
    argv = ['run_thesis.py', '--config', str(config_path)]
    with patch.dict(os.environ, {'PATH': str(blocked)+os.pathsep+os.environ.get('PATH', ''),
                                 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}), \
            patch.object(sys, 'argv', argv), \
            patch.object(core, 'ssh_preflight', side_effect=AssertionError('Unexpected SSH preflight')), \
            patch.object(phase2, 'ssh_preflight', side_effect=AssertionError('Unexpected Phase 2 SSH')), \
            patch.object(phase6, 'ssh_preflight', side_effect=AssertionError('Unexpected Phase 6 SSH')):
        run_thesis.main()
        status = core.load_json(root/'run/run_status.json')
        checkpoint = Path(status['checkpoint_file'])
        first = core.load_json(checkpoint)
        first_reports = Path(status['results_directory'])
        first_hashes = {p.name: core.sha256(p) for p in first_reports.iterdir()}
        run_thesis.main()
        status = core.load_json(root/'run/run_status.json')
        second = core.load_json(checkpoint)
    assert not marker.exists(), 'An SSH/SCP command was attempted'
    assert status['status'] == 'complete'
    for name, stage in first['stages'].items():
        assert stage['status'] == 'complete', name
        if name != 'final_decision':
            assert stage == second['stages'][name], f'Checkpoint was not reused: {name}'
        assert core.validate_artifacts(second['stages'][name]['result'], require_checksums=True), name
    results = Path(status['results_directory'])
    assert results != first_reports
    assert results.parent == first_reports.parent == root/'run/results'
    assert len(list(results.parent.iterdir())) == 2
    assert len(first_hashes) == 6
    assert first_hashes == {p.name: core.sha256(p) for p in first_reports.iterdir()}
    manifest = core.load_json(results/'run_manifest.json')
    assert manifest['phase6_packages_completed'] == manifest['phase6_packages_expected'] == 18
    assert manifest['remote_verified_packages'] == 0
    assert manifest['completion_status'] == 'provisional_incomplete_or_simulated'
    assert manifest['primary_weight_profile'] == 'equal'
    assert manifest['decision_weights']['equal'] == [1/7]*7
    assert not manifest['phase6_failures']
    evidence = pd.read_csv(results/'01_integrated_evidence.csv')
    rankings = pd.read_csv(results/'02_decision_rankings.csv')
    assert len(evidence) == 36
    assert set(evidence.delivery_scenario) == {'fresh_data', 'existing_payload'}
    assert evidence.criteria_available.all(), evidence.loc[~evidence.criteria_available].to_string()
    assert not evidence.measured_completely.any()
    assert set(rankings.decision_evidence_status) == {'simulated_provisional'}
    assert np.isfinite(rankings.topsis_score).all()
    timings = evidence.pivot(index='package_id', columns='delivery_scenario', values='effective_delivery_seconds')
    assert (timings.fresh_data > timings.existing_payload).all()
    assert set(evidence.method) == {'gzip', 'zstd', 'parquet', 'pca', 'autoencoder'}
    assert set(evidence.codec) == {'native', 'gzip', 'zstd'}
    assert (results/'FINAL_REPORT.md').read_text(encoding='utf-8').count('existing_payload') > 1
    summary = {'status': 'passed', 'ae_backend':args.ae_backend, 'rows': n, 'patients': n_patients, 'packages': 18,
               'evidence_rows': len(evidence), 'ranking_rows': len(rankings),
               'checkpoint_resume_verified': True, 'real_ssh_attempts': 0,
               'timestamped_report_snapshots': 2, 'previous_reports_preserved': True,
               'report_directory': str(results)}
    core.atomic_json(root/'validation_summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

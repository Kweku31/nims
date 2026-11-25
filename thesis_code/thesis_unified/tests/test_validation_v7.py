"""Offline regressions for v7 trust gates, timing and checkpoint dependencies."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

import run_thesis
from thesis_pipeline import core, decision, phase2, phase3, phase4, phase6
from test_validation_v6 import rows


class ValidationV7Tests(unittest.TestCase):
    def test_unverified_ssh_never_ranked_or_recommended(self):
        for verified, trials in [(False, 3), (True, 0), ('False', 3), (True, float('inf')), (True, 1.5)]:
            with self.subTest(verified=verified, trials=trials):
                e = rows().assign(network_mode='ssh', remote_sha256_verified=verified,
                                  remote_trials_completed=trials)
                assessed, ranking, notes = decision.decision_tables(e)
                self.assertTrue(ranking.empty)
                self.assertFalse(assessed.eligible.any())
                report = decision.render_report(assessed, ranking, notes,
                                                {'run_id': 'test', 'input_sha256': 'test'})
                self.assertIn('No conditional method recommendation', report)
                self.assertIn('| none |', report)

    def test_ssh_trial_count_and_separate_network_pools(self):
        e = rows()
        ssh = e.assign(network_mode='ssh', remote_sha256_verified=True, remote_trials_completed=2)
        a, r, _ = decision.decision_tables(ssh, {'transfer_trials': 3})
        self.assertFalse(a.eligible.any())
        self.assertTrue(r.empty)
        ssh['remote_trials_completed'] = 3
        combined = pd.concat([e, ssh], ignore_index=True)
        a, r, _ = decision.decision_tables(combined, {'transfer_trials': 3})
        self.assertEqual(set(r.network_mode), {'ssh', 'simulated_ideal'})
        self.assertTrue(r.loc[r.network_mode.eq('ssh'), 'remote_sha256_verified'].all())
        self.assertEqual(int(a.empirical_ssh_eligible.sum()), 3)

    def test_empty_rankings_have_readable_schema(self):
        for e in [pd.DataFrame(), rows().assign(checksum_passed=False)]:
            a, r, notes = decision.decision_tables(e)
            self.assertTrue(r.empty)
            with tempfile.TemporaryDirectory() as td:
                path = Path(td)/'ranking.csv'
                r.to_csv(path, index=False)
                self.assertEqual(list(pd.read_csv(path).columns), decision.RANKING_COLUMNS)
            report = decision.render_report(a, r, notes, {'run_id': 'empty', 'input_sha256': 'test'})
            self.assertIn('No conditional method recommendation', report)
        self.assertTrue(decision.topsis(pd.DataFrame(), decision.WEIGHTS['balanced']).empty)

    def test_complete_report_generation_with_no_packages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root/'input.csv'; source.write_text('x\n1\n')
            results = root/'results'; results.mkdir()
            pd.DataFrame([{'n_rows': 1}]).to_csv(root/'dataset_summary.csv', index=False)
            pd.DataFrame([{'format': 'csv_gzip'}]).to_csv(root/'transfer_benchmark.csv', index=False)
            pd.DataFrame([{'experiment': 'FS_test'}]).to_csv(root/'threshold_comparison.csv', index=False)
            ctx = SimpleNamespace(results=results, key='empty',
                                  state={'run_id': 'empty', 'input_sha256': core.sha256(source)})
            staged = {name: {'run': str(root)} for name in ('phase1', 'phase2', 'phase3')}
            output = run_thesis.generate_results(ctx, source, run_thesis.DEFAULTS, staged,
                                                {'original': {'run': str(root)}}, {'run': str(root)}, [],
                                                [{'configuration': 'test', 'error': 'no package'}])
            self.assertEqual(len(output['artifacts']), 6)
            self.assertTrue(pd.read_csv(results/'02_decision_rankings.csv').empty)
            self.assertTrue(pd.read_csv(results/'04_network_trials.csv').empty)
            self.assertEqual(core.load_json(results/'run_manifest.json')['completion_status'],
                             'provisional_incomplete_or_simulated')
            self.assertIn('No conditional method recommendation', (results/'FINAL_REPORT.md').read_text())

    def test_all_nonfinite_and_out_of_range_criteria_excluded(self):
        for col in decision.CRITERIA:
            for value in [float('nan'), float('inf'), -float('inf')]:
                with self.subTest(col=col, value=value):
                    e = rows(); e[col] = value
                    a, r, _ = decision.decision_tables(e)
                    self.assertFalse(a.criteria_available.any())
                    self.assertTrue(r.empty)
                    with self.assertRaises(ValueError):
                        decision.topsis(e, decision.WEIGHTS['balanced'])
        invalid = [(c, -1) for c in decision.CRITERIA if not c.startswith('R2_')]
        invalid += [('R2_retained_variation_observed_STANDARDIZED', 1.01),
                    ('knn5_overlap_original_vs_reconstruction', 1.01)]
        invalid += [(c, 100.01) for c in decision.CRITERIA if c.endswith('_pct')]
        for col, value in invalid:
            with self.subTest(col=col, value=value):
                e = rows(); e[col] = value
                self.assertTrue(decision.decision_tables(e)[1].empty)

    def test_negative_r2_and_large_finite_values_are_valid(self):
        e = rows(); e['R2_retained_variation_observed_STANDARDIZED'] = [-1, -10, -1e300]
        e['total_transmitted_bytes'] = [1e300, 2e300, 3e300]
        a, r, _ = decision.decision_tables(e)
        self.assertTrue(a.eligible.all())
        self.assertTrue(np.isfinite(r.topsis_score).all())
        self.assertTrue(r.topsis_score.between(0, 1).all())

    def test_delivery_costs_and_separate_ranks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pd.DataFrame([{'method': 'pca', 'k': 2, 'fit_seconds': 12., 'encode_seconds': 3.,
                           'packaging_seconds': 5., 'clinical_screen_new_violation_pct': 0.}]).to_csv(
                               root/'phase4_comparison.csv', index=False)
            pd.DataFrame([{'method': m, 'packaging_seconds': s} for m, s in
                          [('gzip', 7.), ('zstd', 8.), ('parquet', 9.)]]).to_csv(
                              root/'phase4_lossless_baselines.csv', index=False)
            packages, utility = [], []
            for method, lossless in [('pca', False), ('gzip', True), ('zstd', True), ('parquet', True)]:
                entry = rows().iloc[0].to_dict()
                entry.update(method=method, lossless=lossless, k=None if lossless else 2,
                             phase4_run_directory=str(root), package_id=method, end_to_end_seconds=20.)
                packages.append(entry)
                utility.append({**entry, 'method': ('lossless_' if lossless else '')+method})
            path = root/'utility.csv'; pd.DataFrame(utility).to_csv(path, index=False)
            evidence = decision.join_evidence(packages, path, None, model_reuse_count=4)
            for method, fresh in [('pca', 31), ('gzip', 27), ('zstd', 28), ('parquet', 29)]:
                r = evidence[evidence.method.eq(method)].set_index('delivery_scenario')
                self.assertEqual(r.loc['existing_payload', 'effective_delivery_seconds'], 20)
                self.assertEqual(r.loc['fresh_data', 'effective_delivery_seconds'], fresh)
            _, rankings, _ = decision.decision_tables(evidence)
            self.assertEqual(set(rankings.delivery_scenario), set(decision.DELIVERY_SCENARIOS))
            self.assertEqual(len(rankings[rankings['rank'].eq(1)]), 2 * 3 * len(decision.WEIGHTS))
            # A missing/negative preparation component excludes fresh data only.
            for val in [np.nan, -1]:
                p4 = pd.read_csv(root/'phase4_comparison.csv'); p4['encode_seconds'] = val
                p4.to_csv(root/'phase4_comparison.csv', index=False)
                evidence = decision.join_evidence(packages[:1], path, None)
                assessed, rankings, _ = decision.decision_tables(evidence)
                self.assertEqual(set(rankings.delivery_scenario), {'existing_payload'})

    def test_preflight_respects_disabled_fallback_before_building(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = {'transfer_mode': 'auto', 'fallback_simulated': False, 'remote': 'user@example.org'}
            for module in (phase2, phase6):
                with self.subTest(phase=module.__name__), patch.object(module, 'ssh_preflight', return_value=False), \
                        patch.object(module, 'legacy_run') as legacy:
                    with self.assertRaisesRegex(RuntimeError, 'fallback is disabled'):
                        if module is phase2:
                            phase2.run(root/'input.csv', root/'p2', config)
                        else:
                            phase6.package_and_benchmark('original', {'run': str(root), 'source': str(root/'input.csv')},
                                                         'gzip', None, 'native', root/'p6', config)
                    legacy.assert_not_called()

    def test_adapter_artifacts_include_selected_payloads_and_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            variant = root/'FS_test'; variant.mkdir()
            selected = variant/'selected_dataset.csv'; selected.write_text('x\n1\n')
            for module in (phase3, phase4):
                with patch.object(module, 'legacy_run'), patch.object(module, 'find_new_run', return_value=root):
                    if module is phase3:
                        result = module.run(root/'input.csv', root, {})
                        self.assertIn(str(selected), result['artifacts'])
                    else:
                        for name in ['pca_k2_transfer_payload.npz', 'source_csv_gzip6.csv.gz',
                                     'source_csv_zstd3.csv.zst', 'source_parquet_zstd.parquet']:
                            (root/name).write_bytes(b'payload')
                            (root/(name+'.sha256')).write_text('digest')
                        result = module.run(root/'input.csv', root, {})
                        for p in root.iterdir():
                            if p.is_file(): self.assertIn(str(p), result['artifacts'])

    def test_code_fingerprint_includes_runner_and_path_names(self):
        hashes = core.code_fingerprints()
        self.assertIn('run_thesis.py', hashes)
        self.assertIn('thesis_pipeline/legacy/__init__.py', hashes)
        self.assertIn('thesis_pipeline/__init__.py', hashes)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)/'input.csv'; src.write_text('x\n1\n')
            original = core.Checkpoint(Path(td), {}, src).key
            with patch.object(core, 'code_fingerprints', return_value={**hashes, 'run_thesis.py': 'changed'}):
                self.assertNotEqual(original, core.Checkpoint(Path(td), {}, src).key)

    def test_checkpoint_invalidates_dependents_after_same_path_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); src = root/'input.csv'; src.write_text('x\n1\n')
            calls = []
            def task(name):
                calls.append(name); out = root/name; out.write_text('same bytes')
                return {'artifacts': [str(out)]}
            with core.Checkpoint(root, {}, src) as ck:
                def pipeline():
                    p4 = ck.stage('phase4', lambda: task('payload'))
                    for stage in ('phase5', 'phase6'):
                        ck.stage(stage, lambda s=stage: task(s),
                                 dependencies={'phase4': core.dependency_fingerprint(p4)})
                pipeline(); pipeline()
                self.assertEqual(len(calls), 3)
                (root/'payload').write_text('tampered')
                pipeline()
                self.assertEqual(calls, ['payload', 'phase5', 'phase6'] * 2)
                # Legacy/incomplete checksum coverage must never count as verified.
                ck.state['stages']['phase4']['result']['artifact_sha256'] = {}
                pipeline()
                self.assertEqual(len(calls), 9)

    def test_orchestrator_tracks_upstream_content_for_every_dependent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); src = root/'input.csv'; src.write_text('x\n1\n')
            pd.DataFrame({'format': ['csv_gzip', 'parquet']}).to_csv(root/'transfer_benchmark.csv', index=False)
            ctx = SimpleNamespace(work=root, results=root, dependencies={})
            def stage(name, function, **kwargs):
                ctx.dependencies[name] = kwargs.get('dependencies', {})
                result = {'run': str(root), 'source': str(src), 'artifacts': [], 'checkpoint_generation': 1}
                if name == 'phase3': result['selected'] = {'FS_test': str(src)}
                return result
            ctx.stage = stage
            with patch.object(phase6, 'configurations', return_value=[('gzip', None, 'native')]):
                run_thesis.execute_pipeline(ctx, SimpleNamespace(force=[]),
                                            {**run_thesis.DEFAULTS, 'feature_sets': ['FS_test']}, src)
            for stage in ('phase2_topsis', 'phase4_original', 'phase4_FS_test', 'phase5',
                          'phase6_original_gzip_n_native', 'phase6_FS_test_gzip_n_native'):
                self.assertTrue(ctx.dependencies[stage], stage)

    def test_phase2_expansion_allowed_but_invalid_times_rejected(self):
        spec = importlib.util.spec_from_file_location('phase2_topsis_test', core.LEGACY/'topsis_transfer_decision.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        data = pd.DataFrame({'format': ['small', 'expanded'], 'size_reduction_pct': [25., -150.],
                             'packaging_mean_seconds': [1., 1.], 'transfer_mean_seconds': [2., 2.]})
        result = module.calculate_topsis(data, [1, 1, 1])['ranking']
        self.assertEqual(result.iloc[0]['format'], 'small')
        for col, value in [('size_reduction_pct', 101), ('packaging_mean_seconds', -1),
                           ('transfer_mean_seconds', np.inf)]:
            invalid = data.copy(); invalid.loc[0, col] = value
            with self.assertRaises(ValueError): module.calculate_topsis(invalid, [1, 1, 1])
        data['transfer_mode'] = 'ssh'; data['integrity_verified'] = [False, True]
        self.assertEqual(list(module.calculate_topsis(data, [1, 1, 1])['ranking']['format']), ['expanded'])


if __name__ == '__main__':
    unittest.main()

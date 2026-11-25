"""Offline boundary checks for Phase 2 adaptive benchmark trials."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_thesis
from thesis_pipeline import phase2

PATH = Path(__file__).resolve().parents[1]/'thesis_pipeline/legacy/02_transfer_benchmark.py'
spec = importlib.util.spec_from_file_location('phase2_repetition_engine', PATH)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


class Phase2RepetitionTests(unittest.TestCase):
    def test_first_transfer_alone_controls_count_in_both_modes(self):
        for mode in ('ssh', 'simulated'):
            for first, expected in [(9.999, 10), (10.0, 10), (10.001, 1)]:
                with self.subTest(mode=mode, first=first):
                    args = SimpleNamespace(transfer_runs=10, repeat_threshold_seconds=10,
                                           transfer_mode=mode, bandwidth_mbps=100,
                                           host='fake', user='test', port=22, remote_dir='/tmp/test')
                    artifact = SimpleNamespace(format_name='csv_gzip', file_bytes=100)
                    # Later slow transfers do not reverse the first-trial decision.
                    measurements = [SimpleNamespace(transfer_seconds=value, throughput_mbps=1,
                                                     verification_seconds=1000,
                                                     integrity_verified=True)
                                    for value in [first]+[30]*9]
                    name = 'real_transfer' if mode == 'ssh' else 'simulated_transfer'
                    with patch.object(engine, name, side_effect=measurements) as transfer, \
                            contextlib.redirect_stdout(io.StringIO()):
                        times, _, checks, integrity = engine.benchmark_transfer(artifact, args)
                    self.assertEqual(len(times), expected)
                    self.assertEqual(transfer.call_count, expected)
                    self.assertEqual(len(checks), expected)
                    self.assertTrue(all(integrity))

    def test_terminal_failure_aborts_instead_of_counting_a_trial(self):
        args = SimpleNamespace(transfer_runs=10, repeat_threshold_seconds=10,
                               transfer_mode='ssh', host='fake', user='test', port=22, remote_dir='/tmp/test')
        artifact = SimpleNamespace(format_name='csv', file_bytes=100)
        with patch.object(engine, 'real_transfer', side_effect=RuntimeError('checksum mismatch')) as transfer, \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'checksum'):
            engine.benchmark_transfer(artifact, args)
        self.assertEqual(transfer.call_count, 1)

    def test_adapter_applies_phase2_policy_on_fallback_and_keeps_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {'transfer_mode': 'auto', 'remote': 'test@fake', 'fallback_simulated': True,
                      'transfer_trials': 3, 'phase2_transfer_trials': 7,
                      'phase2_repeat_threshold_seconds': 12.5}
            with patch.object(phase2, 'ssh_preflight', return_value=True), \
                    patch.object(phase2, 'legacy_run', side_effect=[RuntimeError('offline'), None]) as run, \
                    patch.object(phase2, 'find_new_run', return_value=root), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = phase2.run(root/'input.csv', root, config)
            self.assertEqual(result['mode'], 'simulated')
            for call in run.call_args_list:
                argv = call.args[1]
                self.assertEqual(argv[argv.index('--transfer-runs')+1], '7')
                self.assertEqual(argv[argv.index('--repeat-threshold-seconds')+1], '12.5')
            self.assertIn(str(root/'transfer_metadata.json'), result['artifacts'])

    def test_defaults_overrides_and_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'input.csv'; source.write_text('x\n1\n')
            with patch.object(sys, 'argv', ['run_thesis.py', '--dataset', str(source)]):
                opts, _ = run_thesis.normalize_options(run_thesis.arguments())
            self.assertEqual(opts['phase2_transfer_trials'], 10)
            self.assertEqual(opts['phase2_repeat_threshold_seconds'], 10)
            self.assertEqual(opts['transfer_trials'], 10)
            with patch.object(sys, 'argv', ['run_thesis.py', '--dataset', str(source),
                                          '--phase2-transfer-trials', '6',
                                          '--phase2-repeat-threshold-seconds', '15']):
                opts, _ = run_thesis.normalize_options(run_thesis.arguments())
            self.assertEqual(opts['phase2_transfer_trials'], 6)
            self.assertEqual(opts['phase2_repeat_threshold_seconds'], 15)
            for key, values in [('phase2_transfer_trials', [0, -1, 1.5, True, '10']),
                                ('phase2_repeat_threshold_seconds', [0, -1, float('nan'), float('inf'), True])]:
                for value in values:
                    config = Path(tmp)/'config.json'; config.write_text(json.dumps({key: value}))
                    with self.subTest(key=key, value=value), \
                            patch.object(sys, 'argv', ['run_thesis.py', '--dataset', str(source), '--config', str(config)]), \
                            self.assertRaisesRegex(ValueError, key):
                        run_thesis.normalize_options(run_thesis.arguments())


if __name__ == '__main__':
    unittest.main()

"""Adaptive Phase 6 trials must remain complete, verified and auditable."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from thesis_pipeline import decision, ssh_transport
from test_validation_v6 import rows

PATH = Path(__file__).resolve().parents[1]/'thesis_pipeline/legacy/06_transfer_package.py'
spec = importlib.util.spec_from_file_location('phase6_repetition_engine', PATH)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


class Phase6RepetitionTests(unittest.TestCase):
    def send(self, folder, first, fail_second=False):
        archive = folder/'payload.tar'; archive.write_bytes(b'payload')
        archive.with_suffix('.tar.sha256').write_text('sidecar')
        args = SimpleNamespace(archive=archive, remote='user@fake', remote_dir='/tmp/remote',
                               trials=10, repeat_threshold_seconds=10., ssh_port=22,
                               report_csv=folder/'trials.csv')
        timings = [dict(scp_seconds=t, remote_sha256_verified=True, attempts=1)
                   for t in [first]+[30]*9]
        if fail_second:
            timings[1] = RuntimeError('connection lost')
        with patch.object(engine, 'verify_archive', return_value={'package_id':'test'}), \
                patch.object(engine.ssh_transport, 'configure_args'), \
                patch.object(engine.ssh_transport, 'deliver', side_effect=timings), \
                contextlib.redirect_stdout(io.StringIO()):
            return engine.send(args)

    def test_sender_boundary_later_slow_trials_and_csv_policy(self):
        for first, count in [(9.99, 10), (10., 10), (10.01, 1)]:
            with self.subTest(first=first), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                records = self.send(folder, first)
                self.assertEqual(len(records), count)
                saved = pd.read_csv(folder/'trials.csv').to_dict('records')
                self.assertEqual(ssh_transport.validate_trial_report(saved, 10, 10.), count)
                self.assertTrue(all(r['requested_trials'] == count for r in saved))
                self.assertTrue(all(r['maximum_trials'] == 10 for r in saved))

    def test_failed_later_trial_keeps_partial_report_ineligible(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with self.assertRaisesRegex(RuntimeError, 'connection lost'):
                self.send(folder, 1., fail_second=True)
            saved = pd.read_csv(folder/'trials.csv').to_dict('records')
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['requested_trials'], 10)
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                ssh_transport.validate_trial_report(saved, 10, 10.)

    def test_report_rejects_forged_count_sequence_checksum_and_threshold(self):
        with tempfile.TemporaryDirectory() as temp:
            records = self.send(Path(temp), 12.)
            for field, value in [('remote_sha256_verified',False), ('trial',2),
                                 ('maximum_trials',1), ('requested_trials',10),
                                 ('first_transfer_seconds',1), ('repeat_threshold_seconds',100),
                                 ('scp_seconds',float('nan')), ('trial_policy','unknown')]:
                forged = [dict(records[0], **{field:value})]
                with self.subTest(field=field), self.assertRaises(ValueError):
                    ssh_transport.validate_trial_report(forged, 10, 10.)

    def test_decision_accepts_only_complete_adaptive_counts(self):
        config = {'transfer_trials':10, 'phase6_repeat_threshold_seconds':10.}
        base = rows().assign(network_mode='ssh', remote_sha256_verified=True,
                             remote_trials_completed=1, remote_trials_requested=1,
                             remote_trials_maximum=10, remote_repeat_threshold_seconds=10.,
                             remote_first_transfer_seconds=12.,
                             remote_trial_policy=ssh_transport.TRIAL_POLICY)
        assessed, ranking, _ = decision.decision_tables(base, config)
        self.assertTrue(assessed.eligible.all())
        self.assertFalse(ranking.empty)
        for changes in [dict(remote_first_transfer_seconds=10.),
                        dict(remote_first_transfer_seconds=float('nan')),
                        dict(remote_trials_maximum=1), dict(remote_repeat_threshold_seconds=1.),
                        dict(remote_trial_policy=''), dict(remote_sha256_verified=False),
                        dict(remote_trials_completed=2), dict(remote_trials_requested=10)]:
            with self.subTest(changes=changes):
                assessed, ranking, _ = decision.decision_tables(base.assign(**changes), config)
                self.assertFalse(assessed.eligible.any())
                self.assertTrue(ranking.empty)
        fast = base.assign(remote_first_transfer_seconds=10., remote_trials_completed=10,
                           remote_trials_requested=10)
        self.assertTrue(decision.decision_tables(fast, config)[0].eligible.all())

    def test_trial_policy_rejects_invalid_inputs(self):
        for first, maximum, threshold in [(0,0,10),(0,1.5,10),(0,True,10),
                                          (-1,10,10),(float('inf'),10,10),
                                          (0,10,float('nan')),(0,10,0),(0,10,-1)]:
            with self.subTest(values=(first,maximum,threshold)), self.assertRaises(ValueError):
                ssh_transport.required_trials(first, maximum, threshold)


if __name__ == '__main__':
    unittest.main()

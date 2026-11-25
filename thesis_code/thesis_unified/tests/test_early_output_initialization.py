"""Early output creation must not depend on Phase 1 completion."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_thesis


class EarlyOutputInitializationTests(unittest.TestCase):
    def test_created_before_phase1_and_preserved_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / 'sample.csv'
            src.write_text('patient_id,time,HR\np1,0,72\n')
            output = root / 'out'
            observed = []

            def simulated_phase1(ctx, args, opts, dataset):
                # There must already be a usable log and status while phase 1
                # is still running, not only when it completes.
                log = output / 'pipeline.log'
                self.assertTrue(log.is_file())
                self.assertIn('PIPELINE INVOCATION START', log.read_text())
                self.assertTrue((output/'results').is_dir())
                status = json.loads((output/'run_status.json').read_text())
                self.assertEqual(status['status'], 'running')
                self.assertEqual(status['run_id'], ctx.key)
                print('Phase 1 is still active', flush=True)
                observed.append('inside')
                raise RuntimeError('intentional phase1 test failure')

            with patch.object(sys, 'argv', ['run_thesis.py', '--dataset', str(src),
                                             '--output-dir', str(output)]), \
                 patch.object(run_thesis, 'execute_pipeline', simulated_phase1), \
                 contextlib.redirect_stdout(io.StringIO()) as stdout:
                with self.assertRaisesRegex(RuntimeError, 'intentional phase1 test failure'):
                    run_thesis.main()
            self.assertEqual(observed, ['inside'])
            self.assertIn('Phase 1 is still active', stdout.getvalue())
            self.assertNotIn(' UTC |', stdout.getvalue())
            log = (output/'pipeline.log').read_text()
            self.assertIn('Phase 1 is still active', log)
            self.assertIn('PIPELINE ABORTED', log)
            self.assertEqual(json.loads((output/'run_status.json').read_text())['status'], 'failed')

    def test_success_publishes_results_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            src=root/'sample.csv'
            src.write_text('patient_id,time,HR\np1,0,72\n')
            out=root/'output'
            names=('FINAL_REPORT.md','01_integrated_evidence.csv','02_decision_rankings.csv',
                   '03_phase_overview.csv','04_network_trials.csv','run_manifest.json')
            def fake_pipeline(ctx, args, opts, dataset):
                assert (out/'pipeline.log').is_file()
                assert (out/'results').is_dir()
                for name in names:
                    (ctx.results/name).write_text('sample data')
            with patch.object(sys,'argv',['run_thesis.py','--dataset',str(src),
                                          '--output-dir',str(out)]), \
                 patch.object(run_thesis,'execute_pipeline',fake_pipeline), \
                 contextlib.redirect_stdout(io.StringIO()):
                run_thesis.main()
            status = json.loads((out/'run_status.json').read_text())
            published = Path(status['results_directory'])
            self.assertEqual(published.parent, out/'results')
            self.assertIn('_UTC_', published.name)
            for name in names:
                self.assertTrue((published/name).is_file())
            self.assertEqual(status['status'],'complete')

    def test_config_output_used_before_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            out=root/'configured'
            cfg=root/'config.json'
            cfg.write_text(json.dumps({'output_dir':str(out)}))
            # Missing dataset must still produce the configured log and status.
            done=subprocess.run([sys.executable,str(Path(run_thesis.__file__)),
                                 '--config',str(cfg)],capture_output=True,text=True)
            self.assertNotEqual(done.returncode,0)
            self.assertTrue((out/'pipeline.log').is_file())
            self.assertTrue((out/'results').is_dir())
            status=json.loads((out/'run_status.json').read_text())
            self.assertEqual(status['status'],'failed')
            self.assertIn('dataset',status['error'])


if __name__ == '__main__':
    unittest.main()

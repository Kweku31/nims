"""Fast, offline checks for the single end-to-end live log."""
import sys
import tempfile
import unittest
from pathlib import Path
from thesis_pipeline.core import Checkpoint, subprocess_run, unified_logging, log_run_id


class UnifiedLoggingTests(unittest.TestCase):
    def test_all_phases_append_and_resume_same_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.csv'
            source.write_text('x\n1\n')
            log = root / 'pipeline.log'
            run_keys = []
            for invocation in range(2):
                with unified_logging(log):
                    with Checkpoint(root, {'a': 1}, source) as ck:
                        log_run_id(ck.key)
                        run_keys.append(ck.key)
                        def job():
                            artifact = root / 'artifact.txt'
                            artifact.write_text('OK')
                            print('hello from phase one')
                            return {'artifacts': [str(artifact)]}
                        ck.stage('phase1', job)
            self.assertEqual(run_keys[0], run_keys[1])
            txt = log.read_text()
            self.assertEqual(txt.count('PIPELINE INVOCATION START'), 2)
            self.assertIn('phase=PHASE1 | START phase1', txt)
            self.assertIn('phase=PHASE1 | hello from phase one', txt)
            self.assertIn('phase=PHASE1 | SKIP phase1', txt)
            self.assertEqual(txt.count('hello from phase one'), 1)

    def test_live_child_output_in_unified_and_phase_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with unified_logging(root/'pipeline.log'):
                subprocess_run([sys.executable, '-c',
                                "print('hello from child'); print('next line')"], root/'phase2.log')
            global_txt = (root/'pipeline.log').read_text()
            phase_txt = (root/'phase2.log').read_text()
            for marker in ('hello from child', 'next line'):
                self.assertIn(marker, global_txt)
                self.assertIn(marker, phase_txt)

    def test_failed_child_and_traceback_still_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(RuntimeError):
                with unified_logging(root/'pipeline.log'):
                    subprocess_run([sys.executable, '-c',
                                    "print('pre-failure'); raise RuntimeError('sample failure')"],
                                   root/'phase3.log')
            log = (root/'pipeline.log').read_text()
            self.assertIn('pre-failure',log)
            self.assertIn('sample failure',log)
            self.assertIn('PIPELINE ABORTED',log)


if __name__ == '__main__':
    unittest.main()

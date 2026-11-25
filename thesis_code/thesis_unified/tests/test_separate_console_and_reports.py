"""Guard console output and separate timestamped report snapshots."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis_pipeline.core import unified_logging, phase_context, log_run_id
from run_thesis import publish_current_reports


class ConsoleAndReportTests(unittest.TestCase):
    def test_console_unchanged_log_formatted_and_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'pipeline.log'
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with unified_logging(log):
                    log_run_id('test-run')
                    with phase_context('phase3'):
                        print('Feature selection: 5,000 rows')
                        print('WARNING: skip unavailable format', file=__import__('sys').stderr)
            self.assertEqual(stdout.getvalue(), 'Feature selection: 5,000 rows\n')
            self.assertEqual(stderr.getvalue(), 'WARNING: skip unavailable format\n')
            text = log.read_text()
            self.assertIn('phase=PHASE3 | Feature selection: 5,000 rows', text)
            self.assertIn('WARNING', text)
            self.assertIn('run=test-run', text)
            self.assertTrue(log.exists())

    def test_publish_timestamped_reports_preserves_previous_runs_even_at_same_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'output'
            archived = base / 'runs' / 'hash' / 'results'
            archived.mkdir(parents=True)
            names = ('FINAL_REPORT.md', '01_integrated_evidence.csv',
                     '02_decision_rankings.csv', '03_phase_overview.csv',
                     '04_network_trials.csv', 'run_manifest.json')
            for name in names:
                (archived / name).write_text(f'first: {name}')
            with patch('run_thesis.datetime') as clock:
                clock.now.return_value.strftime.return_value = '20261113_120000_123456_UTC'
                latest = publish_current_reports(archived, base)
                (archived / 'FINAL_REPORT.md').write_text('updated')
                next_run = publish_current_reports(archived, base)
            self.assertEqual(latest.parent, base / 'results')
            self.assertTrue(latest.name.startswith('20261113_120000_123456_UTC_'))
            self.assertNotEqual(latest, next_run)
            self.assertEqual(sorted(p.name for p in latest.iterdir()), sorted(names))
            self.assertEqual((latest / 'FINAL_REPORT.md').read_text(), 'first: FINAL_REPORT.md')
            self.assertEqual((next_run / 'FINAL_REPORT.md').read_text(), 'updated')
            self.assertEqual(sorted(p.name for p in next_run.iterdir()), sorted(names))
            self.assertEqual((archived / 'FINAL_REPORT.md').read_text(), 'updated')

    def test_copy_failure_does_not_publish_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archived = base / 'source'; archived.mkdir()
            names = ('FINAL_REPORT.md', '01_integrated_evidence.csv', '02_decision_rankings.csv',
                     '03_phase_overview.csv', '04_network_trials.csv', 'run_manifest.json')
            for name in names:
                (archived / name).write_text('complete report')
            previous = publish_current_reports(archived, base)
            with patch('run_thesis.shutil.copyfile', side_effect=OSError('copy failed')):
                with self.assertRaisesRegex(OSError, 'copy failed'):
                    publish_current_reports(archived, base)
            self.assertEqual(list((base / 'results').iterdir()), [previous])
            self.assertEqual(len(list(previous.iterdir())), 6)

    def test_publish_failure_does_not_create_incomplete_report_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archived = base / 'runs' / 'hash' / 'results'
            archived.mkdir(parents=True)
            (archived / 'FINAL_REPORT.md').write_text('partial')
            with self.assertRaises(FileNotFoundError):
                publish_current_reports(archived, base)
            self.assertEqual(list((base / 'results').iterdir()), [])


if __name__ == '__main__':
    unittest.main()

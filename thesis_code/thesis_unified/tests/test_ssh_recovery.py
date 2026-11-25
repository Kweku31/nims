"""Fault injection tests. No test contacts a real SSH host."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis_pipeline import ssh_transport as transport
from thesis_pipeline import core


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('THESIS_NETWORK_') and k != 'THESIS_SSH_SETTINGS'}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        transport.configure({'ssh_retry_delay': 0}, self.root)
        self.payload = self.root/'payload.csv'; self.payload.write_text('id,x\n1,2\n')
        self.sidecar = self.root/'payload.csv.sha256'
        self.sidecar.write_text(hashlib.sha256(self.payload.read_bytes()).hexdigest()+'  payload.csv\n')
        self.commands = []

    def successful_command(self, argv, timeout):
        self.commands.append((argv, timeout))
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.payload, self.sidecar)]
        stdout = '\n'.join(d+'  file' for d in hashes) if argv[-1].startswith('sha256sum --') else ''
        return subprocess.CompletedProcess(argv, 0, stdout, '')

    def events(self):
        return [json.loads(line) for line in (self.root/'network_events.jsonl').read_text().splitlines()]

    def test_transient_upload_restarts_trial_and_publishes_only_verified_set(self):
        uploads = []
        def command(argv, timeout):
            if argv[0] == 'scp':
                uploads.append(argv[-1])
                if len(uploads) == 1:
                    raise subprocess.CalledProcessError(255, argv, stderr='Connection reset by peer')
            return self.successful_command(argv, timeout)
        with patch.object(transport, 'command', side_effect=command):
            report = transport.deliver([self.payload, self.sidecar], 'user@fake', 2222, '/tmp/test')
        self.assertEqual(report['failed_attempts'], 1)
        self.assertEqual(report['attempts'], 2)
        self.assertNotEqual(uploads[0], uploads[1])
        self.assertTrue(report['remote_sha256_verified'])
        self.assertGreaterEqual(report['delivery_wall_seconds'], report['scp_seconds']+report['recovery_overhead_seconds'])
        publish = [argv for argv, _ in self.commands if argv[-1].startswith('mv -T')]
        self.assertEqual(len(publish), 1)
        self.assertRegex(Path(report['remote_directory']).name,
                         r'^payload\.csv_verified_\d{8}_\d{6}_\d{6}_UTC_[0-9a-f]{32}$')
        self.assertTrue(all('/payload.csv_unverified_' in path for path in uploads))
        staged = [r for r in self.events() if 'remote_pending_directory' in r]
        self.assertEqual(len(staged), 2)
        self.assertEqual(staged[-1]['remote_verified_directory'], report['remote_directory'])
        self.assertIn('connection_lost', [r['status'] for r in self.events()])
        self.assertIn('retrying', [r['status'] for r in self.events()])
        self.assertEqual(self.events()[-1]['status'], 'connected')

    def test_sidecar_corruption_is_terminal_and_never_published(self):
        def command(argv, timeout):
            result = self.successful_command(argv, timeout)
            if argv[-1].startswith('sha256sum --'):
                result.stdout = result.stdout.splitlines()[0]+'\n'+'0'*64+'  sidecar\n'
            return result
        with patch.object(transport, 'command', side_effect=command), self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
            transport.deliver([self.payload, self.sidecar], 'user@fake', 22, '/tmp/test')
        self.assertFalse(any(argv[-1].startswith('mv ') for argv, _ in self.commands))
        self.assertEqual(self.events()[-1]['status'], 'needs_attention')
        self.assertEqual(self.events()[-1]['attempt'], 1)
        pending = next(r['remote_pending_directory'] for r in self.events()
                       if 'remote_pending_directory' in r)
        self.assertIn('/payload.csv_unverified_', pending)

    def test_directory_names_safe_bounded_and_unique_even_at_same_timestamp(self):
        from datetime import datetime, timezone
        fixed = datetime(2026, 11, 18, 14, 30, 25, 123456, timezone.utc)
        for name in ['sepsis.csv.gz', 'a'*240+'.tar', ' patient $(touch bad);数据.csv', '...']:
            with self.subTest(name=name), patch.object(transport, 'datetime') as clock:
                clock.now.return_value = fixed
                files = [Path(name+'.sha256'), Path(name)]
                pending, verified = transport.delivery_directories(files, '/tmp/test/')
                self.assertNotEqual((pending, verified), transport.delivery_directories(files, '/tmp/test'))
                for directory, status in [(pending, 'unverified'), (verified, 'verified')]:
                    basename = Path(directory).name
                    self.assertLessEqual(len(basename.encode()), 255)
                    self.assertRegex(basename, r'^[A-Za-z0-9_.-]+$')
                    self.assertIn('_'+status+'_20261118_143025_123456_UTC_', basename)
                    self.assertEqual(Path(directory).parent, Path('/tmp/test'))
                self.assertEqual(pending.replace('_unverified_', '_verified_'), verified)
                if name == 'sepsis.csv.gz':
                    self.assertTrue(Path(verified).name.startswith('sepsis.csv.gz_verified_'))

    def test_permanent_errors_never_retry(self):
        for message in ['Permission denied (publickey)', 'Host key verification failed', 'No space left on device', 'Disk quota exceeded', 'unknown failure']:
            with self.subTest(message=message), patch.object(transport, 'command', side_effect=subprocess.CalledProcessError(255, [], stderr=message)) as call:
                with self.assertRaises(subprocess.CalledProcessError):
                    transport.ssh('user@fake', 22, 'true')
                self.assertEqual(call.call_count, 1)

    def test_retry_budget_exponential_delay_and_timeout_classification(self):
        transport.configure({'ssh_retry_delay': 2, 'ssh_max_attempts': 3}, self.root)
        with patch.object(transport, 'command', side_effect=subprocess.TimeoutExpired([], 60)) as command, patch.object(transport.time, 'sleep') as sleep:
            with self.assertRaises(subprocess.TimeoutExpired):
                transport.ssh('user@fake', 22, 'true')
            self.assertEqual(command.call_count, 3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])
        self.assertEqual(self.events()[-1]['status'], 'needs_attention')

    def test_rsync_resumes_only_within_one_trial_and_accounts_for_failure(self):
        uploads = []
        def command(argv, timeout):
            if argv[0] == 'rsync':
                self.assertIn('--partial-dir=.rsync-partial', argv)
                self.assertIn('StrictHostKeyChecking=yes', argv[argv.index('-e')+1])
                uploads.append(argv[-1])
                if len(uploads) == 1:
                    raise subprocess.CalledProcessError(12, argv, stderr='connection unexpectedly closed')
            return self.successful_command(argv,timeout)
        with patch.object(transport, 'command', side_effect=command):
            first = transport.deliver([self.payload,self.sidecar], 'user@fake',2222,'/tmp/test',method='rsync')
            second = transport.deliver([self.payload,self.sidecar], 'user@fake',2222,'/tmp/test',method='rsync')
        self.assertEqual(uploads[0],uploads[1])
        self.assertNotEqual(uploads[1],uploads[2])
        self.assertNotIn('scp_seconds',first)
        self.assertEqual(first['failed_attempts'],1)
        self.assertEqual(transport.cutoff_seconds(first),first['delivery_wall_seconds'])
        self.assertEqual(transport.cutoff_seconds(second),second['successful_send_seconds'])
        self.assertEqual(transport.required_trials(transport.cutoff_seconds(
            dict(first, delivery_wall_seconds=12, successful_send_seconds=.3)),10,10),1)

    def test_preflight_is_not_cached_after_disconnect(self):
        with patch.object(transport, 'ssh', side_effect=[subprocess.CompletedProcess([],0), RuntimeError('offline')]) as ssh:
            self.assertTrue(core.ssh_preflight('user@fake'))
            self.assertFalse(core.ssh_preflight('user@fake'))
            self.assertEqual(ssh.call_count, 2)

    def test_keepalive_and_deadline_settings_and_input_validation(self):
        ssh, scp = transport.bases('user@fake', 2222)
        for item in ['ServerAliveInterval=15', 'ServerAliveCountMax=3', 'ConnectTimeout=15', 'StrictHostKeyChecking=yes', 'BatchMode=yes']:
            self.assertIn(item, ssh); self.assertIn(item, scp)
        self.assertIn('2222', scp)
        for config in [{'ssh_max_attempts': 0}, {'ssh_transfer_timeout': float('inf')}, {'ssh_retry_delay': -1}, {'ssh_max_attempts': True}, {'ssh_connect_timeout': 1.5}]:
            with self.assertRaises(ValueError): transport.settings(config)
        with patch.object(transport, 'command') as command:
            for remote, directory in [('-bad@host','/tmp/test'),('user@fake','/tmp/../bad'),('user@fake','/tmp/test;true')]:
                with self.assertRaises(ValueError): transport.deliver([self.payload],remote,22,directory)
            command.assert_not_called()

    def test_actual_command_timeout_is_bounded_without_network(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            transport.command([sys.executable, '-c', 'import time; time.sleep(30)'], .05)

    def test_real_subprocess_delivery_with_fake_ssh_and_scp(self):
        """Exercise argv, checksums and rename with local stand-ins for OpenSSH."""
        fakebin = self.root/'bin'; fakebin.mkdir()
        (fakebin/'ssh').write_text('#!'+sys.executable+'\nimport subprocess,sys\nraise SystemExit(subprocess.call(sys.argv[-1],shell=True))\n')
        (fakebin/'scp').write_text('#!'+sys.executable+'''\nimport os,sys,shutil
from pathlib import Path
args=sys.argv[1:]; files=[]; i=0
while i<len(args)-1:
    if args[i] in ('-P','-o'): i+=2; continue
    if args[i]=='-B': i+=1; continue
    files.append(args[i]);i+=1
folder=Path(args[-1].split(':',1)[1])
for file in files: shutil.copyfile(file,folder/Path(file).name)
fault=Path(os.environ['FAULT_MARKER'])
if not fault.exists():
    fault.touch();sys.stderr.write('Connection reset by peer');sys.exit(255)
''')
        for executable in fakebin.iterdir(): executable.chmod(0o755)
        destination = self.root/'remote'
        with patch.dict(os.environ, {'PATH': str(fakebin)+os.pathsep+os.environ['PATH'], 'FAULT_MARKER': str(self.root/'fault')}):
            report = transport.deliver([self.payload,self.sidecar], 'user@fake',22,str(destination))
        self.assertEqual(report['attempts'],2)
        published = Path(report['remote_directory'])
        self.assertEqual((published/self.payload.name).read_bytes(),self.payload.read_bytes())
        self.assertEqual((published/self.sidecar.name).read_bytes(),self.sidecar.read_bytes())
        self.assertEqual(len(list(destination.glob('payload.csv_verified_*'))),1)
        self.assertEqual(len(list(destination.glob('payload.csv_unverified_*'))),1)
        self.assertFalse(any(path.name.startswith('.') for path in destination.iterdir()))

    def test_truncated_journal_is_explicitly_reported(self):
        path=self.root/'truncated.jsonl'
        path.write_text('{"status":"connected"}\n{"status":')
        report=transport.read_events(path)
        self.assertEqual(report['events'],[{'status':'connected'}])
        self.assertEqual(len(report['errors']),1)
        self.assertIn('line 2',report['errors'][0])

    def test_root_and_unified_senders_use_identical_send_logic(self):
        unified = Path(__file__).resolve().parents[1]
        root = unified.parent
        if not (root/'06_transfer_package.py').exists(): self.skipTest('Standalone ZIP has no root scripts')
        for filename, start, end in [('06_transfer_package.py','def send(', 'def parser('),
                                     ('02_transfer_benchmark.py','def real_transfer(', '# ============================================================')]:
            original = (root/filename).read_text()
            bundled = (unified/'thesis_pipeline/legacy'/filename).read_text()
            self.assertEqual(original.split(start)[1].split(end)[0], bundled.split(start)[1].split(end)[0])


if __name__ == '__main__':
    unittest.main()

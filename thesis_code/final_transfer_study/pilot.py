"""Synthetic offline rehearsal using real SCP/SFTP and rsync clients."""
import os
from pathlib import Path
import shutil
import sys
import tempfile

from study import digest, read, run_session, save, schedule


LOCAL_SERVER = """import os, sys
args = sys.argv[1:]
root = os.environ['STUDY_PILOT_REMOTE']
if not any('pilot@local' == arg or 'local' == arg for arg in args):
    sys.exit('unexpected pilot host')
if args[-1] == 'sftp':
    os.execv(os.environ['STUDY_SFTP'], ['sftp-server'])
if '--server' in args:
    if not args[-1].startswith(root+'/'):
        sys.exit('unexpected rsync pilot path')
    os.execv(os.environ['STUDY_RSYNC'], ['rsync', *args[args.index('--server'):]])
cmd = args[-1]
if cmd == 'command -v rsync && command -v sha256sum && uptime':
    print('local pilot preflight')
    sys.exit(0)
if root not in cmd:
    sys.exit('unexpected pilot command')
os.execl('/bin/sh', 'sh', '-c', cmd)
"""


def run():
    sftp = next((str(p) for p in (Path('/usr/lib/openssh/sftp-server'),
                Path('/usr/libexec/openssh/sftp-server')) if p.is_file()),shutil.which('sftp-server'))
    if not sftp:
        raise RuntimeError('The local pilot requires the OpenSSH sftp-server executable')
    with tempfile.TemporaryDirectory(prefix='transport-pilot-') as tmp:
        root = Path(tmp)
        host = root/'ssh'
        host.write_text('#!'+sys.executable+'\n'+LOCAL_SERVER)
        host.chmod(0o700)
        archive = root/'synthetic.bin'
        archive.write_bytes(os.urandom(4*1024*1024))
        side = Path(str(archive)+'.sha256')
        side.write_text(digest(archive)+'  '+archive.name+'\n')
        planned = schedule()
        selected = [s for s in planned if s['session']==1 and s['artifact']=='ae16']
        assert len(planned)==32 and all(
            sum(s['order']==1 and s['transport']=='scp' and (s['artifact'],s['condition'])==key for s in planned)==2
            for key in {(s['artifact'],s['condition']) for s in planned})
        remote = root/'receiver'
        protocol = dict(remote='pilot@local',port=22, remote_dir=str(remote),
                        ssh_settings={'ssh_retry_delay':0},schedule=selected,
                        packages={'ae16':dict(path=str(archive),bytes=archive.stat().st_size,
                                              sha256=digest(archive),sidecar_sha256=digest(side))})
        save(root/'protocol.json',protocol)
        old_path = os.environ['PATH']
        os.environ.update(STUDY_PILOT_REMOTE=str(remote),STUDY_SFTP=sftp,PATH=str(root)+':'+old_path)
        try:
            run_session(root, 1, 'local synthetic rehearsal')
            before = (root/'trials.csv').read_bytes()
            run_session(root, 1, 'repeat completed session')
            assert (root/'trials.csv').read_bytes()==before
            for spec in selected:
                r=read(root/spec['id']/'result.json')
                assert r['verified'] and r['condition_observed'], r
                assert r['attempts']==(2 if spec['condition']=='interrupted' else 1),r
                assert digest(Path(r['remote_directory'])/archive.name)==digest(archive)
            assert 'median (1 pairs)' in (root/'SUMMARY.md').read_text()
            # Exhaust a one-attempt budget. Preserve that trial as a failed
            # delivery even when reporting or running the session again.
            failed = {**selected[-1], 'id':'failed_probe', 'condition':'interrupted'}
            protocol['schedule'].append(failed)
            protocol['ssh_settings']['ssh_max_attempts']=1
            save(root/'protocol.json',protocol)
            run_session(root, 1, 'exhausted retry budget probe')
            outcome=read(root/'failed_probe/result.json')
            assert outcome['state']=='failed' and not outcome['verified'] and outcome['attempts']==1
            assert outcome['condition_observed'] and outcome['delivery_wall_seconds']>0
        finally:
            os.environ['PATH']=old_path
        print('PASS: 32 scheduled positions balanced. Both copy clients passed clean and interrupted '
              'delivery, retried once after a controlled drop, and matched the source checksum. '
              'All receiver processes were local. No clinical data used.')

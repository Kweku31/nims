"""Exercise a fresh six-phase experiment including both paired studies without a network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd


def main():
    pipeline=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='paired-pipeline-') as tmp:
        root=Path(tmp)
        local=root/'bin'; local.mkdir()
        host=local/'ssh'
        real_rsync=shutil.which('rsync')
        real_scp=shutil.which('scp')
        host.write_text('#!'+sys.executable+'''
import os,sys,subprocess
args=sys.argv[1:]
if args[-1]=='sftp':
    os.execl('/usr/lib/openssh/sftp-server','sftp-server')
if '--server' in args:
    if not args[-1].startswith(os.environ['TEST_RECEIVER']+'/'): sys.exit(97)
    os.execv(os.environ['TEST_RSYNC'],['rsync',*args[args.index('--server'):]])
cmd=args[-1]
if cmd not in ('true','command -v rsync','command -v rsync && command -v sha256sum && uptime') and os.environ['TEST_RECEIVER'] not in cmd:
    sys.exit('Unexpected command in local test: '+cmd)
os.execl('/bin/sh','sh','-c',cmd)
''')
        scp=local/'scp'
        scp.write_text('#!'+sys.executable+'''
import sys,os
args=sys.argv[1:]
if '-S' not in args:
    args=['-S',os.environ['TEST_SSH'],*args]
os.execv(os.environ['TEST_SCP'],['scp',*args])
''')
        for path in (scp,host):
            path.chmod(0o700)
        rng=np.random.default_rng(42)
        data=pd.DataFrame(rng.normal(size=(128,24)),columns=[f'v{i}' for i in range(24)])
        for i,(name,center) in enumerate(zip(['HR','O2Sat','Temp','SBP','MAP','DBP','Resp','Lactate'],[85,96,37,120,80,65,18,2])):
            data[name]=center+data.pop(f'v{i}')
        data['patient_id']=np.repeat(np.arange(32),4)
        data['time']=np.tile(np.arange(4),32)
        data['SepsisLabel']=0
        data.to_csv(root/'sample.csv',index=False)
        remote=root/'receiver'
        cfg=dict(dataset=str(root/'sample.csv'),output_dir=str(root/'run'),transfer_mode='ssh',
                 remote='pilot@local',remote_dir=str(remote),fallback_simulated=False,k=[16],
                 feature_sets=['FS_95_clinical_review'],ae_max_iter=2,ae_batch_size=32,packaging_runs=1,transfer_trials=1,
                 phase2_transfer_trials=1,ssh_transport='both',paired_transport_studies=True,ssh_retry_delay=0,
                 distance_samples=16,receiver_execution='remote',remote_python=sys.executable,
                 remote_receiver_script=str(pipeline/'receiver_reconstruct.py'))
        (root/'config.json').write_text(json.dumps(cfg))
        env={**os.environ,'PATH':str(local)+os.pathsep+os.environ['PATH'],'TEST_RECEIVER':str(remote),
             'TEST_SSH':str(host),'TEST_SCP':real_scp,'TEST_RSYNC':real_rsync,
             'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
        for name in ('THESIS_NETWORK_STATUS','THESIS_NETWORK_EVENTS','THESIS_SSH_SETTINGS'):
            env.pop(name,None)
        subprocess.run([sys.executable,str(pipeline/'run_thesis.py'),'--config',str(root/'config.json')],check=True,env=env)
        folder=Path(json.loads((root/'run/run_status.json').read_text())['results_directory'])
        meta=json.loads((folder/'run_manifest.json').read_text())
        studies=meta['transport_studies']
        for name,count in [('paired_baseline_trials.csv',40),('paired_archives_trials.csv',32),('paired_baseline_topsis.csv',6)]:
            assert len(pd.read_csv(folder/name))==count
        for key in ('adaptive_rankings','paired_rankings'):
            assert len(studies[key])==6 and {r['transport_method'] for r in studies[key]}=={'scp','rsync'}
        for key,count in [('baseline',40),('archives',32)]:
            assert sum(r['verified'] for r in studies[key])==count
            assert all(r['matched_pairs']==4 for r in studies[key])
        assert any(r['condition']=='interrupted' for r in studies['archives'])
        ranks=pd.read_csv(folder/'02_decision_rankings.csv')
        winners=ranks[ranks['rank']==1]
        assert set(winners.transport_method)=={'scp','rsync'}
        print('Fresh synthetic experiment passed all six phases, both rankings, 40 direct and 32 archive deliveries.')


if __name__=='__main__':
    main()

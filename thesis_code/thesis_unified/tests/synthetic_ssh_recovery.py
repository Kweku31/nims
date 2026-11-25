"""Execute strict-SSH adapters using local command stand-ins, never a real SSH client.

This checks control flow and evidence provenance, NOT real-network performance.
Run: python tests/synthetic_ssh_recovery.py --output-dir /tmp/new-fake-ssh-study
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--compare-transports', action='store_true')
    args = parser.parse_args()
    root = args.output_dir.resolve(); root.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    rng = np.random.default_rng(42)
    n = 64
    data = pd.DataFrame({'patient_id':np.repeat(np.arange(16),4), 'time':np.tile(np.arange(4),16),
                         'SepsisLabel':np.repeat(np.arange(16)%2,4), 'Age':np.repeat(rng.integers(25,80,16),4),
                         'ICULOS':np.tile(np.arange(1,5),16), 'HospAdmTime':np.repeat(-rng.uniform(1,20,16),4)})
    for name, center, spread in [('HR',85,10),('O2Sat',96,1),('Temp',37,.3),('SBP',120,12),
                                  ('MAP',80,7),('DBP',65,6),('Resp',18,2),('Lactate',1.5,.25),('Glucose',110,15)]:
        data[name] = rng.normal(center,spread,n)
    source=root/'synthetic.csv'; data.to_csv(source,index=False)
    fakebin=root/'local_stand_ins'; fakebin.mkdir()
    remote=root/'remote'
    (fakebin/'ssh').write_text('#!'+sys.executable+'''\nimport os,sys,subprocess
if 'rsync' in sys.argv and '--server' in sys.argv:
    argv=sys.argv[sys.argv.index('rsync'):]
    if not argv[-1].startswith(os.environ['FAKE_REMOTE_DIR']+'/'): sys.exit(97)
    os.execvp('rsync',argv)
command=sys.argv[-1]
if command not in ('true','command -v rsync') and os.environ['FAKE_REMOTE_DIR'] not in command:
    sys.stderr.write('Unexpected command in offline test');sys.exit(97)
raise SystemExit(subprocess.call(command,shell=True))
''')
    (fakebin/'scp').write_text('#!'+sys.executable+'''\nimport os,sys,shutil
from pathlib import Path
args=sys.argv[1:]; files=[]; i=0
while i<len(args)-1:
    if args[i] in ('-P','-o'): i+=2; continue
    if args[i]=='-B': i+=1; continue
    files.append(args[i]);i+=1
folder=Path(args[-1].split(':',1)[1])
if not folder.is_relative_to(Path(os.environ['FAKE_REMOTE_DIR'])): sys.exit(97)
for file in files: shutil.copyfile(file,folder/Path(file).name)
phase='phase6' if any(file.endswith('.tar') for file in files) else 'phase2'
fault=Path(os.environ['FAKE_FAULT_DIR'])/phase
if not fault.exists():
    fault.touch();sys.stderr.write('Connection reset by peer');sys.exit(255)
''')
    for executable in fakebin.iterdir(): executable.chmod(0o755)
    faults=root/'faults'; faults.mkdir()
    config={'dataset':str(source),'output_dir':str(root/'run'),'k':[2],'ae_max_iter':10,
            'feature_sets':['FS_95_clinical_review'],'transfer_mode':'ssh','remote':'offline@stand-in',
            'remote_dir':str(remote),'fallback_simulated':False,'transfer_trials':10,'packaging_runs':1,
            'distance_samples':16,'neighbor_k':[5,10],'compare_npz_codecs':False,
            'continue_independent_errors':False,'ssh_retry_delay':0}
    if args.compare_transports:
        config.update(ssh_transport='both', transfer_trials=2, phase2_transfer_trials=2,
                      receiver_execution='remote', remote_python=sys.executable,
                      remote_receiver_script=str(project/'receiver_reconstruct.py'))
    maximum=config['transfer_trials']
    config_path=root/'config.json'; config_path.write_text(json.dumps(config))
    env={k:v for k,v in os.environ.items() if not k.startswith('THESIS_NETWORK_') and k!='THESIS_SSH_SETTINGS'}
    env.update(PATH=str(fakebin)+os.pathsep+os.environ['PATH'],FAKE_REMOTE_DIR=str(remote),FAKE_FAULT_DIR=str(faults),
               OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    subprocess.run([sys.executable,str(project/'run_thesis.py'),'--config',str(config_path)],env=env,check=True)
    state=json.loads((root/'run/run_status.json').read_text())
    reports=Path(state['results_directory'])
    manifest=json.loads((reports/'run_manifest.json').read_text())
    phase2 = Path(manifest['phase_directories']['phase2'])
    baseline = pd.read_csv(phase2/'transfer_benchmark.csv')
    metadata = json.loads((phase2/'transfer_metadata.json').read_text())
    assert (baseline.transfer_runs == maximum).all()
    assert metadata['experiment_parameters']['repeat_threshold_seconds'] == 10
    assert manifest['config']['phase2_transfer_trials'] == maximum
    assert manifest['config']['transfer_trials'] == maximum
    assert manifest['config']['phase6_repeat_threshold_seconds'] == 10
    trials=pd.read_csv(reports/'04_network_trials.csv')
    evidence=pd.read_csv(reports/'01_integrated_evidence.csv')
    rankings=pd.read_csv(reports/'02_decision_rankings.csv')
    assert manifest['phase6_packages_completed']==manifest['remote_verified_packages']==10
    assert manifest['simulated_packages']==0 and not manifest['phase6_failures']
    assert trials.remote_sha256_verified.all()
    methods = {'scp','rsync'} if args.compare_transports else {'scp'}
    assert set(trials.transport_method) == methods
    assert len(trials) == 10 * maximum * len(methods)
    assert trials.groupby(['package_id','transport_method']).size().eq(maximum).all()
    if args.compare_transports:
        assert evidence.receiver_verification_location.eq('remote_ssh').all()
        assert {r['phase'] for r in manifest['transport_comparison']} == {'2','6'}
        assert {r['transport'] for r in manifest['transport_comparison']} == methods
        assert 'Verified transport measurements' in (reports/'FINAL_REPORT.md').read_text(encoding='utf-8')
    assert trials.failed_attempts.sum()==1  # Separate additional failure injected into Phase 2.
    assert (trials.delivery_wall_seconds >= trials.successful_send_seconds+trials.recovery_overhead_seconds).all()
    assert (evidence.network_mode=='ssh').all()
    assert 'recovery_overhead_seconds' in evidence
    assert len(rankings)>0 and np.isfinite(rankings.topsis_score).all()
    audit=manifest['network_recovery_audit']
    assert not audit['errors']
    assert sum(event['status']=='connection_lost' for event in audit['events'])==2
    assert (faults/'phase2').exists() and (faults/'phase6').exists()
    for directory in trials.remote_directory:
        assert Path(directory).is_dir() and '_verified_' in Path(directory).name
        assert len([p for p in Path(directory).iterdir() if p.is_file()])==2
    summary={'status':'passed','packages':10,'injected_network_failures':2,
             'methods':sorted(methods),'phase2_trials_per_artifact':maximum,'phase2_artifacts':len(baseline),
             'phase6_trials_per_package_per_method':maximum,
             'real_ssh_attempts':0,'transport':'LOCAL COMMAND STAND-INS; NOT REAL SSH EVIDENCE',
             'report_directory':str(reports)}
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()

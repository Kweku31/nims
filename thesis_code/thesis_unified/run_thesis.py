#!/usr/bin/env python3
"""Run Phases 1--6 and consolidated TOPSIS decisions with resumable checkpoints.

Usage:
  python run_thesis.py --dataset input.csv
  python run_thesis.py --dataset input.csv --remote user@host --transfer-mode auto
  python run_thesis.py --dataset input.csv --all-feature-sets
  python run_thesis.py --config config.json

Input/source columns remain in the dataset; FIDDLE and prediction models are out
of the main pipeline. The original statistical implementations live in legacy/.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
from pathlib import PurePosixPath
import shutil
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from thesis_pipeline import phase1,phase2,phase3,phase4,phase5,phase6,decision,transport_decision
from thesis_pipeline.core import (Checkpoint, atomic_json, load_json, sha256, legacy_run,
                                 as_fraction, as_percent, percentage_weights,
                                 unified_logging, log_run_id, current_log_path, utc_now,
                                 dependency_fingerprint)

from thesis_pipeline import ssh_transport

DEFAULTS = {
    **ssh_transport.DEFAULTS,
    'output_dir':'thesis_runs',
    'feature_sets':['FS_95_clinical_review'], # 'all' compares all seven plus raw
    'k':[2,4,8], 'ae_max_iter':500, 'seed':42,
    'ae_tol':1e-4, 'ae_patience':20,
    'ae_backend':'cpu', 'ae_batch_size':256, 'ae_cpu_threads':0, 'ae_progress_interval':10,
    'patient_coverage_min':.75, 'missingness_thresholds':[.80,.90,.95],
    'correlation_threshold':.95, 'phase1_correlation_threshold':None,
    'correlation_action':'flag', 'min_correlation_observations':200,
    'min_correlation_patients':30,
    'minimum_feature_retention_pct':None,
    'minimum_measurement_retention_pct':None,
    'maximum_new_violation_pct':None,
    'violation_sensitivity':['0%', '0.1%', '0.5%', '1%', '5%'],
    'topsis_weights':None, 'paired_transport_studies':False,
    'clinically_protected':['Lactate'], 'distance_samples':200,'neighbor_k':[5,10],
    'ssh_transport':'scp', 'transfer_mode':'auto', 'fallback_simulated':True,
    'receiver_execution':'local', 'remote_receiver_script':None,
    'remote_python':'python3', 'remote_reconstruction_timeout':900,
    'remote':None,'remote_dir':'/tmp/thesis_transfer/phase6', 'ssh_port':22,
    'transfer_trials':10, 'phase6_repeat_threshold_seconds':10.0,'packaging_runs':3,'bandwidth_mbps':100,
    'phase2_transfer_trials':10, 'phase2_repeat_threshold_seconds':10.0,
    'compare_npz_codecs':False, 'strict_dependencies':True, 'model_reuse_count':1,
    'delivery_scenarios':['fresh_data', 'existing_payload'],
    'continue_independent_errors':True,
}


def arguments():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawTextHelpFormatter)
    ssh_transport.add_arguments(p)
    p.add_argument('--dataset',help='Input combined clinical CSV (overrides config)')
    p.add_argument('--config',help='Optional JSON with experiment options')
    p.add_argument('--output-dir', help='Project-wide root directory')
    p.add_argument('--log-file', help='Single append-only live log (default: OUTPUT_DIR/pipeline.log)')
    p.add_argument('--remote',help='SSH account user@host; only key-based authentication')
    p.add_argument('--remote-dir',help='University server destination')
    p.add_argument('--transfer-mode',choices=['auto','ssh','simulated'],
                   help='ssh: strict, no fallback; auto: explicitly labeled simulation if unreachable')
    p.add_argument('--ssh-port',type=int,help='SSH port for Phase 2 and Phase 6, default 22')
    p.add_argument('--receiver-execution', choices=['local','remote'],
                   help='Where Phase 6 unpack/reconstruction runs (default local); remote requires SSH')
    p.add_argument('--remote-receiver-script',
                   help='Absolute path on SSH server to receiver_reconstruct.py')
    p.add_argument('--remote-python', help='Python executable on university server (default python3)')
    p.add_argument('--remote-reconstruction-timeout', type=int,
                   help='Server reconstruction SSH command timeout in seconds (default 900)')
    p.add_argument('--transfer-trials',type=int,help='Phase 6 maximum benchmark trials per package, default 10; separate from failure retries')
    p.add_argument('--phase6-repeat-threshold-seconds',type=float,
                   help='Phase 6 first-transfer cutoff in seconds, default 10')
    p.add_argument('--phase2-transfer-trials',type=int,help='Phase 2 maximum trials per artifact, default 10')
    p.add_argument('--phase2-repeat-threshold-seconds',type=float,
                   help='Continue Phase 2 trials only if first transfer <= this many seconds, default 10')
    p.add_argument('--packaging-runs',type=int,help='Packaging benchmark repetitions, default 3')
    p.add_argument('--model-reuse-count',type=int,
                   help='Amortize unsupervised training over this many deliveries, default 1')
    p.add_argument('--paired-transport-studies',action='store_true',help='Run four paired baseline and archive blocks with a controlled interruption on AE-16')
    p.add_argument('--delivery-scenarios', nargs='+', choices=decision.DELIVERY_SCENARIOS,
                   help='Delivery timing scenarios to compare (default: both)')
    p.add_argument('--bandwidth-mbps',type=float,
                   help='Idealized simulation bandwidth; never claimed as measured')
    p.add_argument('--all-feature-sets',action='store_true',help='Run Phase 4-6 on all Phase 3 variants')
    p.add_argument('--missingness-thresholds', nargs='+', metavar='PCT',
                   help='Hourly missingness cutoffs, e.g. 80 90 95, 80%% 90%% 95%%, or .8 .9 .95')
    p.add_argument('--patient-coverage-min', metavar='PCT',
                   help='Patient-coverage safeguard, e.g. 75, 75%%, or .75')
    p.add_argument('--correlation-threshold', metavar='PCT',
                   help='Absolute Pearson correlation cutoff, e.g. 95 or .95 (Phases 1 and 3)')
    p.add_argument('--phase1-correlation-threshold', metavar='PCT',
                   help='Override Pearson threshold for descriptive Phase 1 only')
    p.add_argument('--correlation-action', choices=['flag','drop'],
                   help='Phase 3: flag highly correlated variables (default), or explicitly drop')
    p.add_argument('--min-correlation-observations', type=int, metavar='N',
                   help='Phase 3: minimum paired observations for a correlation')
    p.add_argument('--min-correlation-patients', type=int, metavar='N',
                   help='Phase 3: minimum paired patients for a correlation')
    p.add_argument('--clinically-protected', nargs='+', metavar='COLUMN',
                   help='Protect specified clinical variables during feature selection')
    p.add_argument('--feature-sets', nargs='+', metavar='VARIANT',
                   help='Which Phase 3 variants enter later phases; use all for every variant')
    p.add_argument('--minimum-feature-retention-pct', metavar='PCT',
                   help='Optional loss-tolerant decision gate: minimum retained clinical predictors')
    p.add_argument('--minimum-measurement-retention-pct', metavar='PCT',
                   help='Optional loss-tolerant decision gate: minimum retained observed cells')
    p.add_argument('--maximum-new-violation-pct', metavar='PCT',
                   help='Optional loss-tolerant decision gate: maximum new clinical-range violation rate')
    p.add_argument('--violation-sensitivity', nargs='+', metavar='PCT',
                   help='Explore multiple study-defined maximum new-violation cutoffs in the final report')
    p.add_argument('--topsis-weights', nargs=7, metavar='W',
                   help='Seven TOPSIS weights in CRITERIA order (percent or fraction); total 100%%. Default: equal weights')
    p.add_argument('--k',nargs='+',type=int)
    p.add_argument('--ae-max-iter',type=int)
    p.add_argument('--ae-backend',choices=['cpu','gpu'])
    p.add_argument('--ae-batch-size',type=int)
    p.add_argument('--ae-cpu-threads',type=int)
    p.add_argument('--ae-progress-interval',type=int)
    p.add_argument('--ae-tol',type=float,help='AE training-loss tolerance, default 0.0001')
    p.add_argument('--ae-patience',type=int,help='AE no-improvement patience, default 20 epochs')
    p.add_argument('--compare-npz-codecs',action='store_true')
    p.add_argument('--allow-missing-codecs',action='store_true',help='For local smoke tests, not final evaluation')
    p.add_argument('--resume-run-id',help='Require the SAME existing checkpoint run ID; refuse changed code/config/data')
    p.add_argument('--replay-phase6',action='store_true',help='On an existing checkpoint, remeasure ONLY Phase 6 on SSH receiver and regenerate TOPSIS')
    p.add_argument('--force',nargs='*',default=[],help='Recompute phases, e.g. --force phase4 phase5; or all')
    p.add_argument('--dry-run',action='store_true')
    return p.parse_args()


def normalize_options(args):
    opts={**DEFAULTS}
    if args.config:
        loaded=load_json(Path(args.config).expanduser().resolve())
        unknown=set(loaded)-set(DEFAULTS)-{'dataset'}
        if unknown: raise ValueError(f'Unknown config options: {sorted(unknown)}')
        opts.update(loaded)
    for key in ssh_transport.DEFAULTS:
        value = getattr(args, key, None)
        if value is not None: opts[key] = value
    ssh_transport.settings(opts)
    if args.dataset: opts['dataset']=args.dataset
    if args.output_dir: opts['output_dir']=args.output_dir
    if args.remote: opts['remote']=args.remote
    if args.remote_dir: opts['remote_dir']=args.remote_dir
    if args.ssh_transport: opts['ssh_transport'] = args.ssh_transport
    ssh_transport.methods(opts['ssh_transport'])
    if opts['ssh_transport'] != 'scp' and (args.transfer_mode or opts['transfer_mode']) != 'ssh':
        raise ValueError('Selecting rsync or both requires strict SSH')
    if args.transfer_mode: opts['transfer_mode']=args.transfer_mode
    for name in ('receiver_execution','remote_receiver_script', 'remote_python',
                 'remote_reconstruction_timeout'):
        val = getattr(args, name)
        if val is not None: opts[name] = val
    if args.delivery_scenarios: opts['delivery_scenarios']=args.delivery_scenarios
    for option in ('ssh_port','transfer_trials','packaging_runs','model_reuse_count','bandwidth_mbps',
                   'phase2_transfer_trials','phase2_repeat_threshold_seconds','phase6_repeat_threshold_seconds'):
        value=getattr(args,option)
        if value is not None: opts[option]=value
    if args.all_feature_sets: opts['feature_sets']='all'
    if args.feature_sets: opts['feature_sets'] = ('all' if args.feature_sets==['all'] else args.feature_sets)
    if args.missingness_thresholds is not None: opts['missingness_thresholds']=args.missingness_thresholds
    if args.patient_coverage_min is not None: opts['patient_coverage_min']=args.patient_coverage_min
    if args.correlation_threshold is not None: opts['correlation_threshold']=args.correlation_threshold
    if args.phase1_correlation_threshold is not None: opts['phase1_correlation_threshold']=args.phase1_correlation_threshold
    if args.correlation_action is not None: opts['correlation_action']=args.correlation_action
    if args.min_correlation_observations is not None: opts['min_correlation_observations']=args.min_correlation_observations
    if args.min_correlation_patients is not None: opts['min_correlation_patients']=args.min_correlation_patients
    if args.clinically_protected is not None: opts['clinically_protected']=args.clinically_protected
    for attr in ('minimum_feature_retention_pct', 'minimum_measurement_retention_pct',
                 'maximum_new_violation_pct', 'topsis_weights'):
        arg=getattr(args,attr)
        if arg is not None: opts[attr]=arg
    if args.paired_transport_studies: opts['paired_transport_studies']=True
    if args.k: opts['k']=args.k
    if args.ae_max_iter: opts['ae_max_iter']=args.ae_max_iter
    for key in ('ae_backend','ae_batch_size','ae_cpu_threads','ae_progress_interval'):
        value = getattr(args, key, None)
        if value is not None: opts[key] = value
    if args.ae_tol is not None: opts['ae_tol']=args.ae_tol
    if args.ae_patience is not None: opts['ae_patience']=args.ae_patience
    if args.violation_sensitivity is not None: opts['violation_sensitivity']=args.violation_sensitivity
    if args.compare_npz_codecs: opts['compare_npz_codecs']=True
    if args.allow_missing_codecs: opts['strict_dependencies']=False
    # Percentage inputs are normalized at one boundary and stored as fractions
    # for the legacy feature-selection engine; decision eligibility uses percent.
    opts['patient_coverage_min']=as_fraction(opts['patient_coverage_min'],name='patient_coverage_min')
    opts['correlation_threshold']=as_fraction(opts['correlation_threshold'],
                                               name='correlation_threshold',allow_zero=False)
    if opts['phase1_correlation_threshold'] is not None:
        opts['phase1_correlation_threshold']=as_fraction(
            opts['phase1_correlation_threshold'],name='phase1_correlation_threshold',allow_zero=False)
    else:
        opts['phase1_correlation_threshold']=opts['correlation_threshold']
    thresholds=opts['missingness_thresholds']
    if not isinstance(thresholds,(list,tuple)) or not thresholds:
        raise ValueError('missingness_thresholds must contain at least one percentage')
    opts['missingness_thresholds']=[as_fraction(x,name='missingness_thresholds') for x in thresholds]
    rounded=[round(100*x) for x in opts['missingness_thresholds']]
    if len(set(rounded)) != len(rounded):
        raise ValueError('Missingness thresholds must have distinct whole-percent Phase 3 labels')
    if opts['correlation_action'] not in ('flag','drop'):
        raise ValueError('correlation_action must be flag or drop')
    if int(opts['min_correlation_observations'])<3 or int(opts['min_correlation_patients'])<1:
        raise ValueError('Minimum paired observations >=3 and patients >=1 are required')
    for key in ('minimum_feature_retention_pct','minimum_measurement_retention_pct',
                'maximum_new_violation_pct'):
        if opts[key] is not None:
            opts[key]=as_percent(opts[key],name=key)
    if opts['topsis_weights'] is not None:
        opts['topsis_weights']=percentage_weights(opts['topsis_weights'],name='topsis_weights')
    vals=opts.get('violation_sensitivity') or []
    opts['violation_sensitivity']=[as_percent(v,name='violation_sensitivity') for v in vals]
    if len(set(opts['violation_sensitivity'])) != len(opts['violation_sensitivity']):
        raise ValueError('violation_sensitivity cutoffs must be distinct')
    if opts['feature_sets'] != 'all' and (not isinstance(opts['feature_sets'],list)
                                              or not opts['feature_sets']):
        raise ValueError('feature_sets must be a nonempty list or "all"')
    if not isinstance(opts['clinically_protected'],list) or not all(
        isinstance(v,str) and v.strip() for v in opts['clinically_protected']):
        raise ValueError('clinically_protected must be a list of nonempty column names')
    if not opts.get('dataset'): raise ValueError('Provide --dataset or dataset in config')
    src=Path(opts['dataset']).expanduser().resolve()
    if not src.is_file() or src.suffix.lower()!='.csv':
        raise ValueError('Expected existing source .csv: '+str(src))
    opts['dataset']=str(src)
    opts['output_dir']=str(Path(opts['output_dir']).expanduser().resolve())
    if opts['receiver_execution'] not in ('local','remote'):
        raise ValueError('receiver_execution must be local or remote')
    if opts['receiver_execution'] == 'remote':
        if opts['transfer_mode'] != 'ssh':
            raise ValueError('Remote reconstruction requires --transfer-mode ssh (no simulation)')
        script = opts['remote_receiver_script']
        if not isinstance(script, str) or not script.startswith('/') or not re.fullmatch(r'/[A-Za-z0-9_./-]+',script):
            raise ValueError('Remote receiver script must be a safe absolute server-side path')
        executable = opts['remote_python']
        if not isinstance(executable, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', executable):
            raise ValueError('Invalid remote Python executable')
        timeout = opts['remote_reconstruction_timeout']
        if isinstance(timeout,bool) or not isinstance(timeout,int) or not 1 <= timeout <= 86400:
            raise ValueError('remote_reconstruction_timeout must be an integer 1..86400')
    if opts['transfer_mode']=='ssh' and not opts['remote']:
        raise ValueError('SSH requested but --remote missing')
    if not isinstance(opts['k'],list) or not opts['k'] or any(int(x)<1 for x in opts['k']):
        raise ValueError('k must be a nonempty positive integer list')
    if not (math.isfinite(float(opts['bandwidth_mbps'])) and 0 < float(opts['bandwidth_mbps'])):
        raise ValueError('bandwidth_mbps must be finite and positive')
    if type(opts.get('paired_transport_studies')) is not bool:
        raise ValueError('paired_transport_studies must be a boolean')
    if opts.get('paired_transport_studies') and (opts['transfer_mode']!='ssh' or opts['ssh_transport']!='both' or 16 not in opts['k'] or opts.get('ssh_max_attempts',3)<2):
        raise ValueError('Paired studies require strict SSH, both transports, k=16 and at least two attempts')
    if opts['transfer_mode'] not in ('auto', 'ssh', 'simulated'):
        raise ValueError('transfer_mode must be auto, ssh or simulated')
    if not isinstance(opts['fallback_simulated'], bool):
        raise ValueError('fallback_simulated must be a Boolean')
    delivery = opts['delivery_scenarios']
    if (not isinstance(delivery, list) or not delivery or
            any(s not in decision.DELIVERY_SCENARIOS for s in delivery) or len(set(delivery)) != len(delivery)):
        raise ValueError('delivery_scenarios must be a nonempty unique list of fresh_data / existing_payload')
    if not (1 <= int(opts['ssh_port']) <= 65535):
        raise ValueError('SSH port must be 1..65535')
    if int(opts['transfer_trials']) < 1 or int(opts['packaging_runs']) < 1:
        raise ValueError('Transfer trials and packaging runs must be positive')
    if type(opts['phase2_transfer_trials']) is not int or opts['phase2_transfer_trials'] < 1:
        raise ValueError('phase2_transfer_trials must be a positive integer')
    if opts['ae_backend'] not in ('cpu','gpu'):
        raise ValueError('ae_backend must be cpu or gpu')
    for key, minimum in [('ae_batch_size',1),('ae_cpu_threads',0),('ae_progress_interval',1)]:
        if type(opts[key]) is not int or opts[key] < minimum:
            raise ValueError(f'{key} must be an integer >= {minimum}')
    if type(opts['ae_patience']) is not int or opts['ae_patience'] < 1:
        raise ValueError('ae_patience must be a positive integer')
    if (isinstance(opts['ae_tol'], bool) or not isinstance(opts['ae_tol'], (int,float))
            or not math.isfinite(opts['ae_tol']) or opts['ae_tol'] <= 0):
        raise ValueError('ae_tol must be finite and positive')
    threshold = opts['phase2_repeat_threshold_seconds']
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or threshold <= 0):
        raise ValueError('phase2_repeat_threshold_seconds must be finite and positive')
    if int(opts.get('model_reuse_count',1))<1:
        raise ValueError('model_reuse_count must be at least 1')
    ssh_transport.required_trials(0, opts['transfer_trials'], opts['phase6_repeat_threshold_seconds'])
    return opts,src


def transport_summary(phase, artifact, frame):
    if 'transport_method' not in frame:
        return []
    records = []
    for method, trials in frame.groupby('transport_method'):
        if trials.empty or not trials.remote_sha256_verified.eq(True).all():
            continue
        records.append(dict(phase=phase, artifact=artifact, transport=method, trials=len(trials),
                            mean_send_seconds=float(trials.successful_send_seconds.mean()),
                            mean_wall_seconds=float(trials.delivery_wall_seconds.mean()),
                            failed_attempts=int(trials.failed_attempts.sum())))
    return records


def force_for(stage: str, forced: list[str]):
    return 'all' in forced or stage in forced or stage.split('_',1)[0] in forced


def selected_inputs(src, phase3_result, requested):
    result={'original':str(src)}
    selected=phase3_result['selected']
    if requested=='all':
        variants=list(selected)
    else:
        variants=requested
    for name in variants:
        if name not in selected:
            raise ValueError(f'Unknown Phase 3 variant {name}. Available: {list(selected)}')
        result[name]=selected[name]
    return result


def generate_results(ctx, src: Path, opts: dict, staged: dict, phase4_results: dict,
                     phase5_result: dict, packages: list, failures: list):
    folder=ctx.results
    utility=Path(phase5_result['run'])/'phase5_utility_summary.csv'
    baseline=Path(staged['phase2']['run'])/'transfer_benchmark.csv'
    evidence=decision.join_evidence(list(transport_decision.transport_views(packages)),utility,baseline,int(opts.get('model_reuse_count',1)),
                                    opts.get('delivery_scenarios', decision.DELIVERY_SCENARIOS))
    if not evidence.empty:
        evidence.to_csv(folder/'01_integrated_evidence.csv',index=False)
    else:
        pd.DataFrame(columns=['method','dataset','status']).to_csv(folder/'01_integrated_evidence.csv',index=False)
    assessed,ranking,notes=decision.decision_tables(evidence, opts)
    if not assessed.empty:
        assessed.to_csv(folder/'01_integrated_evidence.csv',index=False)
    ranking.to_csv(folder/'02_decision_rankings.csv',index=False)
    # Phase level descriptive summaries: 1/2/3 with provenance, no pretend combined data.
    p1=pd.read_csv(Path(staged['phase1']['run'])/'dataset_summary.csv')
    p2=pd.read_csv(baseline)
    p3=pd.read_csv(Path(staged['phase3']['run'])/'threshold_comparison.csv')
    summaries=[]
    for _,r in p1.iterrows():
        for key,unit in [('input_file_bytes','bytes'),('n_rows','count'),('n_columns','count'),
                         ('profiling_time_seconds','s'),('highly_correlated_pairs','count')]:
            summaries.append({'phase':'1','configuration':'source','metric':key,'value':r.get(key),'unit':unit})
    cp=Path(staged['phase1']['run'])/'column_profile.csv'
    if cp.exists():
        vars=pd.read_csv(cp)
        if 'n_missing' in vars and len(vars) and float(p1.iloc[0]['n_rows'])>0:
            nrows=float(p1.iloc[0]['n_rows'])
            ncols=len(vars)
            missing_pct=vars['n_missing'].sum()/(nrows*ncols)*100
            summaries.append({'phase':'1','configuration':'source','metric':'overall_cell_missingness_pct',
                              'value':missing_pct,'unit':'%'})
    for _,r in p2.iterrows():
        for key,unit in [('file_bytes','bytes'),('packaging_mean_seconds','s'),('transfer_mean_seconds','s'),('verification_mean_seconds','s')]:
            summaries.append({'phase':'2','configuration':r['format'],'metric':key,'value':r.get(key),'unit':unit,'mode':r.get('transfer_mode')})
    for _,r in p3.iterrows():
        for key,unit in [('predictors_retained','count'),('predictor_reduction_pct','%'),
                         ('size_reduction_pct_vs_source','%'),('fit_selection_seconds','s')]:
            summaries.append({'phase':'3','configuration':r['experiment'],'metric':key,'value':r.get(key),'unit':unit})
    if 'phase2_topsis' in staged:
        ranking_path=Path(staged['phase2_topsis']['run'])/'topsis_ranking.csv'
        if ranking_path.exists():
            for _,r in pd.read_csv(ranking_path).iterrows():
                summaries.append({'phase':'2 TOPSIS','configuration':r.get('format'),
                                  'transport_method':r.get('transport_method'), 'metric':'topsis_score','value':r.get('topsis_score'),'unit':'score'})
    pd.DataFrame(summaries).to_csv(folder/'03_phase_overview.csv',index=False)
    # Compact trial table; keep detailed logs under _work only.
    trails = []
    comparisons = []
    phase2_trials = Path(staged['phase2']['run'])/'transport_comparison.csv'
    if phase2_trials.exists():
        for fmt, group in pd.read_csv(phase2_trials).groupby('format'):
            comparisons.extend(transport_summary('2', fmt, group))
    for pkg in packages:
        files = [pkg['trials_file'], *pkg.get('transport_comparison_files', [])]
        frames = []
        for file in files:
            if Path(file).exists():
                frame = pd.read_csv(file)
                frames.append(frame)
                for trial in frame.to_dict('records'):
                    trails.append({'dataset':pkg['dataset'], 'method':pkg['method'], 'k':pkg['k'],
                                   'codec':pkg['codec'], 'network_mode':pkg['network_mode'], **trial})
        if frames and pkg['network_mode'] == 'ssh':
            comparisons.extend(transport_summary('6', pkg['package_id'], pd.concat(frames)))
    trial_table = pd.DataFrame(trails) if trails else pd.DataFrame(columns=[
        'dataset', 'method', 'k', 'codec', 'network_mode', 'trial', 'remote_sha256_verified'])
    trial_table.to_csv(folder/'04_network_trials.csv',index=False)
    if failures:
        notes += [f'{len(failures)} Phase 6 configurations failed. Missing packages are not ranked.']
    if opts.get('_phase6_replay', {}).get('phase6_packages_reused', 0):
        reused = opts['_phase6_replay']['phase6_packages_reused']
        notes.append(f'{reused} Phase 6 packages reused previously measured, verified SSH/receiver '
                     'results. Their original times were retained, not remeasured; compare '
                     'measurement dates and server load when interpreting TOPSIS rankings.')
    if opts.get('_phase6_replay') and staged['phase2'].get('mode') != 'ssh':
        notes += ['Phase 6 replay used measured server-side SSH delivery and reconstruction, '
                  'but Phase 2 was reused unchanged and was not necessarily an SSH benchmark. '
                  'Do not describe Phase 2 simulated timing as empirical SSH.']
    n_codecs=3 if opts.get('compare_npz_codecs') else 1
    expected=len(phase4_results)*(3+2*len(opts['k'])*n_codecs)
    if len(packages)!=expected:
        notes.append(f'Only {len(packages)} of {expected} expected configurations completed; decision remains incomplete.')
    remote_verified = (decision.remote_verification_mask(pd.DataFrame(packages), int(opts.get('transfer_trials', 1)),
                                                         opts.get('phase6_repeat_threshold_seconds'))
                       if packages else pd.Series(dtype=bool))
    if not remote_verified.all() or not packages:
        notes.append('At least one configuration lacks actual verified SSH performance; results are PROVISIONAL for deployment.')
    if len(packages)==0:
        notes += ['No packages built; do not publish a final strategy recommendation.']
    report=decision.render_report(assessed,ranking,notes,ctx.state,opts)
    studies=transport_decision.followup_results(staged,p2)
    for kind,key in [('baseline','phase2_paired'),('archives','phase6_paired')]:
        if key in staged:
            shutil.copyfile(Path(staged[key]['run'])/'trials.csv',folder/('paired_'+kind+'_trials.csv'))
    if 'paired_rankings' in studies:
        pd.DataFrame(studies['paired_rankings'],columns=transport_decision.COLUMNS).to_csv(folder/'paired_baseline_topsis.csv',index=False)
    if 'phase2_topsis' in staged:
        studies['adaptive_rankings']=pd.read_csv(Path(staged['phase2_topsis']['run'])/'topsis_ranking.csv').to_dict('records')
    for key in ('adaptive_rankings','paired_rankings'):
        if studies.get(key):
            report+='\n## Phase 2 TOPSIS ('+key.split('_')[0]+')\n\n'
            for row in studies[key]:
                report+=f"- {row.get('transport_method','historical')} · rank {row['rank']} · {row['format']} · {row['topsis_score']:.4f}\n"
    for key in ('baseline','archives'):
        if key in studies:
            report+='\n## Paired deliveries ('+key+')\n\n'
            for row in studies[key]:
                delta=row['median_wall_difference_seconds']
                measured=f"{delta:+.2f} s" if delta is not None else 'unavailable'
                report+=f"- {row['artifact']} ({row['condition']}): {row['verified']}/{row['scheduled']} verified; {row['matched_pairs']} matched pairs; median rsync minus SCP {measured}.\n"
    if comparisons:
        report += '\n## Verified transport measurements\n\n'
        report += 'Wall time covers setup, failed attempts, backoff, successful upload, verification and publication. Receiver reconstruction is timed separately. In both mode each transport has a separate ranking. The identical verified archive shares the measured receiver reconstruction cost.\n\n'
        report += '| Phase | Artifact | Transport | Trials | Mean successful send (s) | Mean wall (s) | Failed attempts |\n|---|---|---|---:|---:|---:|---:|\n'
        for item in comparisons:
            report += ('| {phase} | {artifact} | {transport} | {trials} | {mean_send_seconds:.4f} | '
                       '{mean_wall_seconds:.4f} | {failed_attempts} |\n').format(**item)
    (folder/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
    meta={'transport_studies':studies,'transport_comparison':comparisons,'version':'7','run_id':ctx.key,'unified_log_file':current_log_path(),
          'input':str(src),'input_sha256':sha256(src),
          'config':opts,'phase_directories':{k:v.get('run') for k,v in staged.items()},
          'phase4_runs':{k:v.get('run') for k,v in phase4_results.items()},
          'phase6_packages_completed':len(packages),'phase6_packages_expected':expected,
          'completion_status': (('fully_verified_ssh_remote_receiver' if opts.get('receiver_execution')=='remote'
                                else 'fully_verified_ssh') if len(packages)==expected and not failures and
                                len(packages)>0 and remote_verified.all() and
                                all(x.get('checksum_passed') is True and x.get('receiver_recovery_passed') is True
                                    for x in packages) else 'provisional_incomplete_or_simulated'),
          'phase6_failures':failures,
          'network_modes':sorted({x['network_mode'] for x in packages}),
          'remote_verified_packages':int(remote_verified.sum()),
          'simulated_packages':sum(x['network_mode'] != 'ssh' for x in packages),
          'receiver_recovery_location':sorted({x.get('receiver_verification_location','local') for x in packages}),
          'network_fallback_notes':[x['network_note'] for x in packages if x['network_note']],
          'network_timing_policy':'New measurements charge the successful send and recovery overhead. Wall time also includes successful setup, verification and publication.',
          'network_recovery_audit': ssh_transport.read_events(Path(opts['output_dir'])/'network_events.jsonl'),
          'decision_criteria':decision.CRITERIA,
          'decision_weights':decision.get_weight_profiles(opts),
          'primary_weight_profile':decision.primary_weight_profile(opts),
          'decision_percentage_policy':{k:opts.get(k) for k in
            ('minimum_feature_retention_pct','minimum_measurement_retention_pct','maximum_new_violation_pct')},
          'phase2_network_mode':staged['phase2'].get('mode'),
          'interpretation':'Observational development-run decision support; not generalizable clinical acceptability.'}
    requested_studies=[studies[key] for key in ('baseline','archives') if key in studies]
    if requested_studies:
        complete=all(rows and all(r['matched_pairs']==4 and r['verified']==r['scheduled'] for r in rows)
                     for rows in requested_studies)
        meta['paired_study_status']='complete' if complete else 'partial'
        if not complete:
            meta['completion_status']='provisional_incomplete_paired_study'
    if opts.get('_phase6_replay'):
        meta['phase6_replay'] = opts['_phase6_replay']
        # Source options are unchanged; transfer-only options are an addendum.
        meta['original_config'] = ctx.state.get('config')
    atomic_json(folder/'run_manifest.json',meta)
    return {'run':str(folder),'artifacts':[str(folder/x) for x in
             ['01_integrated_evidence.csv','02_decision_rankings.csv',
              '03_phase_overview.csv','04_network_trials.csv','FINAL_REPORT.md','run_manifest.json']]}


def publish_current_reports(run_results: Path, output_root: Path) -> Path:
    """Publish all six reports atomically in a new timestamped directory.

    Every successful invocation, including checkpoint resumes, gets a separate
    snapshot. The temporary directory's unique suffix prevents timestamp
    collisions, and prior published snapshots are never overwritten.
    """
    names = ('FINAL_REPORT.md', '01_integrated_evidence.csv',
             '02_decision_rankings.csv', '03_phase_overview.csv',
             '04_network_trials.csv', 'run_manifest.json')
    optional={'baseline':'paired_baseline_trials.csv','archives':'paired_archives_trials.csv',
              'paired_rankings':'paired_baseline_topsis.csv'}
    if any((run_results/name).exists() for name in optional.values()):
        studies=load_json(run_results/'run_manifest.json').get('transport_studies',{})
        names+=tuple(name for key,name in optional.items() if key in studies)
    reports_root = output_root / 'results'
    reports_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        source = run_results / name
        if not source.is_file():
            raise FileNotFoundError(f'Missing consolidated report: {source}')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    staging = Path(tempfile.mkdtemp(dir=reports_root, prefix=f'.{stamp}_'))
    destination = reports_root / staging.name[1:]
    try:
        for name in names:
            shutil.copyfile(run_results / name, staging / name)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def startup_paths(args) -> tuple[Path, Path]:
    """Resolve operational paths before input validation and Phase 1.

    This lets tail -F attach as soon as the process starts, even if the
    source is large, a prerequisite is missing, or the run later fails.
    Relative paths are based on the shell's current working directory.
    """
    output = args.output_dir
    if not output and args.config:
        # Defer validation errors to normalize_options inside the log. A broken
        # config still produces a default-location diagnostic log.
        try:
            config = load_json(Path(args.config).expanduser().resolve())
            output = config.get('output_dir') if isinstance(config, dict) else None
        except (OSError, ValueError, TypeError):
            pass
    base = Path(output or DEFAULTS['output_dir']).expanduser().resolve()
    log = (Path(args.log_file).expanduser().resolve()
           if args.log_file else base / 'pipeline.log')
    return base, log


def main():
    args = arguments()
    if args.resume_run_id is not None and (args.dry_run or args.force):
        raise ValueError('--resume-run-id cannot be used with --dry-run or --force')
    if args.replay_phase6 and not args.resume_run_id:
        raise ValueError('--replay-phase6 requires --resume-run-id for an existing experiment')
    if args.dry_run:
        opts, src = normalize_options(args)
        print(json.dumps({'input':str(src),'configuration':opts,'sequence':[
            'phase1','phase2','phase3','phase4 for each selected feature set',
            'phase5','phase6 each combination with SSH/ideal simulation fallback',
            'decision']},indent=2))
        return

    base, log_path = startup_paths(args)
    # The combined log is opened immediately, even before validating inputs or
    # computing the potentially expensive dataset SHA-256/run checkpoint.
    with unified_logging(log_path):
        (base / 'results').mkdir(parents=True, exist_ok=True)
        status_path = base / 'run_status.json'
        status = {
            'status': 'initializing',
            'started_utc': utc_now(),
            'run_id': None,
            'log_file': str(log_path),
            'results_directory': str(base / 'results'),
            'note': 'All six reports are published together in a new timestamped results directory after all phases finish.'
        }
        atomic_json(status_path, status)
        print(f'LOG FILE: {log_path}', flush=True)
        try:
            opts, src = normalize_options(args)
            if Path(opts['output_dir']) != base:
                raise RuntimeError('Resolved output directory changed during initialization')
            if opts['ae_backend'] == 'gpu' and not args.replay_phase6:
                from thesis_pipeline.legacy.ae_runtime import cuda_module, device_details
                print('GPU preflight: '+json.dumps(device_details(cuda_module())), flush=True)
            ssh_transport.configure(opts, base)
            ssh_transport.event('idle', operation='Experiment starting')
            if opts['transfer_mode'] == 'ssh' or (opts['transfer_mode'] == 'auto' and not opts['fallback_simulated']):
                from thesis_pipeline.core import ssh_preflight
                if not ssh_preflight(opts['remote'],int(opts['ssh_port'])):
                    raise RuntimeError('SSH is required, but remote preflight failed. Check user, host key, key auth and port; no simulation will be substituted.')
            checkpoint_opts = opts
            if args.replay_phase6:
                prior_file = base / 'runs' / args.resume_run_id / 'checkpoint.json'
                if not prior_file.is_file():
                    raise RuntimeError('Phase 6 replay requires a previous checkpoint: '+str(prior_file))
                prior = load_json(prior_file)
                checkpoint_opts = prior['config']
                permitted = {'ssh_transport', 'transfer_mode', 'fallback_simulated', 'remote', 'remote_dir',
                             'ssh_port', 'ssh_max_attempts', 'ssh_transfer_timeout',
                             'ssh_retry_delay', 'ssh_connect_timeout', 'ssh_command_timeout',
                             'ssh_keepalive_interval', 'ssh_keepalive_count',
                             'receiver_execution', 'remote_receiver_script', 'remote_python',
                             'remote_reconstruction_timeout'}
                disallowed = [k for k in set(opts) | set(checkpoint_opts)
                              if opts.get(k) != checkpoint_opts.get(k) and k not in permitted]
                if disallowed:
                    raise RuntimeError('Phase 6 replay cannot change original research options: '
                                       + ', '.join(sorted(disallowed)))
                if opts['transfer_mode'] != 'ssh' or opts['receiver_execution'] != 'remote':
                    raise RuntimeError('Phase 6 replay requires Strict SSH and remote receiver reconstruction')
                if opts.get('fallback_simulated'):
                    opts = {**opts, 'fallback_simulated':False}
            if opts['ssh_transport'] in ('rsync','both'):
                if not shutil.which('rsync'):
                    raise RuntimeError('rsync is required on the sending host')
                ssh_transport.ssh(opts['remote'], int(opts['ssh_port']), 'command -v rsync')
            with Checkpoint(base, checkpoint_opts, src,
                            resume_run_id=None if args.replay_phase6 else args.resume_run_id,
                            phase6_replay_id=args.resume_run_id if args.replay_phase6 else None) as ctx:
                log_run_id(ctx.key)
                status.update(status='running', run_id=ctx.key,
                              checkpoint_file=str(ctx.state_file), updated_utc=utc_now())
                atomic_json(status_path, status)
                print(f'RUN {ctx.key}: {ctx.root}', flush=True)
                if args.replay_phase6:
                    execute_phase6_replay(ctx, opts, src, checkpoint_opts)
                else:
                    execute_pipeline(ctx, args, opts, src)
                latest = publish_current_reports(ctx.results, base)
                print(f'RESULTS: {latest.resolve()}', flush=True)
            status.update(status='complete', completed_utc=utc_now(),
                          results_directory=str(latest.resolve()))
            atomic_json(status_path, status)
        except BaseException as exc:
            status.update(status=('interrupted' if isinstance(exc, KeyboardInterrupt)
                                  else 'failed'),
                          error=f'{type(exc).__name__}: {exc}',
                          updated_utc=utc_now())
            atomic_json(status_path, status)
            raise



def _require_verified_stage(ctx, name, dependencies=None):
    """Never run or repair an earlier phase during a Phase 6 receiver replay."""
    from thesis_pipeline.core import validate_artifacts
    previous = ctx.state.get('stages', {}).get(name)
    if not previous or previous.get('status') != 'complete':
        raise RuntimeError(f'Phase 6 replay requires completed {name}; original stages will not run')
    if dependencies is not None and previous.get('dependencies', {}) != dependencies:
        raise RuntimeError(f'Phase 6 replay found changed dependencies for {name}')
    if not validate_artifacts(previous.get('result'), require_checksums=True):
        raise RuntimeError(f'Phase 6 replay found missing or corrupted {name} artifacts')
    print(f'SKIP {name}: verified original output; no recomputation', flush=True)
    return previous['result']


def _phase6_replay_spec(opts: dict) -> str:
    """A stable signature for every option that can affect replay measurements.

    Do not include the transient audit timestamp: otherwise no replay could be
    resumed.  This intentionally includes the receiver interpreter and SSH
    trial policy so measurements from different environments aren't mixed.
    """
    from thesis_pipeline.core import fingerprint
    return fingerprint({key: value for key, value in opts.items()
                        if key != '_phase6_replay'})


def _remote_replay_outputs_present(package: dict, trials: pd.DataFrame, opts: dict) -> bool:
    """Check saved receiver output still exists AND matches saved SHA-256 hashes.

    The command only READS from the receiver, never reruns reconstruction.
    This verification is not counted in the original delivery-time experiment.
    """
    try:
        report = package['remote_receiver_report']
        archive = Path(package['archive'])
        remote_dir = str(trials.iloc[-1]['remote_directory']).rstrip('/')
        archive_name = archive.name
        reconstructed = str(report['reconstructed_csv_path'])
        expected_csv = str(PurePosixPath(remote_dir) / 'receiver_recovery' / 'reconstructed.csv')
        if reconstructed != expected_csv:
            return False
        expected_archive_hash = sha256(archive)
        expected_csv_hash = str(report['reconstructed_csv_sha256'])
        if not re.fullmatch(r'[a-f0-9]{64}', expected_csv_hash):
            return False
        remote_archive = str(PurePosixPath(remote_dir) / archive_name)
        remote_report = str(PurePosixPath(remote_dir) / 'receiver_recovery' / 'receiver_report.json')
        ssh_base, _ = ssh_transport.bases(opts['remote'], int(opts['ssh_port']))
        command = ('test -f ' + shlex.quote(remote_report) + ' && ' +
                   shlex.join(['sha256sum', '--', remote_archive, reconstructed]))
        timeout = max(int(opts.get('ssh_command_timeout', 60)),
                      int(opts.get('remote_reconstruction_timeout', 900)))
        output = ssh_transport.command([*ssh_base, command], timeout=timeout).stdout
        lines = output.strip().splitlines()
        if len(lines) != 2:
            return False
        actual = {}
        for line in lines:
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2 or not re.fullmatch(r'[a-f0-9]{64}', parts[0]):
                return False
            actual[parts[1].lstrip('*')] = parts[0]
        return (actual.get(remote_archive) == expected_archive_hash and
                actual.get(reconstructed) == expected_csv_hash)
    except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError) as exc:
        print(f'REPLAY: could not verify saved server files: {exc}', flush=True)
        return False


def _verified_prior_phase6(ctx, stage: str, label: str, info: dict, method: str,
                           k: int | None, codec: str, opts: dict, spec: str) -> tuple[bool, bool]:
    """Return (reusable, legacy) after verifying both local and remote evidence.

    Legacy Phase 6 replay checkpoints recorded only a Phase 4 dependency.  They
    can be reused if their actual SSH measurements and recovered files verify;
    checkpoints for local-only or simulated deliveries are never reused here.
    """
    from thesis_pipeline.core import validate_artifacts
    previous = ctx.state.get('stages', {}).get(stage, {})
    if previous.get('status') != 'complete':
        return False, False
    dependencies = previous.get('dependencies', {})
    if dependencies.get('phase4') != dependency_fingerprint(info):
        return False, False
    legacy = 'phase6_replay_spec' not in dependencies
    if not legacy and dependencies['phase6_replay_spec'] != spec:
        return False, False
    result = previous.get('result', {})
    if result.get('transport_selection') != opts.get('ssh_transport', 'scp'):
        return False, False
    if not validate_artifacts(result, require_checksums=True):
        return False, False
    if not all((result.get('dataset') == label,
                result.get('method') == method, result.get('k') == k,
                result.get('codec') == codec,
                result.get('network_mode') == 'ssh',
                result.get('receiver_verification_location') == 'remote_ssh',
                result.get('remote_sha256_verified') is True,
                result.get('receiver_recovery_passed') is True,
                result.get('checksum_passed') is True,
                result.get('phase4_run_directory') == str(info['run']),
                result.get('source') == str(info['source']))):
        return False, False
    receiver = result.get('remote_receiver_report')
    if not isinstance(receiver, dict) or not all((
            receiver.get('receiver_execution_role') == 'receiver_host',
            receiver.get('receiver_recovery_passed') is True,
            receiver.get('receiver_package_sha256_verified') is True,
            receiver.get('package_id') == result.get('package_id'),
            receiver.get('method') == method,
            receiver.get('k') == k,
            receiver.get('reconstructed_csv_sha256') == result.get('remote_reconstructed_csv_sha256'))):
        return False, False
    try:
        path = Path(result['trials_file'])
        trials = pd.read_csv(path)
        count = ssh_transport.validate_trial_report(trials.to_dict('records'),
                  int(opts['transfer_trials']), float(opts['phase6_repeat_threshold_seconds']))
        if (len(trials) != result.get('remote_trials_completed') or
                count != result.get('remote_trials_requested') or
                not trials['remote'].eq(opts['remote']).all() or
                not trials['package_id'].eq(result['package_id']).all()):
            return False, False
        base = PurePosixPath(str(opts['remote_dir']))
        for remote_dir in trials['remote_directory']:
            candidate = PurePosixPath(str(remote_dir))
            if candidate == base or base not in candidate.parents:
                return False, False
        if not _remote_replay_outputs_present(result, trials, opts):
            return False, False
        return True, legacy
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(f'REPLAY: invalid saved SSH evidence for {stage}: {exc}', flush=True)
        return False, False


def execute_phase6_replay(ctx, opts, src, original_opts):
    """Reuse Phases 1–5 and verified Phase 6 packages; recalculate TOPSIS."""
    from thesis_pipeline.core import code_fingerprints
    audit = {'performed_utc':utc_now(), 'original_run_id':ctx.key,
             'original_receiver_execution':original_opts.get('receiver_execution', 'local'),
             'receiver_execution':'remote', 'transfer_mode':'ssh',
             'remote':opts['remote'], 'remote_dir':opts['remote_dir'],
             'original_code_sha256':ctx.state['code_sha256'],
             'replay_code_sha256':code_fingerprints(),
             'reason':'Explicit, independently measured Phase 6 receiver-side replay'}
    # Validate first, BEFORE touching any Phase 6 checkpoint or published report.
    staged = {name:_require_verified_stage(ctx,name) for name in ('phase1','phase2','phase3')}
    if ctx.state.get('stages', {}).get('phase2_topsis', {}).get('status') == 'complete':
        staged['phase2_topsis'] = _require_verified_stage(ctx, 'phase2_topsis',
                   {'phase2':dependency_fingerprint(staged['phase2'])})
    inputs = selected_inputs(src, staged['phase3'], original_opts['feature_sets'])
    phase4_results = {}
    for label, input_csv in inputs.items():
        phase4_results[label] = _require_verified_stage(ctx, f'phase4_{label}',
            {'source_csv':str(Path(input_csv).resolve()),
             'source_sha256':sha256(Path(input_csv)),
             'phase3':dependency_fingerprint(staged['phase3'])})
    staged['phase5'] = _require_verified_stage(ctx, 'phase5',
        {'phase4':{k:dependency_fingerprint(v) for k,v in phase4_results.items()}})
    # Prior completed packages are reusable only after recorded checksums,
    # adaptive SSH trials, receiver provenance and live server hashes agree.
    # Failed/incomplete/missing packages must be rebuilt. Original snapshots
    # remain untouched; final TOPSIS is always republished from the complete set.
    effective = {**opts, '_phase6_replay':audit, '_input_dataset':str(src)}
    replay_spec = _phase6_replay_spec(effective)
    packages = []
    failures = []
    reused = 0
    rebuilt = 0
    for label, info in phase4_results.items():
        for method, k, codec in phase6.configurations(info, effective):
            stage = f'phase6_{label}_{method}_{"n" if k is None else k}_{codec}'
            try:
                can_reuse, legacy = _verified_prior_phase6(
                    ctx, stage, label, info, method, k, codec, effective, replay_spec)
                dependencies = {'phase4':dependency_fingerprint(info),
                                'phase6_replay_spec':replay_spec}
                if can_reuse and legacy:
                    # Previous versions saved only the Phase 4 dependency. Do
                    # not rewrite their historical provenance; use the verified
                    # evidence directly and record a notice in this replay log.
                    value = ctx.state['stages'][stage]['result']
                    print(f'SKIP {stage}: verified legacy SSH package and server reconstruction', flush=True)
                else:
                    value = ctx.stage(stage,
                        lambda l=label,r=info,m=method,kk=k,c=codec:
                        phase6.package_and_benchmark(l,r,m,kk,c,ctx.work/'phase6',effective),
                        force=not can_reuse, dependencies=dependencies)
                if can_reuse:
                    reused += 1
                else:
                    rebuilt += 1
                packages.append(value)
            except Exception as exc:
                failures.append({'configuration':stage,'error':str(exc)})
                print('WARNING: phase6 replay configuration failed:',stage,exc,flush=True)
                # Real SSH must never silently fall back to simulated evidence.
                raise
    audit['phase6_packages_reused'] = reused
    audit['phase6_packages_recomputed'] = rebuilt
    ctx.stage('final_decision',
              lambda:generate_results(ctx,src,effective,staged,phase4_results,
                                      staged['phase5'],packages,failures),force=True)
    print(f'PHASE6 REPLAY COMPLETE: reused={reused}, recomputed={rebuilt}; original phases unchanged; TOPSIS republished for dashboard.',flush=True)


def execute_pipeline(ctx, args, opts, src):
    staged={}
    staged['phase1']=ctx.stage('phase1',lambda:phase1.run(src,ctx.work/'phase1',opts),
                               force=force_for('phase1',args.force))
    staged['phase2']=ctx.stage('phase2',lambda:phase2.run(src,ctx.work/'phase2',opts),
                               force=force_for('phase2',args.force))
    # TOPSIS 2: preserve previous dedicated Phase 2 ranking; optional if fewer formats.
    try:
        def p2topsis():
            d=ctx.work/'phase2_topsis'
            d.mkdir(exist_ok=True)
            table=Path(staged['phase2']['run'])/'transfer_benchmark.csv'
            trials=table.parent/'transport_comparison.csv'
            ranked=transport_decision.baseline_rankings(pd.read_csv(table),pd.read_csv(trials) if trials.exists() else None,
                    maximum=opts['phase2_transfer_trials'],threshold=opts['phase2_repeat_threshold_seconds'],audit_dir=d)
            ranked.to_csv(d/'topsis_ranking.csv',index=False)
            return {'run':str(d),'artifacts':[str(d/'topsis_ranking.csv')]}
        staged['phase2_topsis']=ctx.stage('phase2_topsis',p2topsis,
                                          force=force_for('phase2',args.force),
                                          dependencies={'phase2': dependency_fingerprint(staged['phase2'])})
    except Exception as exc:
        if opts.get('ssh_transport')=='both':
            raise
        print('WARNING: optional Phase 2 TOPSIS failed:',exc,flush=True)
    if opts.get('paired_transport_studies'):
        staged['phase2_paired']=ctx.stage('phase2_paired',
            lambda:transport_decision.run_followup('baseline',ctx.work/'paired_baseline',src,opts,phase2=staged['phase2']),
            force=force_for('phase2',args.force), dependencies={'phase2':dependency_fingerprint(staged['phase2'])})
    staged['phase3']=ctx.stage('phase3',lambda:phase3.run(src,ctx.work/'phase3',opts),
                               force=force_for('phase3',args.force))
    inputs=selected_inputs(src,staged['phase3'],opts['feature_sets'])
    rerun_p4 = force_for('phase3',args.force) or force_for('phase4',args.force)
    rerun_p5 = rerun_p4 or force_for('phase5',args.force)
    rerun_p6 = rerun_p4 or force_for('phase6',args.force)
    phase4_results={}
    for label,input_csv in inputs.items():
        phase4_results[label]=ctx.stage(f'phase4_{label}',
            lambda csv=input_csv,l=label:phase4.run(Path(csv),ctx.work/'phase4'/l,opts),
            force=rerun_p4 or force_for(f'phase4_{label}', args.force),
            dependencies={'source_csv':str(Path(input_csv).resolve()),
                                           'source_sha256':sha256(Path(input_csv)),
                                           'phase3':dependency_fingerprint(staged['phase3'])})
    staged['phase5']=ctx.stage('phase5',
        lambda:phase5.run(phase4_results,src,ctx.work/'phase5',opts),
        force=rerun_p5, dependencies={'phase4':{k:dependency_fingerprint(v) for k,v in phase4_results.items()}})
    opts_with_source={**opts,'_input_dataset':str(src)}
    packages=[]; failures=[]
    for label, info in phase4_results.items():
        for method,k,codec in phase6.configurations(info,opts):
            stage=f'phase6_{label}_{method}_{"n" if k is None else k}_{codec}'
            try:
                entry=ctx.stage(stage,lambda l=label,r=info,m=method,kk=k,c=codec:
                                phase6.package_and_benchmark(l,r,m,kk,c,ctx.work/'phase6',opts_with_source),
                                force=rerun_p6 or force_for(stage, args.force),
                                dependencies={'phase4':dependency_fingerprint(info)})
                packages.append(entry)
            except Exception as exc:
                failures.append({'configuration':stage,'error':str(exc)})
                print('WARNING: independent configuration failed:',stage,exc,flush=True)
                if opts.get('transfer_mode') == 'ssh' or not opts.get('continue_independent_errors',True):
                    raise
    if opts.get('paired_transport_studies'):
        staged['phase6_paired']=ctx.stage('phase6_paired',
            lambda:transport_decision.run_followup('archives',ctx.work/'paired_archives',src,opts,packages=packages),
            force=rerun_p6,dependencies={'packages':[dependency_fingerprint(p) for p in packages]})
    result=ctx.stage('final_decision',
                     lambda:generate_results(ctx,src,opts,staged,phase4_results,
                                             staged['phase5'],packages,failures),
                     force=True)  # Always consolidate current package evidence.
    print('\nDONE: '+str(ctx.results.resolve()))
    print('  FINAL_REPORT.md')
    print('  01_integrated_evidence.csv')
    print('  02_decision_rankings.csv')
    print('  03_phase_overview.csv')
    print('  04_network_trials.csv')
    print('  run_manifest.json')
    if failures:
        print(f'WARNING: {len(failures)} configurations failed, see run_manifest.json')


if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError) as exc:
        sys.exit('ERROR: '+str(exc))

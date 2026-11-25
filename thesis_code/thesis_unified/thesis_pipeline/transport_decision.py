"""Transport-specific TOPSIS inputs from verified transfers of the same files."""
from pathlib import Path
import numpy as np
import pandas as pd
from . import ssh_transport
from .core import sha256
from .legacy.topsis_transfer_decision import calculate_topsis, DEFAULT_FORMATS, CRITERIA

LABELS = {'Source CSV':'original_source', 'Rewritten CSV':'csv', 'gzip':'csv_gzip',
          'Parquet':'parquet', 'Zstandard':'csv_zstd'}
COLUMNS = ['transport_method','rank','format','topsis_score','distance_to_ideal_best','distance_to_ideal_worst',*CRITERIA,'trials','measurement_basis']


def baseline_rankings(benchmark, trials, *, paired=False, maximum=10, threshold=10.0, audit_dir=None):
    """Keep the original three compressed alternatives, equal weights and mean copy time."""
    data = benchmark[benchmark.format.isin(DEFAULT_FORMATS)].copy()
    if data.format.duplicated().any():
        raise ValueError('Duplicate baseline format')
    if trials is None:
        data['trials'] = data.transfer_runs
        methods = data.get('transport_method', pd.Series('scp',index=data.index)).fillna('scp')
        data['transport_method'] = methods.where(data.transfer_mode.eq('ssh'), 'simulated')
        inputs = data
    else:
        population = trials.copy()
        if paired:
            if 'transport_method' in population:
                population = population[population.transport_method.eq(population.method)].copy()
            else:
                population['transport_method'] = population.method
            population['format'] = population['format'].replace(LABELS)
        if not {'payload_sha256','remote_sha256_verified','successful_send_seconds'}.issubset(population):
            return pd.DataFrame(columns=COLUMNS)
        if population.empty:
            return pd.DataFrame(columns=COLUMNS)
        observations = []
        for fmt, group in population.groupby('format'):
            if fmt not in set(data.format):
                continue
            if paired:
                # Both methods must have delivered identical bytes on the first attempt.
                accepted = []
                for _, block in group.groupby('block'):
                    if (len(block)==2 and set(block.transport_method)=={'scp','rsync'} and
                        block.state.eq('verified').all() and block.attempts.eq(1).all() and
                        block.remote_sha256_verified.eq(True).all() and
                        block.payload_sha256.notna().all() and block.payload_sha256.nunique()==1 and
                        block.payload_sha256.eq(block.sha256).all()):
                        accepted.append(block)
                if not accepted:
                    continue
                group = pd.concat(accepted)
            if group.payload_sha256.isna().any() or group.payload_sha256.nunique()!=1:
                continue
            for method, subset in group.groupby('transport_method'):
                if method not in ('scp','rsync') or not subset.remote_sha256_verified.eq(True).all():
                    continue
                if not paired:
                    subset = subset.sort_values('trial')
                    count = ssh_transport.required_trials(ssh_transport.cutoff_seconds(subset.iloc[0]),maximum,threshold)
                    if list(subset.trial)!=list(range(1,count+1)):
                        continue
                times = pd.to_numeric(subset.successful_send_seconds, errors='coerce')
                if not np.isfinite(times).all() or times.lt(0).any():
                    continue
                observations.append(dict(format=fmt,transport_method=method,
                                         trials=len(times),transfer_mean_seconds=times.mean()))
        if not observations:
            return pd.DataFrame(columns=COLUMNS)
        static = data[['format','size_reduction_pct','packaging_mean_seconds']]
        inputs = static.merge(pd.DataFrame(observations),on='format').assign(transfer_mode='ssh',integrity_verified=True)
    results=[]
    methods=inputs.transport_method.unique()
    primary='scp' if 'scp' in methods else next(iter(methods),None)
    for method, pool in inputs.groupby('transport_method'):
        if 'integrity_verified' in pool:
            pool=pool[pool.transfer_mode.eq('simulated') | pool.integrity_verified.eq(True)]
        if len(pool)<2:
            continue
        matrices=calculate_topsis(pool,[1,1,1])
        if audit_dir is not None:
            target=Path(audit_dir)/method
            target.mkdir(parents=True,exist_ok=True)
            for name,frame in matrices.items():
                frame.to_csv(target/f'topsis_{name}.csv',index=False)
                if method==primary and name!='ranking':
                    frame.to_csv(Path(audit_dir)/f'topsis_{name}.csv',index=False)
        ranked=matrices['ranking'].merge(pool[['format','trials']],on='format')
        results.append(ranked.assign(transport_method=method,measurement_basis='paired_clean' if paired else 'adaptive'))
    return pd.concat(results)[COLUMNS] if results else pd.DataFrame(columns=COLUMNS)


def transport_views(packages):
    """Share byte-identical archive and receiver measurements, replacing the network terms."""
    for pkg in packages:
        yield pkg
        if pkg.get('network_mode')!='ssh' or pkg.get('transport_selection')!='both':
            continue
        paths=pkg.get('transport_comparison_files',[])
        if len(paths)!=1:
            raise ValueError('Missing rsync comparison evidence')
        table=pd.read_csv(paths[0])
        count=ssh_transport.validate_trial_report(table.to_dict('records'),pkg['remote_trials_maximum'],
                                                  pkg['remote_repeat_threshold_seconds'])
        if not table.transport_method.eq('rsync').all() or not table.payload_sha256.eq(sha256(Path(pkg['archive']))).all():
            raise ValueError('Mismatched rsync trial evidence')
        times=table.transfer_seconds
        check=table.remote_sha256_verification_seconds.mean()
        if not all(np.isfinite(table[c]).all() and table[c].ge(0).all() for c in
                   ['transfer_seconds','remote_sha256_verification_seconds','delivery_wall_seconds','recovery_overhead_seconds']):
            raise ValueError('Invalid rsync timing evidence')
        common=pkg['end_to_end_seconds']-pkg['transfer_seconds']-pkg['remote_verify_seconds']
        yield {**pkg,'transport_method':'rsync','trials_file':str(paths[0]),'transport_comparison_files':[],
               'network_time_basis':'observed_RSYNC','receiver_time_basis':'shared measurement on identical verified archive',
               'transfer_seconds':times.mean(),'remote_verify_seconds':check,
               'transfer_median_seconds_MEASURED':times.median(),'transfer_std_seconds_MEASURED':times.std() if count>1 else None,
               'transfer_p95_seconds_MEASURED':times.quantile(.95),'scp_median_seconds_MEASURED':None,
               'scp_std_seconds_MEASURED':None,'scp_p95_seconds_MEASURED':None,
               'recovery_overhead_seconds':table.recovery_overhead_seconds.mean(),
               'delivery_wall_seconds':table.delivery_wall_seconds.mean(),'failed_attempts':int(table.failed_attempts.sum()),
               'remote_first_transfer_seconds':ssh_transport.cutoff_seconds(table.iloc[0]),
               'remote_trials_completed':count,'remote_trials_requested':count,'remote_sha256_verified':True,
               'end_to_end_seconds':common+times.mean()+check,
               'end_to_end_with_network_recovery_seconds':common+table.delivery_wall_seconds.mean()}


def run_followup(kind, base, src, opts, *, phase2=None, packages=None):
    """Persist a fresh protocol for new inputs, resume pending trials of that protocol."""
    import sys
    from .core import atomic_json, fingerprint, subprocess_run
    study_dir=Path(__file__).resolve().parents[2]/'final_transfer_study'
    request=dict(kind=kind, remote=opts['remote'],port=opts['ssh_port'],
                 ssh_settings={k:opts.get(k,v) for k,v in ssh_transport.DEFAULTS.items()})
    if kind=='baseline':
        artifacts=Path(phase2['run'])/'artifacts'
        names=['original_'+Path(src).name,'dataset.csv','dataset.csv.gz','dataset.parquet','dataset.csv.zst']
        paths={label:artifacts/name for label,name in zip(LABELS,names)}
    else:
        selected={('parquet',None):'parquet',('gzip',None):'gzip',('autoencoder',16):'ae16'}
        paths={selected[(p['method'],p['k'])]:Path(p['archive']) for p in packages if
               p['dataset']=='original' and p['codec']=='native' and (p['method'],p['k']) in selected}
        if set(paths)!=set(selected.values()):
            raise ValueError('Paired archive study requires the original gzip, Parquet and feasible AE-16 packages')
    files={}
    for label,path in paths.items():
        files[label]=dict(path=str(path.resolve()),sha256=sha256(path),bytes=path.stat().st_size)
        if kind=='archives':
            files[label]['sidecar_sha256']=sha256(Path(str(path)+'.sha256'))
    request['files' if kind=='baseline' else 'packages']=files
    request['code_sha256']={name:sha256(study_dir/name) for name in
                            ('study.py','baseline.py','copy_shell.py','new_experiment.py')}
    folder=base/fingerprint(request)
    folder.mkdir(parents=True,exist_ok=True)
    request['remote_dir']=opts['remote_dir'].rstrip('/')+'/paired_'+kind+'/'+folder.name
    atomic_json(folder/'request.json',request)
    subprocess_run([sys.executable,str(study_dir/'new_experiment.py'),str(folder/'request.json')],folder/'followup.log')
    return dict(run=str(folder),artifacts=[str(folder/name) for name in
                ('protocol.json','trials.csv','SUMMARY.md','request.json')])


def study_summary(frame, kind):
    """Describe verified matched pairs and retain counts for all scheduled deliveries."""
    rows=frame.copy()
    if kind=='baseline':
        rows=rows.rename(columns={'method':'transport','block':'session','format':'artifact'})
        rows['condition']='clean'
        rows['condition_observed']=(rows.state.eq('verified') & rows.get('attempts',pd.Series(0,index=rows.index)).eq(1) &
                                    rows.get('remote_sha256_verified',pd.Series(False,index=rows.index)).eq(True) &
                                    rows.get('payload_sha256',pd.Series('',index=rows.index)).eq(rows.sha256))
    if 'condition_observed' not in rows:
        rows['condition_observed']=False
    results=[]
    for (artifact,condition),group in rows.groupby(['artifact','condition'],sort=False):
        diffs=[]
        for _,block in group.groupby('session'):
            ok=block[block.verified.eq(True)] if 'verified' in block else block[block.state.eq('verified')]
            ok=ok[ok.condition_observed.eq(True)]
            if len(ok)!=2 or set(ok.transport)!={'scp','rsync'} or ok.sha256.nunique()!=1:
                continue
            times=ok.set_index('transport').delivery_wall_seconds
            diffs.append(times['rsync']-times['scp'])
        verified=group.verified.eq(True) if 'verified' in group else group.state.eq('verified')
        results.append(dict(artifact=artifact,condition=condition,scheduled=len(group),verified=int(verified.sum()),
                            matched_pairs=len(diffs),median_wall_difference_seconds=float(np.median(diffs)) if diffs else None))
    return results


def followup_results(staged, baseline):
    data={}
    for kind,key in [('baseline','phase2_paired'),('archives','phase6_paired')]:
        if key not in staged:
            continue
        trials=pd.read_csv(Path(staged[key]['run'])/'trials.csv')
        data[kind]=study_summary(trials,kind)
        if kind=='baseline':
            data['paired_rankings']=baseline_rankings(baseline,trials,paired=True).to_dict('records')
    return data

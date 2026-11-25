"""Evidence table and transparent multi-criteria decisions.

TOPSIS is a decision aid, not a clinical validity threshold. Missing evidence
is never silently replaced by estimates. Simulated and real networking are
ranked in separate pools.
"""
from __future__ import annotations
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import ssh_transport
from .core import load_json, atomic_json, percentage_weights

# Explicit weight profiles; users can alter them and rerun. Benefit/cost tags
# are separate from clinical acceptability, which is not inferred from a score.
CRITERIA = {
    'total_transmitted_bytes': 'cost',
    'effective_delivery_seconds': 'cost',
    'R2_retained_variation_observed_STANDARDIZED': 'benefit',
    'knn5_overlap_original_vs_reconstruction': 'benefit',
    'clinical_predictor_retention_pct': 'benefit',
    'original_observed_measurement_retention_pct': 'benefit',
    'clinical_screen_new_violation_pct': 'cost',
}
WEIGHTS = {
    'equal': [1 / len(CRITERIA)] * len(CRITERIA),
    'balanced': [0.22,0.18,0.22,0.12,0.10,0.06,0.10],
    'transfer_priority':[0.35,0.30,0.12,0.07,0.07,0.04,0.05],
    'utility_priority':[0.10,0.10,0.30,0.18,0.12,0.07,0.13],
}
assert all(abs(sum(x)-1)<.001 for x in WEIGHTS.values())

DELIVERY_SCENARIOS = ('fresh_data', 'existing_payload')
RANKING_COLUMNS = [
    'dataset', 'network_mode', 'transport_method', 'delivery_scenario', 'scenario', 'weight_profile',
    'method', 'k', 'codec', 'package_id', 'candidate_count', 'decision_evidence_status',
    'remote_sha256_verified', 'topsis_score', 'end_to_end_seconds', *CRITERIA, 'rank',
]


def valid_criteria(df: pd.DataFrame) -> pd.Series:
    """R² has no lower bound; percentages, overlaps and costs have physical bounds."""
    x = df[list(CRITERIA)].apply(pd.to_numeric, errors='coerce')
    valid = pd.Series(np.isfinite(x.to_numpy()).all(axis=1), index=df.index)
    for col in ('total_transmitted_bytes', 'effective_delivery_seconds'):
        valid &= x[col].ge(0)
    valid &= x['R2_retained_variation_observed_STANDARDIZED'].le(1)
    valid &= x['knn5_overlap_original_vs_reconstruction'].between(0, 1)
    for col in ('clinical_predictor_retention_pct',
                'original_observed_measurement_retention_pct', 'clinical_screen_new_violation_pct'):
        valid &= x[col].between(0, 100)
    return valid


def remote_verification_mask(df: pd.DataFrame, expected_trials: int = 1,
                             repeat_threshold_seconds=None) -> pd.Series:
    completed = pd.to_numeric(df.get('remote_trials_completed', pd.Series(0, index=df.index)), errors='coerce')
    requested = pd.to_numeric(df.get('remote_trials_requested', pd.Series(expected_trials, index=df.index)), errors='coerce')
    verified = df.get('remote_sha256_verified', pd.Series(False, index=df.index)).eq(True)
    base = (df['network_mode'].eq('ssh') & verified & np.isfinite(completed) &
            np.isfinite(requested) & requested.ge(1) & requested.mod(1).eq(0) &
            completed.ge(requested) & completed.mod(1).eq(0))
    policy = df.get('remote_trial_policy', pd.Series('', index=df.index)).fillna('')
    # Legacy fixed-count evidence still needs the configured count; it cannot use
    # an adaptive one-trial exception without explicit, consistent timing evidence.
    counts_ok = policy.eq('') & completed.ge(expected_trials)
    if repeat_threshold_seconds is not None:
        counts_ok[:] = False
    for index, row in df.loc[policy.eq(ssh_transport.TRIAL_POLICY)].iterrows():
        try:
            maximum = float(row['remote_trials_maximum'])
            threshold = float(row['remote_repeat_threshold_seconds'])
            if (not math.isfinite(maximum) or maximum != int(maximum)
                    or maximum < expected_trials
                    or (repeat_threshold_seconds is not None and
                        (maximum != expected_trials or threshold != repeat_threshold_seconds))):
                continue
            required = ssh_transport.required_trials(row['remote_first_transfer_seconds'], int(maximum), threshold)
            counts_ok.loc[index] = requested.loc[index] == required and completed.loc[index] == required
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return base & counts_ok


def get_weight_profiles(config: dict | None = None) -> dict[str,list[float]]:
    """Equal default plus named comparison profiles and optional custom weights."""
    profiles={k:list(v) for k,v in WEIGHTS.items()}
    if config and config.get('topsis_weights') is not None:
        custom=percentage_weights(config['topsis_weights'], name='topsis_weights')
        # An identical weight vector is not an independent sensitivity scenario.
        if not any(all(abs(a-b) < 1e-10 for a,b in zip(custom, v))
                   for v in profiles.values()):
            profiles['custom']=custom
    return profiles


def primary_weight_profile(config: dict | None = None) -> str:
    if not config or config.get('topsis_weights') is None:
        return 'equal'
    selected = percentage_weights(config['topsis_weights'], name='topsis_weights')
    return next(name for name, weights in get_weight_profiles(config).items()
                if all(abs(a-b) < 1e-10 for a,b in zip(selected, weights)))


def _safe_float(v):
    try:
        z=float(v)
        return z if np.isfinite(z) else float('nan')
    except (ValueError, TypeError):
        return float('nan')


def join_evidence(packages: list[dict], utility_path: Path, phase2_path: Path | None,
                  model_reuse_count: int = 1, delivery_scenarios=DELIVERY_SCENARIOS) -> pd.DataFrame:
    if model_reuse_count < 1 or not math.isfinite(model_reuse_count):
        raise ValueError('model_reuse_count must be finite and at least 1')
    if not delivery_scenarios or any(s not in DELIVERY_SCENARIOS for s in delivery_scenarios):
        raise ValueError('Unknown or empty delivery_scenarios')
    if not packages:
        return pd.DataFrame(columns=['dataset', 'network_mode', 'delivery_scenario', *CRITERIA])
    utility = pd.read_csv(utility_path)
    if phase2_path and phase2_path.exists():
        phase2 = pd.read_csv(phase2_path)
    else:
        phase2 = pd.DataFrame()
    rows = []
    for pkg in packages:
        row = {k:v for k,v in pkg.items() if k!='artifacts'}
        # Never confuse a checksum verified on the laptop with a university-side check.
        row['remote_sha256_verified'] = pkg.get('remote_sha256_verified', False) is True
        row['remote_trials_completed'] = pkg.get('remote_trials_completed', 0)
        method = ('lossless_' if pkg['lossless'] else '')+pkg['method']
        hit = utility[(utility['phase4_run_directory'].astype(str).map(lambda s: str(Path(s).resolve()))
                       == str(Path(pkg['phase4_run_directory']).resolve())) &
                      (utility['method'] == method)]
        if pkg['k'] is not None:
            hit = hit[pd.to_numeric(hit['k'],errors='coerce') == pkg['k']]
        if len(hit)==1:
            for key,val in hit.iloc[0].to_dict().items():
                if key not in row:
                    row[key] = val
        else:
            row['utility_match_problem'] = f'Expected 1 row; found {len(hit)}'
        # Phase 5 field was labelled ambiguously: it describes *local* recovery.
        row['receiver_local_checksum_verified'] = bool(row.pop('receiver_checksum_verified', False))
        if pkg['lossless']:
            row['clinical_screen_new_violation_pct'] = 0.0
            row['model_fit_seconds'] = 0.0
            row['initial_encode_seconds'] = 0.0
            row['initial_payload_creation_seconds'] = float('nan')
            baseline_file = Path(pkg['phase4_run_directory'])/'phase4_lossless_baselines.csv'
            if baseline_file.exists():
                baselines = pd.read_csv(baseline_file)
                match = baselines[baselines['method'].eq(pkg['method'])]
                if len(match) == 1:
                    row['initial_payload_creation_seconds'] = _safe_float(match.iloc[0].get('packaging_seconds'))
        else:
            # Phase 4 new violation rate is computed on its audited clinical cells.
            p4_file = Path(pkg['phase4_run_directory'])/'phase4_comparison.csv'
            if p4_file.exists():
                p4 = pd.read_csv(p4_file)
                p4hit=p4[(p4['method']==pkg['method']) & (pd.to_numeric(p4['k'],errors='coerce')==pkg['k'])]
                if len(p4hit)==1:
                    p4r=p4hit.iloc[0]
                    row['clinical_screen_new_violation_pct']=p4r.get('clinical_screen_new_violation_pct')
                    row['model_fit_seconds']=p4r.get('fit_seconds')
                    row['initial_encode_seconds']=p4r.get('encode_seconds')
                    row['initial_payload_creation_seconds']=p4r.get('packaging_seconds')
        if not pkg['lossless'] and 'model_fit_seconds' not in row:
            row['model_fit_seconds'] = float('nan')
        if pkg['lossless']:
            row['model_fit_seconds'] = 0.0
        fit=_safe_float(row.get('model_fit_seconds'))
        encode=_safe_float(row.get('initial_encode_seconds'))
        create=_safe_float(row.get('initial_payload_creation_seconds'))
        # Invalid components cannot cancel each other and produce a valid total.
        preparation = (fit/model_reuse_count + encode + create
                       if all(math.isfinite(v) and v >= 0 for v in (fit, encode, create))
                       else float('nan'))
        row['model_reuse_count_assumed'] = model_reuse_count
        row['effective_delivery_time_basis'] = (
            'measured_server_reconstruction_plus_'+str(pkg.get('transport_method') or 'scp').upper()
            if pkg.get('receiver_verification_location') == 'remote_ssh'
            else 'measured_local_reconstruction_plus_'+str(pkg.get('transport_method') or 'scp').upper()
            if pkg.get('network_mode') == 'ssh'
            else 'measured_local_plus_idealized_network')
        if not phase2.empty:
            fmt={'gzip':'csv_gzip','zstd':'csv_zstd','parquet':'parquet'}.get(pkg['method'])
            if fmt and fmt in phase2['format'].values:
                old=phase2[phase2['format']==fmt].iloc[0]
                row['phase2_baseline_mean_ssh_seconds']=old['transfer_mean_seconds'] if (old.get('transport_method','scp') == (pkg.get('transport_method') or 'scp')) else None
                row['phase2_baseline_transfer_mode']=old['transfer_mode']
        for delivery in delivery_scenarios:
            current = dict(row, delivery_scenario=delivery)
            current['initial_preparation_seconds_charged'] = preparation if delivery == 'fresh_data' else 0.0
            base_time = _safe_float(pkg['end_to_end_seconds'])
            current['effective_delivery_seconds'] = (base_time + current['initial_preparation_seconds_charged']
                                                       if base_time >= 0 else float('nan'))
            rows.append(current)
    return pd.DataFrame(rows)


def topsis(df: pd.DataFrame, weights: list[float]) -> pd.Series:
    if df.empty:
        return pd.Series(index=df.index, dtype=float)
    if not valid_criteria(df).all():
        raise ValueError('TOPSIS criteria must be finite and within their defined ranges')
    cols = list(CRITERIA)
    x = df[cols].astype(float).to_numpy(copy=True)
    w = np.array(weights, dtype=float, copy=True)
    if w.shape != (len(cols),) or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError('TOPSIS requires one finite nonnegative weight per criterion and a positive total')
    # Scale before squaring to keep finite, large costs and negative R² stable.
    scale = np.max(np.abs(x), axis=0)
    x /= np.where(scale == 0, 1, scale)
    norms = np.linalg.norm(x, axis=0)
    # Criterion constant or zero: it cannot distinguish candidates.
    inactive = (np.nanmax(x,axis=0)-np.nanmin(x,axis=0) < 1e-14) | (norms==0)
    w[inactive]=0
    if w.sum()==0:
        return pd.Series(np.full(len(df),.5),index=df.index)
    w/=w.sum()
    v=(x/np.where(norms==0,1,norms))*w
    maximize=np.array([CRITERIA[c]=='benefit' for c in cols])
    best=np.where(maximize, v.max(axis=0),v.min(axis=0))
    worst=np.where(maximize,v.min(axis=0),v.max(axis=0))
    d_best=np.linalg.norm(v-best,axis=1)
    d_worst=np.linalg.norm(v-worst,axis=1)
    return pd.Series(np.divide(d_worst,d_best+d_worst,out=np.full_like(d_worst,.5),
                               where=(d_best+d_worst)>0),index=df.index)


def decision_tables(evidence: pd.DataFrame, config: dict | None = None) -> tuple[pd.DataFrame,pd.DataFrame,list[str]]:
    if evidence.empty:
        return evidence.copy(),pd.DataFrame(columns=RANKING_COLUMNS),['No verified Phase 6 configurations available.']
    df=evidence.copy()
    method=df.get('transport_method',pd.Series(index=df.index,dtype=object))
    df['transport_method']=method.fillna('scp').where(df.network_mode.eq('ssh'),'simulated')
    config=config or {}
    if 'delivery_scenario' not in df:
        df['delivery_scenario'] = 'existing_payload'
    for c in CRITERIA:
        if c not in df:
            df[c]=np.nan
        df[c]=pd.to_numeric(df[c],errors='coerce')
    # Accept older locally verified archives but never infer remote validation.
    if 'remote_sha256_verified' not in df: df['remote_sha256_verified'] = False
    if 'remote_trials_completed' not in df: df['remote_trials_completed'] = 0
    for col in ('checksum_passed', 'receiver_recovery_passed'):
        if col not in df: df[col] = False
    df['check_passed'] = df['checksum_passed'].eq(True) & df['receiver_recovery_passed'].eq(True)
    df['criteria_available'] = valid_criteria(df)
    remote_ok = remote_verification_mask(df, int(config.get('transfer_trials', 1)),
                                         config.get('phase6_repeat_threshold_seconds'))
    df['measured_completely'] = df['criteria_available'] & df['check_passed'] & remote_ok
    # Simulation may be compared provisionally, but is NEVER fully measured.
    df['eligible'] = (df['check_passed'] & df['criteria_available'] &
                      (df['network_mode'].eq('simulated_ideal') | remote_ok) &
                      df['delivery_scenario'].isin(DELIVERY_SCENARIOS))
    df['empirical_ssh_eligible'] = df['eligible'] & df['measured_completely']
    # For phase3 selected datasets, 'lossless' means lossless *for selected columns*.
    df['loss_tolerant_eligible']=df['eligible'].copy()
    config=config or {}
    limits={
        'minimum_feature_retention_pct':('clinical_predictor_retention_pct','min'),
        'minimum_measurement_retention_pct':('original_observed_measurement_retention_pct','min'),
        'maximum_new_violation_pct':('clinical_screen_new_violation_pct','max'),
    }
    for name,(col,direction) in limits.items():
        cutoff=config.get(name)
        if cutoff is not None:
            valid=(df[col]>=cutoff) if direction=='min' else (df[col]<=cutoff)
            df['loss_tolerant_eligible'] &= valid
    df['full_fidelity_eligible'] = (df['eligible'] & df['lossless'].eq(True) &
                                   (df['clinical_predictor_retention_pct'].astype(float) >= 100-1e-9))
    rows=[]
    notes=[]
    rejected_ssh = df['network_mode'].eq('ssh') & ~remote_ok
    if rejected_ssh.any():
        notes.append('Unverified or incomplete SSH results are excluded from every ranking and recommendation.')
    if not df['criteria_available'].all():
        notes.append('Missing, non-finite or out-of-range criteria are excluded; negative finite R² remains valid.')
    if config.get('topsis_weights') is not None and 'custom' not in get_weight_profiles(config):
        notes.append('Custom TOPSIS weights duplicate a predefined profile; duplicate scenario omitted.')
    if config.get('maximum_new_violation_pct') == 100:
        notes.append('A 100% maximum new-violation cutoff does not meaningfully constrain clinical plausibility.')
    # Never compare empirical SSH timings with ideal payload-only simulations.
    for (dataset, delivery), ddf in df.groupby(['dataset', 'delivery_scenario'],dropna=False):
        modes=sorted(ddf['network_mode'].astype(str).unique())
        if len(modes)>1:
            notes.append(f'{dataset}: mixed SSH and simulated network modes. Rankings separated by mode; no global winner.')
        for (mode,transport), mdf in ddf.groupby(['network_mode','transport_method']):
            for scenario in ['full_fidelity','selected_columns_exact','loss_tolerant']:
                if scenario=='full_fidelity':
                    pool=mdf[mdf['full_fidelity_eligible']].copy()
                elif scenario=='selected_columns_exact':
                    pool=mdf[mdf['eligible'] & mdf['lossless'].eq(True)].copy()
                else:
                    pool=mdf[mdf['loss_tolerant_eligible']].copy()
                if pool.empty:
                    notes.append(f'{dataset}/{mode}/{scenario}: no fully verified comparable candidates')
                    continue
                if len(pool)==1:
                    notes.append(f'{dataset}/{mode}/{scenario}: only one eligible candidate; TOPSIS score is non-comparative')
                for profile,weight in get_weight_profiles(config).items():
                    vals=topsis(pool,weight)
                    for idx,score in vals.items():
                        p=pool.loc[idx]
                        rows.append({'dataset':dataset,'network_mode':mode,'transport_method':transport,'scenario':scenario,
                                     'delivery_scenario':delivery,
                                     'weight_profile':profile,'method':p['method'],'k':p['k'],
                                     'codec':p['codec'], 'package_id':p['package_id'],
                                     'candidate_count':len(pool),
                                     'decision_evidence_status':('empirical_ssh' if mode=='ssh' else 'simulated_provisional'),
                                     'remote_sha256_verified':bool(p.get('remote_sha256_verified',False)),
                                     'topsis_score':float(score),'total_transmitted_bytes':p['total_transmitted_bytes'],
                                     'end_to_end_seconds':p.get('end_to_end_seconds',float('nan')),
                                     'effective_delivery_seconds':p['effective_delivery_seconds'],
                                     'R2_retained_variation_observed_STANDARDIZED':p['R2_retained_variation_observed_STANDARDIZED'],
                                     'knn5_overlap_original_vs_reconstruction':p['knn5_overlap_original_vs_reconstruction'],
                                     'clinical_predictor_retention_pct':p['clinical_predictor_retention_pct'],
                                     'original_observed_measurement_retention_pct':p['original_observed_measurement_retention_pct'],
                                     'clinical_screen_new_violation_pct':p['clinical_screen_new_violation_pct']})
    decision=pd.DataFrame(rows, columns=RANKING_COLUMNS)
    if len(decision):
        decision=decision.sort_values(['dataset','network_mode','transport_method','delivery_scenario','scenario','weight_profile','topsis_score'],
                                       ascending=[True,True,True,True,True,True,False], kind='stable')
        decision['rank']=decision.groupby(['dataset','network_mode','transport_method','delivery_scenario','scenario','weight_profile']).cumcount()+1
    return df,decision,notes


def violation_sensitivity_table(evidence: pd.DataFrame, config: dict) -> list[str]:
    """Study-defined clinical-screen cutoff sensitivity, not clinical authorization."""
    values = config.get('violation_sensitivity', [0, 0.1, 0.5, 1, 5])
    if not values or evidence.empty:
        return []
    lines = ['', '## Exploratory plausibility-threshold sensitivity', '',
             'The cutoffs are **study-defined sensitivity values**, not clinical safety standards.',
             'A new violation means that the reconstruction fell outside a study-screening bound while the original observation was inside it. '
             'The denominator is originally observed cells covered by the seven screened vital-sign variables.', '',
             f'| Dataset | Network | Delivery | Maximum new violations | Eligible configurations | Winner ({primary_weight_profile(config)} weights) |',
             '|---|---|---|---:|---:|---|']
    for cutoff in values:
        trial_config = {**config, 'maximum_new_violation_pct': float(cutoff)}
        evaluated, ranked, _ = decision_tables(evidence, trial_config)
        for (dataset, mode, transport, delivery), pool in evaluated.groupby(['dataset', 'network_mode', 'transport_method','delivery_scenario']):
            eligible = int(pool['loss_tolerant_eligible'].sum())
            subset = ranked[(ranked['dataset'] == dataset) &
                            (ranked['network_mode'] == mode) & (ranked['transport_method']==transport) &
                            (ranked['delivery_scenario'] == delivery) &
                            (ranked['scenario'] == 'loss_tolerant') &
                            (ranked['weight_profile'] == primary_weight_profile(config)) &
                            (ranked['rank'] == 1)]
            if subset.empty:
                winner = 'none'
            else:
                r = subset.iloc[0]
                winner = str(r['method']) + ('' if pd.isna(r['k']) else f" k={int(r['k'])}")
            lines.append(f'| {dataset} | {mode} ({transport}) | {delivery} | {float(cutoff):g}% | {eligible} | {winner} |')
    return lines

def render_report(evidence: pd.DataFrame, ranking: pd.DataFrame, notes: list[str], state: dict, config: dict | None = None) -> str:
    config=config or {}
    profiles=get_weight_profiles(config)
    primary=primary_weight_profile(config)
    lines=['# Integrated thesis experiment — decision report','',
           f"**Run ID:** `{state['run_id']}`  ",f"**Input SHA-256:** `{state['input_sha256']}`",'',
           '## Scope and integrity','',
           'Findings apply to the supplied dataset and experimental configurations, not to all clinical data.',
           'Lossless formats preserve the variables actually sent; variables removed by Phase 3 are not recovered.',
           'No predictive-task clinical utility was evaluated. Range checks are screening rules, not clinical acceptance.',
           '','## Measurement policy','',
           '- `ssh`: measured file transfer over SSH with remote SHA-256 verification; `simulated_ideal`: ideal payload/bandwidth calculation, **not a real measured delivery time**.',
           '- Receiver recovery location is recorded per candidate in `receiver_verification_location`: `remote_ssh` means unpacking/reconstruction measured on the university server; `local` means local recovery only.',
           '- The `end_to_end_seconds` proxy includes Phase 6 package creation, local integrity check, network transfer, remote integrity if SSH, and receiver unpack/recovery; remote receiver persistence time is included for `remote_ssh`. It is a sum of separately timed stages, not one synchronized wall-clock measurement.',
           '- New transfer measurements charge successful sends plus failed-attempt and backoff overhead; older checkpoints retain their recorded timing basis. `delivery_wall_seconds` includes all attempts and successful setup/publication. These rankings do not measure outage resilience. See the network trial table and recovery audit in the manifest.',
           '- `existing_payload` uses that proxy for an already-created Phase 4 payload, with no initial model fit, encoding or compression charge.',
           '- `fresh_data` additionally charges Phase 4 fitting divided by model reuse count, encoding, and initial NPZ serialization/compression (or lossless compression/serialization). Encoding and payload creation are charged on every delivery. Phase 6 wrapper/recompression costs remain in both scenarios. These scoped proxies exclude CSV loading, preprocessing and feature selection.',
           '- Missing initial preparation measurements exclude a candidate from fresh-data rankings; they are never replaced with zero. Rankings and sensitivity comparisons are separated by delivery scenario.',
           '- TOPSIS is a sensitivity-based decision aid. No TOPSIS score establishes clinical acceptability.',
           '- PCA intrinsic explained variance is not substituted for AE reconstruction-based R².',
           '- Across different feature sets, reconstruction metrics have different denominators. Retention penalties are included but cannot make them clinically equivalent.',
           '', '## Ranking rules','',
           'For each dataset, network mode and delivery scenario, evaluate three fidelity scenarios: full reference fidelity, exact selected-columns delivery, and loss-tolerant representation delivery. Unverified SSH results are excluded from all pools. Profiles: equal, balanced, transfer-priority, utility-priority and optional custom.']
    lines += ['', '## Autoencoder execution', '',
              f"Requested backend: **{config.get('ae_backend', 'cpu')}**; batch size: **{config.get('ae_batch_size', 256)}**; maximum epochs: **{config.get('ae_max_iter', 500)}**.",
              'CPU uses the original sklearn optimizer. Optional GPU execution uses the same network and Adam equations with float32 arithmetic. Batch-size and precision changes can affect convergence and reconstruction; compare observed R² and clinical-screen results, not runtime alone.',
              'Phase 4 comparison tables record actual device, backend, precision, epochs and loss. GPU fitting includes training data upload and weight download; GPU availability preflight is outside the delivery proxy. Encoding and receiver reconstruction remain CPU operations; the remote receiver may run on a separate host.']
    gates={k:config.get(k) for k in
           ('minimum_feature_retention_pct','minimum_measurement_retention_pct','maximum_new_violation_pct')
           if config.get(k) is not None}
    if gates:
        lines+=['', '## Study-defined loss-tolerant eligibility safeguards', '',
                'These are experimental policy thresholds, not medically validated error limits.',
                'Configured percentages: '+', '.join(f'{k}={v:g}%' for k,v in gates.items())+'.']
    lines+=['', '## Selected TOPSIS weights', '', f'Primary weight profile: **{primary}**.', '',
            '| Criterion | Direction | Selected weight |', '|---|---|---:|']
    lines += [f'| {criterion} | {direction} | {weight*100:.6f}% |'
              for (criterion,direction),weight in zip(CRITERIA.items(),profiles[primary])]
    lines += ['', 'Other weight profiles are sensitivity comparisons. Constant criteria within a ranking pool are inactive; remaining active weights are renormalized.']
    if evidence.empty:
        lines+=['','**No final Phase 6 evidence available.**']
    else:
        lines+=['','## Verification summary','',f"- Packages benchmarked: {evidence['package_id'].nunique()}.",
                f"- Package/delivery-scenario evidence rows: {len(evidence)}.",
                f"- Local sender SHA-256 and configured receiver recovery passed: {int(evidence['check_passed'].sum())}/{len(evidence)}.",
                f"- Empirically measured and remotely verified: {int(evidence['measured_completely'].sum())}/{len(evidence)}.",
                f"- Complete comparison criteria (includes simulations): {int(evidence['criteria_available'].sum())}/{len(evidence)}."]
    if len(ranking):
        lines+=['','## TOPSIS first-place results','',
                '| Dataset | Network | Delivery | Scenario | Weight profile | Method | k | Codec | Score |',
                '|---|---|---|---|---|---|---:|---|---:|']
        for _,r in ranking[ranking['rank']==1].iterrows():
            lines.append(f"| {r['dataset']} | {r['network_mode']} ({r['transport_method']}) | {r['delivery_scenario']} | {r['scenario']} | {r['weight_profile']} | {r['method']} | {'' if pd.isna(r['k']) else int(r['k'])} | {r['codec']} | {r['topsis_score']:.4f} |")
        lines += ['','These are rankings **within** the indicated network and dataset group; they are not evidence that one strategy dominates all clinical tasks.']
        winners=ranking[ranking['rank']==1].groupby(['dataset','network_mode','transport_method','delivery_scenario','scenario'])
        lines+=['','## Weight sensitivity','']
        for (ds,mode,transport,delivery,sc),grp in winners:
            best=grp['package_id'].unique()
            if len(best)==1 and len(grp)==len(profiles):
                kval=grp.iloc[0]['k']
                label='N/A' if pd.isna(kval) else str(int(kval))
                lines.append(f'- {ds}/{mode}/{transport}/{delivery}/{sc}: the same method ranks first under all {len(profiles)} weight profiles ({grp.iloc[0]["method"]}, k={label}). Check candidate count before treating this as a robust conclusion.')
            else:
                lines.append(f'- {ds}/{mode}/{transport}/{delivery}/{sc}: preferred configuration changes across weights or only one configuration is eligible; avoid claiming an unqualified winner.')
    else:
        lines += ['','**No eligible integrated ranking is available.** Missing observations must not be imputed as if they were verified outcomes.']
    lines += ['','## Conditional recommendation','']
    if len(ranking):
        profile=primary_weight_profile(config)
        baseline=ranking[(ranking['weight_profile']==profile) & (ranking['rank']==1)]
        for _,r in baseline.iterrows():
            goal={'full_fidelity':'exact preservation of the complete clinical source',
                  'selected_columns_exact':'exact preservation of the transmitted/selected columns',
                  'loss_tolerant':'loss-tolerant use subject to external clinical acceptance'}[r['scenario']]
            ktxt='' if pd.isna(r['k']) else f", k={int(r['k'])}"
            prefix='PROVISIONAL (idealized network)' if r['network_mode']!='ssh' else 'SSH-verified package comparison'
            lines.append(f'- **{r["dataset"]} / {r["transport_method"]} / {r["delivery_scenario"]} / {goal}:** {r["method"]}{ktxt}, codec {r["codec"]} ({prefix}, {profile}-weight TOPSIS).')
    else:
        lines.append('No conditional method recommendation can be made from the available evidence.')
    lines += ['', 'The recommendations above are scenario-conditional. A lossy TOPSIS winner must not replace clinical acceptance criteria or an exact-data requirement.']
    lines += violation_sensitivity_table(evidence, config)
    if notes:
        lines += ['','## Warnings',''] + [f'- {x}' for x in sorted(set(notes))]
    lines += ['','## Clinical and deployment limitations','',
              'Interpretability of PCA/AE latent features and clinical effect of errors require task-specific review.',
              'SSH runs require authenticated connections; an unauthenticated checksum sidecar alone does not prove sender identity.',
              'Results from a small development cohort require validation on the full patient population.',
              'The current broad vital-sign bounds are exploratory plausibility screens; no universally validated error-acceptance threshold was found for this study.',
              'Scheduling and Project 4 ingestion remain outside this prototype.']
    return '\n'.join(lines)+'\n'

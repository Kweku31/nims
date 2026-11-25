"""Phase 1 -- Baseline Dataset Profiling.

Profiles storage, missingness, cardinality, sparsity, exact duplicates, and
Pearson correlation structure. Correlation is descriptive only: no columns
are removed in Phase 1.

Identifiers are detected automatically from common ID naming conventions and
may also be declared explicitly with --identifier-columns.
"""
from __future__ import annotations
import argparse, hashlib, json, platform, re, sys, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
import numpy as np
import pandas as pd

@dataclass
class ColumnProfile:
    name: str; dtype: str; n_missing: int; pct_missing: float
    n_unique: int; cardinality_ratio: float; n_zero: int; pct_zero: float
    estimated_bytes: int; pct_dataset_memory: float

@dataclass
class DatasetProfile:
    source_file: str; n_rows: int; n_cols: int; input_file_bytes: int
    total_bytes_in_memory: int; load_time_seconds: float; profiling_time_seconds: float
    columns: list[ColumnProfile] = field(default_factory=list)
    duplicate_column_groups: list[list[str]] = field(default_factory=list)
    correlation_pairs: list[dict] = field(default_factory=list)
    redundant_pairs: list[dict] = field(default_factory=list)
    automatic_identifiers: list[str] = field(default_factory=list)
    manual_identifiers: list[str] = field(default_factory=list)
    identifier_columns: list[str] = field(default_factory=list)
    correlation_variables: list[str] = field(default_factory=list)

def human_size(n:int)->str:
    x=float(n)
    for u in ['B','KB','MB','GB','TB']:
        if x<1024: return f'{x:.2f} {u}'
        x/=1024
    return f'{x:.2f} PB'

def percentage(a,b): return 0.0 if b==0 else float(a/b*100)

def load_dataset(file_path:str):
    p=Path(file_path)
    if not p.is_file(): raise FileNotFoundError(f'Dataset not found: {p.resolve()}')
    size=p.stat().st_size; name=p.name.lower(); t=time.perf_counter()
    if name.endswith('.csv') or name.endswith('.csv.gz'): df=pd.read_csv(p,low_memory=False)
    elif name.endswith('.parquet'): df=pd.read_parquet(p)
    elif name.endswith('.xlsx') or name.endswith('.xls'): df=pd.read_excel(p)
    else: raise ValueError('Supported: .csv, .csv.gz, .parquet, .xlsx, .xls')
    elapsed=time.perf_counter()-t
    print('='*72); print('PHASE 1 -- BASELINE DATASET PROFILING'); print('='*72)
    print(f'Dataset: {p.resolve()}\nRows: {len(df):,}\nColumns: {df.shape[1]:,}')
    print(f'Source size: {human_size(size)} ({size:,} bytes)\nLoad time: {elapsed:.6f} s')
    return df,elapsed,size

def profile_column(df,column,total_memory):
    s=df[column]; n=len(s); miss=int(s.isna().sum()); unique=int(s.nunique(dropna=True))
    if pd.api.types.is_numeric_dtype(s): zero=int(s.eq(0).sum())
    else: zero=0
    mem=int(s.memory_usage(index=False,deep=True))
    return ColumnProfile(str(column),str(s.dtype),miss,percentage(miss,n),unique,
                         unique/n if n else 0.0,zero,percentage(zero,n),mem,percentage(mem,total_memory))

def normalize_column_name(c): return str(c).strip().lower()

def detect_identifier_columns(df):
    """Heuristic only; manual identifiers can supplement it."""
    found=[]
    for c in df.columns:
        original=str(c).strip(); low=normalize_column_name(c)
        separated=bool(re.search(r'(^id$|[_\-\s]id$)',low))
        camel_upper=bool(re.search(r'(?:Id|ID)$',original))
        if separated or camel_upper: found.append(c)
    return found

def combine_identifier_columns(df,manual):
    auto=detect_identifier_columns(df)
    missing=[c for c in manual if c not in df.columns]
    if missing: raise ValueError('Manual identifier column(s) not found: '+', '.join(missing))
    manual_present=[c for c in manual if c in df.columns]
    union=set(auto)|set(manual_present)
    combined=[c for c in df.columns if c in union]
    return auto,manual_present,combined

def numeric_variable_profile(df,auto_ids,manual_ids,all_ids):
    rows=[]; aset=set(auto_ids); mset=set(manual_ids); ids=set(all_ids)
    for c in df.select_dtypes(include=[np.number]).columns:
        s=df[c]; isid=c in ids
        rows.append({'variable':c,'data_type':str(s.dtype),'n_unique':int(s.nunique(dropna=True)),
                     'n_missing':int(s.isna().sum()),'pct_missing':float(s.isna().mean()*100),
                     'identifier':isid,'automatic_identifier':c in aset,'manual_identifier':c in mset,
                     'included_in_correlation':not isid,
                     'reason':'Excluded: identifier' if isid else 'Included: numeric analytical variable'})
    return pd.DataFrame(rows)

def column_fingerprint(s):
    h=pd.util.hash_pandas_object(s,index=False).values
    return hashlib.sha256(h.tobytes()).hexdigest()

def find_duplicate_columns(df):
    groups={}
    for c in df.columns: groups.setdefault(column_fingerprint(df[c]),[]).append(c)
    out=[]
    for candidates in groups.values():
        if len(candidates)<2: continue
        verified=[]
        for c in candidates:
            for g in verified:
                if df[c].equals(df[g[0]]): g.append(c); break
            else: verified.append([c])
        out.extend(g for g in verified if len(g)>1)
    return out

def calculate_correlations(df,identifier_columns,threshold,max_columns):
    numeric=df.select_dtypes(include=[np.number]).columns.tolist(); ids=set(identifier_columns)
    variables=[c for c in numeric if c not in ids]
    if len(variables)>max_columns:
        return [],[],variables,True
    all_pairs=[]; high=[]
    for a,b in combinations(variables,2):
        pair=df[[a,b]].dropna(); n=len(pair)
        status='calculated'; r=np.nan
        if n<3: status='insufficient observations'
        elif pair[a].nunique(dropna=True)<=1 or pair[b].nunique(dropna=True)<=1: status='constant variable'
        else: r=pair[a].corr(pair[b],method='pearson')
        abs_r=abs(float(r)) if pd.notna(r) else np.nan
        flag=bool(pd.notna(abs_r) and abs_r>=threshold)
        rec={'column_a':a,'column_b':b,'pearson_r':float(r) if pd.notna(r) else np.nan,
             'absolute_pearson_correlation':abs_r,'pairwise_n':n,'above_threshold':flag,'status':status}
        all_pairs.append(rec)
        if flag: high.append(rec.copy())
    key=lambda x: -1 if pd.isna(x['absolute_pearson_correlation']) else x['absolute_pearson_correlation']
    all_pairs.sort(key=key,reverse=True); high.sort(key=key,reverse=True)
    return all_pairs,high,variables,False

def profile_dataset(df,source_file,input_bytes,load_time,threshold,max_columns,manual_ids):
    t=time.perf_counter(); total=int(df.memory_usage(index=True,deep=True).sum())
    cols=[profile_column(df,c,total) for c in df.columns]
    duplicates=find_duplicate_columns(df)
    auto,manual,ids=combine_identifier_columns(df,manual_ids)
    pairs,high,corr_vars,skipped=calculate_correlations(df,ids,threshold,max_columns)
    elapsed=time.perf_counter()-t
    profile=DatasetProfile(str(Path(source_file).resolve()),len(df),df.shape[1],input_bytes,total,
                           load_time,elapsed,cols,duplicates,pairs,high,auto,manual,ids,corr_vars)
    return profile,skipped

def column_profiles_to_dataframe(profile):
    return pd.DataFrame([asdict(c) for c in profile.columns]).sort_values('estimated_bytes',ascending=False)

def create_run_directory(dataset_path,base):
    p=Path(dataset_path); name=p.name[:-7] if p.name.lower().endswith('.csv.gz') else p.stem
    now=datetime.now(timezone.utc); d=Path(base)/f'{name}_{now.strftime("%Y%m%d_%H%M%S")}'
    d.mkdir(parents=True,exist_ok=False); return d,now.isoformat()

def sha256_file(path,chunk=1024*1024):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def print_report(profile,skipped,threshold,top_n):
    print('\n'+'='*72+'\nBASELINE PROFILE RESULTS\n'+'='*72)
    print(f'Rows: {profile.n_rows:,} | Columns: {profile.n_cols:,}')
    print(f'Input size: {human_size(profile.input_file_bytes)} | DataFrame memory: {human_size(profile.total_bytes_in_memory)}')
    print(f'Load: {profile.load_time_seconds:.6f}s | Profiling: {profile.profiling_time_seconds:.6f}s')
    print('\nIdentifiers')
    print('  Automatic: '+(', '.join(profile.automatic_identifiers) if profile.automatic_identifiers else 'None'))
    print('  Manual:    '+(', '.join(profile.manual_identifiers) if profile.manual_identifiers else 'None'))
    print('  Combined:  '+(', '.join(profile.identifier_columns) if profile.identifier_columns else 'None'))
    print('\nCorrelation variables: '+(', '.join(profile.correlation_variables) if profile.correlation_variables else 'None'))
    if skipped: print('Correlation skipped: dimensionality safeguard exceeded.'); return
    print(f'Unique pairs: {len(profile.correlation_pairs):,} | Threshold: |r| >= {threshold}')
    if profile.correlation_pairs:
        print(pd.DataFrame(profile.correlation_pairs)[['column_a','column_b','pearson_r','absolute_pearson_correlation','pairwise_n']].to_string(index=False))
    print(f'\nPairs above threshold: {len(profile.redundant_pairs)}')
    if profile.redundant_pairs:
        print(pd.DataFrame(profile.redundant_pairs).head(top_n)[['column_a','column_b','pearson_r','absolute_pearson_correlation']].to_string(index=False))

def save_results(profile,df,out,skipped,threshold,timestamp,checksum,args):
    out=Path(out)
    column_profiles_to_dataframe(profile).to_csv(out/'column_profile.csv',index=False)
    numeric_variable_profile(df,profile.automatic_identifiers,profile.manual_identifiers,profile.identifier_columns).to_csv(out/'numeric_variable_profile.csv',index=False)
    pair_cols=['column_a','column_b','pearson_r','absolute_pearson_correlation','pairwise_n','above_threshold','status']
    pd.DataFrame(profile.correlation_pairs,columns=pair_cols).to_csv(out/'correlation_all_pairs.csv',index=False)
    pd.DataFrame(profile.redundant_pairs,columns=pair_cols).to_csv(out/'redundant_pairs.csv',index=False)
    dup=[]
    for i,g in enumerate(profile.duplicate_column_groups,1):
        dup.extend({'group_id':i,'column':c} for c in g)
    pd.DataFrame(dup,columns=['group_id','column']).to_csv(out/'duplicate_columns.csv',index=False)
    total=profile.load_time_seconds+profile.profiling_time_seconds
    pd.DataFrame([{'source_file':profile.source_file,'n_rows':profile.n_rows,'n_columns':profile.n_cols,
                   'input_file_bytes':profile.input_file_bytes,'dataframe_memory_bytes':profile.total_bytes_in_memory,
                   'load_time_seconds':profile.load_time_seconds,'profiling_time_seconds':profile.profiling_time_seconds,
                   'total_phase1_seconds':total,'numeric_identifiers_excluded':len(profile.identifier_columns),
                   'numeric_variables_correlated':len(profile.correlation_variables),'correlation_pairs_calculated':len(profile.correlation_pairs),
                   'duplicate_groups':len(profile.duplicate_column_groups),'highly_correlated_pairs':len(profile.redundant_pairs),
                   'correlation_threshold':threshold,'correlation_skipped':skipped}]).to_csv(out/'dataset_summary.csv',index=False)
    metadata={'experiment':{'phase':'Phase 1 - Baseline Profiling','script':Path(__file__).name,'run_timestamp_utc':timestamp},
              'dataset':{'filename':Path(profile.source_file).name,'absolute_path':profile.source_file,'sha256':checksum,
                         'rows':profile.n_rows,'columns':profile.n_cols,'input_file_bytes':profile.input_file_bytes,
                         'dataframe_memory_bytes':profile.total_bytes_in_memory},
              'identifier_detection':{'automatic_method':'name heuristic: ID, *_ID, *-ID, space-ID, CamelCase/uppercase ID suffix',
                                      'automatic_identifiers':profile.automatic_identifiers,'manual_identifiers':profile.manual_identifiers,
                                      'combined_identifiers':profile.identifier_columns,'identifiers_retained_in_dataset':True,
                                      'identifiers_excluded_from_correlation':True},
              'correlation_analysis':{'method':'Pearson','purpose':'descriptive profiling; no feature removal in Phase 1',
                                      'threshold':threshold,'missing_value_strategy':'pairwise-complete observations',
                                      'correlation_variables':profile.correlation_variables,'total_pairs':len(profile.correlation_pairs),
                                      'highly_correlated_pairs':len(profile.redundant_pairs),'skipped':skipped},
              'parameters':vars(args),'command_line':sys.argv,
              'environment':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,
                             'os':platform.system(),'release':platform.release(),'machine':platform.machine()},
              'timing':{'load_seconds':profile.load_time_seconds,'profiling_seconds':profile.profiling_time_seconds,'total_seconds':total}}
    with open(out/'profile_metadata.json','w',encoding='utf-8') as f: json.dump(metadata,f,indent=2)

def parse_arguments():
    p=argparse.ArgumentParser(description='Phase 1 baseline profiling for structured clinical datasets.')
    p.add_argument('dataset')
    p.add_argument('--output-dir',default='output/profiling')
    p.add_argument('--threshold',type=float,default=0.95,help='Flag potential redundancy when |r| >= threshold; no columns are removed.')
    p.add_argument('--max-correlation-columns',type=int,default=2000)
    p.add_argument('--top-n',type=int,default=10)
    p.add_argument('--identifier-columns',nargs='*',default=[],help='Additional non-standard identifier columns to exclude from correlation while retaining them in the dataset.')
    a=p.parse_args()
    if not 0<a.threshold<=1: p.error('--threshold must be > 0 and <= 1')
    if a.max_correlation_columns<2: p.error('--max-correlation-columns must be >= 2')
    if a.top_n<1: p.error('--top-n must be >= 1')
    return a

def main():
    args=parse_arguments(); df,load,size=load_dataset(args.dataset)
    profile,skipped=profile_dataset(df,args.dataset,size,load,args.threshold,args.max_correlation_columns,args.identifier_columns)
    print_report(profile,skipped,args.threshold,args.top_n)
    run_dir,timestamp=create_run_directory(args.dataset,args.output_dir)
    checksum=sha256_file(args.dataset)
    save_results(profile,df,run_dir,skipped,args.threshold,timestamp,checksum,args)
    print('\n'+'='*72+'\nPHASE 1 COMPLETED SUCCESSFULLY\n'+'='*72)
    print(f'Results saved to: {run_dir.resolve()}')
    print('Outputs: column_profile.csv, numeric_variable_profile.csv, correlation_all_pairs.csv, redundant_pairs.csv, duplicate_columns.csv, dataset_summary.csv, profile_metadata.json')

if __name__=='__main__': main()

"""Attach two completed follow-ups to their source experiment's dashboard snapshot."""
import argparse
from pathlib import Path
import sys
import shutil

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'thesis_unified'))
from thesis_pipeline.core import atomic_json, load_json, sha256
from thesis_pipeline.transport_decision import baseline_rankings, followup_results


def attach(snapshot, baseline, archives):
    manifest=load_json(snapshot/'run_manifest.json')
    source=Path(manifest['phase_directories']['phase2']).resolve()
    if load_json(archives/'protocol.json').get('source_run')!=manifest['run_id']:
        raise ValueError('Archive study belongs to another experiment')
    files=load_json(baseline/'protocol.json')['files']
    for entry in files.values():
        path=Path(entry['path']).resolve()
        if not path.is_relative_to(source/'artifacts') or sha256(path)!=entry['sha256']:
            raise ValueError('Direct-file study artifacts differ from the selected experiment')
    benchmark=pd.read_csv(source/'transfer_benchmark.csv')
    stages={'phase2_paired':{'run':baseline},'phase6_paired':{'run':archives}}
    studies=followup_results(stages,benchmark)
    studies['adaptive_rankings']=baseline_rankings(benchmark,None).to_dict('records')
    atomic_json(snapshot/'transport_studies.json',dict(run_id=manifest['run_id'],
                input_sha256=manifest['input_sha256'],studies=studies))
    ranked=pd.DataFrame(studies['paired_rankings'])
    ranked.to_csv(baseline/'topsis_by_transport.csv',index=False)
    ranked.to_csv(snapshot/'paired_baseline_topsis.csv',index=False)
    for name,folder in [('baseline',baseline),('archives',archives)]:
        shutil.copyfile(folder/'trials.csv',snapshot/f'paired_{name}_trials.csv')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','baseline','archives'):
        parser.add_argument(name,type=Path)
    args=parser.parse_args()
    attach(args.snapshot,args.baseline,args.archives)

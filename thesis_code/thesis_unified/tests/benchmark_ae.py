"""Synthetic AE timing/quality comparison; no patient data or network transfers.

Example: python tests/benchmark_ae.py --rows 790215 --epochs 5 --output result.json
This is a short throughput probe, not a converged-quality experiment.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thesis_pipeline.legacy import ae_runtime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows',type=int,default=131072)
    parser.add_argument('--epochs',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.rows < 2 or args.epochs < 1:
        parser.error('Rows must be >=2 and epochs >=1')
    spec=importlib.util.spec_from_file_location('benchmark_engine',
        Path(ae_runtime.__file__).with_name('04_dimensionality_reduction_updated.py'))
    engine=importlib.util.module_from_spec(spec); sys.modules[spec.name]=engine
    spec.loader.exec_module(engine)
    cp=ae_runtime.cuda_module()
    rng=np.random.RandomState(20261118)
    x=rng.normal(size=(args.rows,8)) @ rng.normal(size=(8,34))
    x += rng.normal(scale=.1,size=x.shape)
    results=[]
    for backend,batch in [('cpu',256),('cpu',4096),('gpu',4096)]:
        model=engine.AutoencoderCompressor(2,max_iter=args.epochs,backend=backend,
            batch_size=batch,cpu_threads=1,progress_interval=1)
        started=time.perf_counter();model.fit(x);seconds=time.perf_counter()-started
        # Observe reconstruction quality separately from the fit timer.
        latent=model.compress(x)
        a=latent
        for i in range(2,len(model.model.coefs_)):
            a=a @ model.model.coefs_[i] + model.model.intercepts_[i]
            if i<len(model.model.coefs_)-1:a=np.maximum(a,0)
        target=model.scaler.transform(x)
        r2=1-float(np.sum((a-target)**2)/np.sum((target-target.mean(axis=0))**2))
        record={'backend':backend,'batch_size':batch,'rows':args.rows,'features':34,
                'fit_seconds':seconds,'reconstruction_r2_standardized':r2,
                **model.training_diagnostics()}
        print(json.dumps(record),flush=True);results.append(record)
        args.output.write_text(json.dumps({'synthetic':True,'note':'Short throughput probe; not converged quality. GPU availability preflight is outside fit timer.',
            'device':ae_runtime.device_details(cp),'results':results},indent=2)+'\n')


if __name__=='__main__':
    main()

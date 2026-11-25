import unittest
from pathlib import Path
import sys

import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thesis_pipeline.transport_decision import baseline_rankings


class TransportRankings(unittest.TestCase):
    def test_paired_rankings_use_matched_bytes_and_means(self):
        benchmark=pd.DataFrame({'format':['csv_gzip','parquet','csv_zstd'],
                                'size_reduction_pct':[60,60,60],'packaging_mean_seconds':[2,2,2]})
        rows=[]
        for index,fmt in enumerate(['gzip','Parquet','Zstandard']):
            for block in range(1,5):
                for method in ('scp','rsync'):
                    rows.append(dict(format=fmt,block=block,method=method,transport_method=method,
                                     attempts=1,state='verified',sha256=fmt,payload_sha256=fmt,
                                     remote_sha256_verified=True,
                                     successful_send_seconds=(index+1 if method=='scp' else 3-index)))
        # An unverified peer excludes both measurements from this pair.
        rows[1].update(remote_sha256_verified=False,successful_send_seconds=900)
        result=baseline_rankings(benchmark,pd.DataFrame(rows),paired=True)
        winners=result[result['rank']==1].set_index('transport_method').format.to_dict()
        self.assertEqual(winners,{'rsync':'csv_zstd','scp':'csv_gzip'})
        self.assertEqual(list(result[result.format=='csv_gzip'].trials),[3,3])
        for r in rows:
            if r['method']=='rsync':
                r['payload_sha256']='unexpected'
        self.assertTrue(baseline_rankings(benchmark,pd.DataFrame(rows),paired=True).empty)

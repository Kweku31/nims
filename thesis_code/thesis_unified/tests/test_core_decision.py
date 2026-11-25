"""Offline unit tests: python -m unittest discover -s tests -v"""
import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from thesis_pipeline.core import Checkpoint, sha256, ssh_preflight
from thesis_pipeline import decision

class PipelineTests(unittest.TestCase):
    def test_topsis_rank_and_constant_columns(self):
        df = pd.DataFrame([
            {'total_transmitted_bytes':100,'effective_delivery_seconds':1,
             'R2_retained_variation_observed_STANDARDIZED':1,
             'knn5_overlap_original_vs_reconstruction':1,
             'clinical_predictor_retention_pct':100,
             'original_observed_measurement_retention_pct':100,
             'clinical_screen_new_violation_pct':0},
            {'total_transmitted_bytes':200,'effective_delivery_seconds':2,
             'R2_retained_variation_observed_STANDARDIZED':.4,
             'knn5_overlap_original_vs_reconstruction':.3,
             'clinical_predictor_retention_pct':100,
             'original_observed_measurement_retention_pct':100,
             'clinical_screen_new_violation_pct':0}])
        score=decision.topsis(df,decision.WEIGHTS['balanced'])
        self.assertGreater(score.iloc[0],score.iloc[1])
    def test_resume_and_checksum_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); src=p/'dataset.csv';src.write_text('x\n1\n')
            called=[]
            def task():
                called.append('run'); out=p/'record';out.write_text('ok')
                return {'artifacts':[str(out)]}
            with Checkpoint(p,{},src) as ck:
                ck.stage('phase1',task)
                ck.stage('phase1',task)
                self.assertEqual(len(called),1)
                (p/'record').write_text('tampered')
                ck.stage('phase1',task)
                self.assertEqual(len(called),2)
                ck.stage('phase1',task,dependencies={'x':'new'})
                self.assertEqual(len(called),3)
    def test_scenarios_exclude_lossy_from_exact(self):
        rows=[]
        for lossless,method in [(True,'parquet'),(False,'autoencoder')]:
            r={'dataset':'x','network_mode':'simulated_ideal','method':method,'k':None if lossless else 2,
               'codec':'native','package_id':method,'lossless':lossless,
               'checksum_passed':True,'receiver_recovery_passed':True}
            for criterion in decision.CRITERIA:r[criterion]=1
            r['clinical_predictor_retention_pct']=100
            rows.append(r)
        e,rank,notes=decision.decision_tables(pd.DataFrame(rows))
        exact=rank[rank['scenario']=='full_fidelity']
        self.assertEqual(set(exact['method']),{'parquet'})
    def test_no_ssh_preflight_without_host(self):
        self.assertFalse(ssh_preflight(None))

if __name__=='__main__':unittest.main()

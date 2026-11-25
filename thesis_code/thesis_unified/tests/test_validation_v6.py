"""Regression tests for evidence provenance, SSH strictness and sensitivity."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from thesis_pipeline import decision, phase2
import run_thesis


def rows():
    out = []
    for method, lossless, violations, name in (
        ('parquet', True, 0., 'p'),
        ('pca', False, .3, 'q'),
        ('autoencoder', False, 1.3, 'r')):
        entry = dict(dataset='original', network_mode='simulated_ideal', method=method,
                     lossless=lossless,k=None if lossless else 2,codec='native', package_id=name,
                     checksum_passed=True,receiver_recovery_passed=True,
                     remote_sha256_verified=False,remote_trials_completed=0)
        entry.update({col: 1. for col in decision.CRITERIA})
        entry.update(total_transmitted_bytes=500 if lossless else 200,
                     effective_delivery_seconds=1 if lossless else 2,
                     clinical_predictor_retention_pct=100,
                     original_observed_measurement_retention_pct=100,
                     clinical_screen_new_violation_pct=violations)
        out.append(entry)
    return pd.DataFrame(out)

class ValidationV6Tests(unittest.TestCase):
    def test_simulation_not_empirical(self):
        evidence, rankings, _ = decision.decision_tables(rows())
        self.assertEqual(int(evidence.measured_completely.sum()),0)
        self.assertEqual(int(evidence.empirical_ssh_eligible.sum()),0)
        self.assertEqual(int(evidence.criteria_available.sum()),3)
        self.assertTrue((rankings.decision_evidence_status=='simulated_provisional').all())
        self.assertTrue((rankings.candidate_count>0).all())

    def test_ssh_requires_remote_hash_and_trials(self):
        e=rows();e['network_mode']='ssh'
        a,_,_=decision.decision_tables(e)
        self.assertFalse(a.measured_completely.any())
        e['remote_sha256_verified']=True;e['remote_trials_completed']=10
        a,_,_=decision.decision_tables(e)
        self.assertTrue(a.measured_completely.all())

    def test_duplicate_custom_is_not_new_sensitivity_profile(self):
        cfg={'topsis_weights':decision.WEIGHTS['balanced']}
        self.assertNotIn('custom',decision.get_weight_profiles(cfg))
        cfg={'topsis_weights':[.23,.17,.22,.12,.10,.06,.10]}
        self.assertIn('custom',decision.get_weight_profiles(cfg))

    def test_violation_gates_and_sensitivity_report(self):
        e=rows()
        evaluated,_,_=decision.decision_tables(e,{'maximum_new_violation_pct':.5})
        self.assertEqual(int(evaluated.loss_tolerant_eligible.sum()),2)
        text='\n'.join(decision.violation_sensitivity_table(e,{'violation_sensitivity':[0,.5,1]}))
        self.assertIn('0.5%',text)
        self.assertIn('clinical safety standards',text)

    def test_strict_ssh_phase2_fails_not_simulates(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(phase2,'ssh_preflight',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'Strict SSH'):
                    phase2.run(Path(td)/'missing.csv',Path(td)/'work',
                               {'remote':'user@example.org','transfer_mode':'ssh'})

    def test_strict_ssh_main_creates_log_and_failed_status_before_phase1(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            data=p/'sample.csv';data.write_text('patient_id,time,HR,SepsisLabel\np1,1,80,0\n')
            out=p/'thesis_runs'
            args=['run_thesis.py','--dataset',str(data),'--output-dir',str(out),
                  '--remote','user@example.org','--transfer-mode','ssh']
            with patch.object(sys,'argv',args), patch('thesis_pipeline.core.ssh_preflight',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'SSH is required'):
                    run_thesis.main()
            self.assertTrue((out/'pipeline.log').exists())
            self.assertEqual(json.loads((out/'run_status.json').read_text())['status'],'failed')
            self.assertFalse((out/'runs').exists())

if __name__=='__main__': unittest.main()

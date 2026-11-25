"""Verify configurable percentage rules without network or model training."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from thesis_pipeline.core import as_fraction, as_percent, percentage_weights
from thesis_pipeline import decision, phase1, phase3
import run_thesis


class PercentageConfigurationTests(unittest.TestCase):
    def test_percentage_equivalence(self):
        for value in (75, '75', '75%', 0.75, '0.75'):
            self.assertAlmostEqual(as_fraction(value, name='coverage'), .75)
        self.assertAlmostEqual(as_fraction('1%', name='cutoff'), .01)
        self.assertAlmostEqual(as_fraction(1, name='cutoff'), 1.)
        self.assertAlmostEqual(as_percent(95, name='screen'), 95)

    def test_reject_bad_percentage(self):
        for value in (-10, 101, 'nan', 'inf', 'oops'):
            with self.assertRaises(ValueError):
                as_fraction(value, name='coverage')
        with self.assertRaises(ValueError):
            percentage_weights([10, 10, 10, 10, 10, 10, 10], name='weights')

    def test_cli_overrides_and_normalizes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'input.csv'; source.write_text('patient_id,time,HR,SepsisLabel\na,1,80,0\n')
            config=Path(tmp)/'config.json'; config.write_text('{"dataset":"'+str(source)+'","patient_coverage_min":90}')
            argv=['run_thesis.py','--config',str(config),'--patient-coverage-min','75%',
                  '--missingness-thresholds','70','85','95',
                  '--correlation-threshold','95','--phase1-correlation-threshold','90%',
                  '--minimum-feature-retention-pct','80%',
                  '--minimum-measurement-retention-pct','95',
                  '--maximum-new-violation-pct','0.5%',
                  '--topsis-weights','22','18','22','12','10','6','10',
                  '--feature-sets','all']
            with patch.object(sys,'argv',argv):
                options,_=run_thesis.normalize_options(run_thesis.arguments())
            self.assertEqual(options['missingness_thresholds'],[.7,.85,.95])
            self.assertEqual(options['patient_coverage_min'],.75)
            self.assertEqual(options['correlation_threshold'],.95)
            self.assertEqual(options['phase1_correlation_threshold'],.9)
            self.assertEqual(options['minimum_feature_retention_pct'],80.)
            self.assertEqual(options['minimum_measurement_retention_pct'],95.)
            self.assertEqual(options['maximum_new_violation_pct'],.5)
            self.assertEqual(options['topsis_weights'],[.22,.18,.22,.12,.1,.06,.1])
            self.assertEqual(options['feature_sets'],'all')

    def test_phase3_passes_thresholds_to_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            dataset=d/'raw.csv';dataset.write_text('patient_id,time,HR,SepsisLabel\np1,1,80,0\n')
            called=[]
            def fake_run(script,args,log):
                called.extend(args)
                folder=d/'run_1'; folder.mkdir(exist_ok=True)
                (folder/'threshold_comparison.csv').write_text('experiment\nFS_85_clinical_review\n')
                (folder/'run_metadata.json').write_text('{}')
                return ''
            with patch.object(phase3,'legacy_run',fake_run):
                phase3.run(dataset,d,{'patient_coverage_min':.60,
                                      'missingness_thresholds':[.7,.85,.95],
                                      'correlation_threshold':.9,
                                      'correlation_action':'flag',
                                      'min_correlation_observations':150,
                                      'min_correlation_patients':15,
                                      'clinically_protected':['Lactate']})
            self.assertEqual(called[called.index('--patient-coverage-min')+1],'0.6')
            self.assertEqual(called[called.index('--correlation-threshold')+1],'0.9')
            self.assertEqual(called[called.index('--min-correlation-patients')+1],'15')
            self.assertEqual(called[called.index('--missingness-thresholds')+1:called.index('--clinically-protected')],
                             ['0.7','0.85','0.95'])

    def test_decision_optional_cutoffs_and_custom_profile(self):
        rows=[]
        for method,retention in [('parquet',100),('pca',60)]:
            row={'dataset':'x','network_mode':'simulated_ideal','method':method,
                 'k':None if method=='parquet' else 2,'codec':'native',
                 'package_id':method, 'lossless':method=='parquet',
                 'checksum_passed':True,'receiver_recovery_passed':True}
            row.update({c:1 for c in decision.CRITERIA})
            row['clinical_predictor_retention_pct']=retention
            rows.append(row)
        _,ranking,_=decision.decision_tables(pd.DataFrame(rows),{
            'minimum_feature_retention_pct':80,
            'topsis_weights':[.22,.18,.22,.12,.10,.06,.10]})
        subset=ranking[(ranking['scenario']=='loss_tolerant')]
        self.assertEqual(set(subset.method),{'parquet'})
        self.assertEqual(set(subset.weight_profile),set(decision.WEIGHTS))
        _,ranking_open,_=decision.decision_tables(pd.DataFrame(rows))
        self.assertIn('pca',set(ranking_open[ranking_open.scenario=='loss_tolerant'].method))


if __name__=='__main__': unittest.main()

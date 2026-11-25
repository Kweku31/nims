import unittest
from pathlib import Path
from unittest.mock import patch
import tempfile

from thesis_pipeline import decision
from thesis_pipeline.core import percentage_weights
from test_validation_v6 import rows
from thesis_pipeline import phase4


class SelectedWeightsTests(unittest.TestCase):
    def test_ae_stopping_controls_forwarded_without_changing_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(phase4,'legacy_run') as run, patch.object(phase4,'find_new_run',return_value=root):
                phase4.run(root/'input.csv',root,{'ae_tol':.001,'ae_patience':8})
            argv=run.call_args.args[1]
            self.assertEqual(argv[argv.index('--ae-tol')+1],'0.001')
            self.assertEqual(argv[argv.index('--ae-patience')+1],'8')
    def test_equal_default_and_duplicate_profile_selection(self):
        self.assertEqual(decision.primary_weight_profile(), 'equal')
        self.assertEqual(decision.get_weight_profiles()['equal'], [1/7]*7)
        for name, weights in decision.WEIGHTS.items():
            config = {'topsis_weights': weights}
            self.assertEqual(decision.primary_weight_profile(config), name)
            self.assertNotIn('custom', decision.get_weight_profiles(config))

    def test_percentages_include_one_percent_and_zero(self):
        self.assertEqual(percentage_weights([1,19,20,20,20,20,0], name='weights'),
                         [.01,.19,.2,.2,.2,.2,0])
        for invalid in [None, [True,0,0,0,0,0,0], [0]*7, [10]*7,
                        [float('nan'),1,0,0,0,0,0], [float('inf'),0,0,0,0,0,0],
                        [-1,101,0,0,0,0,0], [1]*6]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                percentage_weights(invalid, name='weights')

    def test_custom_weights_control_sensitivity_winner_and_report(self):
        evidence = rows().iloc[:2].copy().reset_index(drop=True)
        evidence['method'] = ['smaller', 'faster']
        evidence['package_id'] = ['smaller', 'faster']
        evidence['total_transmitted_bytes'] = [10,100]
        evidence['effective_delivery_seconds'] = [100,10]
        evidence['clinical_screen_new_violation_pct'] = 0
        config = {'topsis_weights':[1,0,0,0,0,0,0], 'violation_sensitivity':[0]}
        assessed, ranking, notes = decision.decision_tables(evidence, config)
        winners = ranking[(ranking.weight_profile=='custom') & (ranking['rank']==1)]
        self.assertEqual(set(winners.method), {'smaller'})
        table = '\n'.join(decision.violation_sensitivity_table(evidence, config))
        self.assertIn('Winner (custom weights)', table)
        self.assertIn('smaller', table)
        self.assertNotIn('faster', table)
        report = decision.render_report(assessed, ranking, notes,
                                        {'run_id':'weights', 'input_sha256':'test'}, config)
        self.assertIn('Primary weight profile: **custom**', report)
        self.assertIn('| total_transmitted_bytes | cost | 100.000000% |', report)
        default = '\n'.join(decision.violation_sensitivity_table(evidence, {}))
        self.assertIn('Winner (equal weights)', default)


if __name__ == '__main__':
    unittest.main()

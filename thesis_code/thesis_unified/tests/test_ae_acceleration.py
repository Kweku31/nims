import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import warnings

import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from thesis_pipeline.legacy import ae_runtime
from thesis_pipeline import phase4

PATH = Path(ae_runtime.__file__).with_name('04_dimensionality_reduction_updated.py')
spec = importlib.util.spec_from_file_location('ae_test_engine', PATH)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


class AccelerationTests(unittest.TestCase):
    def setUp(self):
        self.x = np.random.RandomState(11).normal(size=(71, 7))

    def test_array_optimizer_matches_sklearn_with_partial_final_batch(self):
        for tol, patience in [(1e-4, 20), (100., 1)]:
            with self.subTest(tol=tol), warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
                warnings.simplefilter('ignore')
                baseline = MLPRegressor(hidden_layer_sizes=(32,2,32), batch_size=16,
                    max_iter=5, random_state=42, tol=tol, n_iter_no_change=patience).fit(self.x,self.x)
                actual, _ = ae_runtime.fit_array_autoencoder(self.x, hidden=(32,), k=2,
                    max_iter=5, seed=42, tol=tol, patience=patience, batch_size=16, dtype='float64')
                self.assertEqual(baseline.n_iter_, actual.n_iter_)
                np.testing.assert_allclose(actual.loss_curve_, baseline.loss_curve_, atol=1e-13, rtol=1e-13)
                for a,b in zip(actual.coefs_+actual.intercepts_, baseline.coefs_+baseline.intercepts_):
                    np.testing.assert_allclose(a,b,atol=1e-13,rtol=1e-13)

    def test_cpu_progress_preserves_original_training_and_decoder(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            model=engine.AutoencoderCompressor(2,max_iter=3,batch_size=16,progress_interval=1).fit(self.x)
            x=StandardScaler().fit_transform(self.x)
            baseline=MLPRegressor(hidden_layer_sizes=(32,2,32),batch_size=16,max_iter=3,
                                  random_state=42,n_iter_no_change=20).fit(x,x)
        for a,b in zip(model.model.coefs_,baseline.coefs_):
            np.testing.assert_array_equal(a,b)
        self.assertIn('epoch 3/3',output.getvalue())
        self.assertIn('remaining_to_epoch_limit',output.getvalue())
        self.assertEqual(model.training_diagnostics()['autoencoder_backend'],'cpu')
        self.assertEqual(model.decoder_arrays()['decoder_layers'],2)
        self.assertEqual(model.compress(self.x).shape,(71,2))

    def test_requested_gpu_failure_is_not_silently_cpu(self):
        with patch.object(engine,'cuda_module',side_effect=RuntimeError('GPU unavailable')):
            with self.assertRaisesRegex(RuntimeError,'GPU unavailable'):
                engine.AutoencoderCompressor(2,backend='gpu').fit(self.x)
        with patch.dict(sys.modules,{'cupy':None}):
            with self.assertRaisesRegex(RuntimeError,'explicitly select CPU'):
                ae_runtime.cuda_module()

    def test_unavailable_gpu_fails_before_pipeline_work(self):
        import json
        import tempfile
        import run_thesis
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            dataset=root/'input.csv'; dataset.write_text('patient_id,time,SepsisLabel,HR\n1,0,0,80\n')
            args=['run_thesis.py','--dataset',str(dataset),'--output-dir',str(root/'output'),
                  '--ae-backend','gpu','--transfer-mode','simulated']
            with patch.object(sys,'argv',args), patch.object(ae_runtime,'cuda_module',side_effect=RuntimeError('No GPU')), \
                    patch.object(run_thesis,'execute_pipeline') as execute, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'No GPU'):
                    run_thesis.main()
            execute.assert_not_called()
            self.assertEqual(json.loads((root/'output/run_status.json').read_text())['status'],'failed')

    def test_invalid_execution_settings(self):
        for values in [dict(backend='auto'),dict(batch_size=0),dict(cpu_threads=-1),
                       dict(progress_interval=0),dict(batch_size=True)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                engine.AutoencoderCompressor(2,**values)

    def test_adapter_forwards_execution_settings(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with patch.object(phase4,'legacy_run') as run, patch.object(phase4,'find_new_run',return_value=folder):
                phase4.run(folder/'input.csv',folder,dict(ae_backend='gpu',ae_batch_size=4096,
                                                        ae_cpu_threads=2,ae_progress_interval=1))
            argv=run.call_args.args[1]
            for key,value in [('backend','gpu'),('batch-size','4096'),('cpu-threads','2'),('progress-interval','1')]:
                self.assertEqual(argv[argv.index('--ae-'+key)+1],value)

    @unittest.skipUnless(os.environ.get('THESIS_TEST_GPU')=='1','opt-in real CUDA test')
    def test_gpu_training_matches_cpu_float32_and_decoder_is_portable(self):
        cp=ae_runtime.cuda_module()
        settings=dict(hidden=(32,),k=2,max_iter=3,seed=42,tol=1e-4,patience=20,batch_size=16)
        with contextlib.redirect_stdout(io.StringIO()):
            expected,_=ae_runtime.fit_array_autoencoder(self.x,**settings)
            actual,_=ae_runtime.fit_array_autoencoder(self.x,**settings,xp=cp)
            model=engine.AutoencoderCompressor(2,max_iter=3,backend='gpu',batch_size=16).fit(self.x)
        np.testing.assert_allclose(actual.loss_curve_,expected.loss_curve_,atol=2e-6,rtol=2e-5)
        for a,b in zip(actual.coefs_,expected.coefs_):
            np.testing.assert_allclose(a,b,atol=2e-5,rtol=2e-4)
        arrays=model.decoder_arrays()
        self.assertTrue(all(isinstance(a,np.ndarray) for a in arrays.values()))
        self.assertEqual(model.training_diagnostics()['autoencoder_training_dtype'],'float32')
        self.assertIn('autoencoder_device',model.training_diagnostics())


if __name__ == '__main__':
    unittest.main()

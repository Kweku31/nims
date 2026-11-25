"""Optional CUDA execution for the existing dense ReLU/Adam autoencoder.

CPU training still uses sklearn. The array implementation is checked against
sklearn using NumPy, then executes the same operations with CuPy on CUDA.
No CuPy import is needed to train on CPU or reconstruct a received payload.
"""
import math
import time
from types import SimpleNamespace

import numpy as np
from sklearn.neural_network import MLPRegressor


def progress(epoch, maximum, loss, started, backend):
    elapsed = time.perf_counter() - started
    remaining = elapsed / epoch * (maximum - epoch)
    print(f'AE {backend}: epoch {epoch}/{maximum}, loss={loss:.8f}, '
          f'elapsed={elapsed:.1f}s, remaining_to_epoch_limit~{remaining:.1f}s '
          '(may stop earlier)', flush=True)


class ProgressMLPRegressor(MLPRegressor):
    """Observe sklearn's epoch hook without changing its optimizer or stopping."""
    def _update_no_improvement_count(self, *args, **kwargs):
        super()._update_no_improvement_count(*args, **kwargs)
        if self.n_iter_ == 1 or self.n_iter_ % self.progress_interval == 0 or self.n_iter_ == self.max_iter:
            progress(self.n_iter_, self.max_iter, self.loss_, self.progress_started, 'cpu')


def cuda_module():
    """Fail explicitly; never substitute CPU for a requested GPU experiment."""
    try:
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError('No CUDA device detected')
        # Exercise runtime, NVRTC and BLAS, not merely driver discovery.
        probe = cp.maximum(cp.ones((2, 2), dtype=cp.float32), 0)
        (probe @ probe).sum().item()
        cp.cuda.Stream.null.synchronize()
        return cp
    except Exception as exc:
        raise RuntimeError('GPU autoencoder unavailable. Install a matching CuPy/CUDA '
                           'runtime and check GPU access, or explicitly select CPU. '
                           f'Details: {exc}') from exc


def device_details(cp):
    props = cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)
    name = props['name']
    return {'autoencoder_device': name.decode() if isinstance(name, bytes) else str(name),
            'autoencoder_cupy_version': cp.__version__,
            'autoencoder_cuda_runtime': cp.cuda.runtime.runtimeGetVersion(),
            'autoencoder_cuda_driver': cp.cuda.runtime.driverGetVersion()}


def fit_array_autoencoder(X, *, hidden, k, max_iter, seed, tol, patience,
                          batch_size, xp=np, dtype='float32', progress_interval=10):
    """Port of sklearn's unweighted squared-error MLP Adam training loop.

    Same Glorot initialization, CPU RNG/shuffle, alpha=0.0001, Adam defaults,
    training-loss tolerance and patience. Float32 GPU results need not match
    float64 CPU bitwise. NumPy execution exists for regression validation only.
    """
    started = time.perf_counter()
    rng = np.random.RandomState(seed)
    n, p = X.shape
    units = (p, *hidden, k, *reversed(hidden), p)
    weights, biases = [], []
    for fan_in, fan_out in zip(units[:-1], units[1:]):
        bound = math.sqrt(6.0 / (fan_in + fan_out))
        weights.append(xp.asarray(rng.uniform(-bound, bound, (fan_in, fan_out)), dtype=dtype))
        biases.append(xp.asarray(rng.uniform(-bound, bound, fan_out), dtype=dtype))
    data = xp.asarray(X, dtype=dtype)
    params = weights + biases
    ms = [xp.zeros_like(a) for a in params]
    vs = [xp.zeros_like(a) for a in params]
    indices = np.arange(n)
    size = min(batch_size, n)
    curve, best, bad, step = [], float('inf'), 0, 0
    alpha, beta1, beta2, epsilon = 0.0001, 0.9, 0.999, 1e-8
    for epoch in range(1, max_iter + 1):
        indices = rng.permutation(indices)
        # Copy only the shuffled indices; the full training matrix stays on GPU.
        order = xp.asarray(indices)
        accumulated = xp.asarray(0., dtype=dtype)
        for start in range(0, n, size):
            batch = data[order[start:start + size]]
            count = len(batch)
            acts = [batch]
            for i, (w, b) in enumerate(zip(weights, biases)):
                value = acts[-1] @ w + b
                acts.append(xp.maximum(value, 0) if i < len(weights)-1 else value)
            delta = acts[-1] - batch
            loss = 0.5 * xp.mean(delta ** 2)
            loss += (0.5 * alpha / count) * sum(xp.sum(w * w) for w in weights)
            accumulated += loss * count
            wg, bg = [None] * len(weights), [None] * len(biases)
            for i in range(len(weights)-1, -1, -1):
                wg[i] = (acts[i].T @ delta + alpha * weights[i]) / count
                bg[i] = xp.mean(delta, axis=0)
                if i:
                    delta = (delta @ weights[i].T) * (acts[i] > 0)
            step += 1
            rate = 0.001 * math.sqrt(1 - beta2 ** step) / (1 - beta1 ** step)
            for i, grad in enumerate(wg + bg):
                ms[i] = beta1 * ms[i] + (1 - beta1) * grad
                vs[i] = beta2 * vs[i] + (1 - beta2) * grad ** 2
                params[i] -= rate * ms[i] / (xp.sqrt(vs[i]) + epsilon)
        loss = float(accumulated / n)  # Synchronizes GPU work before timing/logging.
        if not math.isfinite(loss):
            raise ValueError('AE training produced non-finite loss; experiment rejected')
        curve.append(loss)
        bad = bad + 1 if loss > best - tol else 0
        best = min(best, loss)
        if epoch == 1 or epoch % progress_interval == 0 or epoch == max_iter or bad > patience:
            progress(epoch, max_iter, loss, started, 'gpu' if xp is not np else 'array-test')
        if bad > patience:
            break
    to_numpy = np.asarray if xp is np else xp.asnumpy
    model = SimpleNamespace(coefs_=[to_numpy(w) for w in weights],
                            intercepts_=[to_numpy(b) for b in biases],
                            n_iter_=epoch, loss_=loss, loss_curve_=curve)
    # sklearn warns at the budget unless the stopping criterion fires first.
    return model, epoch == max_iter and bad <= patience

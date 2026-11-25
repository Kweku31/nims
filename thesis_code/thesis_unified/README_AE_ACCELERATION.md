# Autoencoder CPU/GPU execution and timing

Updated 18 November 2026. These controls are available in the unified pipeline,
standalone Phase 4 script and React dashboard. CPU remains the default so existing
experiment configurations retain the original sklearn execution path.

## Starting an accelerated experiment

In **New experiment → Optional settings → Model training and utility evaluation**:

- **AE compute device:** NVIDIA GPU (CuPy / CUDA).
- **AE batch size:** try 4096 for a throughput/quality pilot on this laptop.
- **AE progress interval:** 1 for a message after every epoch, or 10 for less logging.
- **Autoencoder iteration limit:** keep 500 for a comparable maximum budget, or use
  100 for an initial exploration. A shorter budget is not evidence of convergence.
- Keep tolerance 0.0001 and patience 20 initially. Review achieved loss, observed
  R², and clinical-screen results before choosing a final study configuration.

These fields are optional. Defaults are CPU, batch size 256, library-default CPU
threading (0), progress every 10 epochs, maximum 500 epochs in the unified runner,
tolerance 0.0001 and patience 20. The standalone script retains its previous
300-epoch default. A batch larger than the dataset is clipped to the row count.
Larger batches mean fewer optimizer updates per epoch, so identical epoch limits
are not identical optimization budgets. More CPU threads are not necessarily faster
for the small 32-unit hidden layers.

From `thesis_unified` (use your pipeline Python environment):

```bash
../thesis/bin/python run_thesis.py --dataset /path/to/data.csv \
  --output-dir /path/to/new_gpu_experiment --transfer-mode simulated \
  --ae-backend gpu --ae-batch-size 4096 --ae-max-iter 100 \
  --ae-progress-interval 1
```

The standalone `04_dimensionality_reduction_updated.py` accepts the same AE flags.
The simulation flag above tests compute/payload creation without real SSH.
Configure SSH explicitly for a measured network experiment.

An active CPU training job cannot switch device mid-fit. Allow it to finish, or
stop it using the dashboard if you choose to abandon that fit. Existing checkpoints
do not contain per-epoch optimizer state. A new backend/batch configuration is a
new experiment, not a continuation of the old fit. Code/config fingerprints prevent
reuse of incompatible checkpoints. The live dashboard server must be restarted
from the pipeline environment after its active experiment finishes to load the new
server controls. The updated frontend explains this if the server is still old.

## Installation and explicit failure handling

This laptop has a Quadro P2000 with Max-Q Design, 4 GiB VRAM, and working system
CUDA 11 libraries. The project environment now has `cupy-cuda11x==13.6.0` installed;
no NVIDIA driver replacement was performed. CPU installations do not need CuPy.
For another machine with matching CUDA 11 libraries, from `thesis_unified`:

```bash
python -m pip install -r requirements-gpu-cuda11.txt
python -c "from thesis_pipeline.legacy.ae_runtime import cuda_module, device_details; print(device_details(cuda_module()))"
```

Other CUDA installations need the matching CuPy distribution; follow the
[official CuPy installation instructions](https://docs.cupy.dev/en/stable/install.html).
Do not install conflicting CuPy distributions in one environment. This requirements
file does not install a GPU driver or complete system CUDA toolkit.

GPU preflight exercises allocation, a compiled elementwise kernel and matrix
multiplication. Missing CuPy, incompatible CUDA, or an inaccessible GPU causes an
explicit failure before the unified pipeline phases start. There is no silent CPU
substitution. GPU out-of-memory errors also fail the affected computation; reduce
the batch size or explicitly select CPU in a new experiment. The full standardized
training matrix resides on the GPU; batch size alone cannot bound all VRAM use.

## Algorithm and provenance

CPU training still calls sklearn's MLPRegressor optimizer. A subclass observes its
epoch progress hook; it does not change the optimizer or stop condition. GPU training
executes the same dense architecture: predictors → 32 ReLU → k ReLU → 32 ReLU →
linear reconstruction, Glorot initialization, Adam (learning rate 0.001, beta1 0.9,
beta2 0.999, epsilon 1e-8), L2 coefficient 0.0001, the same seeded NumPy shuffle,
and the same training-loss tolerance/patience logic. There is no validation split.
Stopping occurs after **more than** the configured patience count of insufficient
improvements. Reaching the iteration budget is reported as a convergence warning.

GPU math is float32; the existing pipeline CPU training is float64. The GPU path
is an explicit alternative numerical implementation, not a bitwise reproduction
of every CPU result. Precision, batch size and hardware can affect the optimization
trajectory. Regression tests compare the array implementation in float64 against
sklearn, and compare real GPU float32 training against its CPU-array equivalent.
Tests were run with sklearn 1.9.0, NumPy 2.5.2 and CuPy 13.6.0. Re-run them after
library upgrades, especially because the CPU progress observer uses a sklearn hook.

PCA, median imputation, clinical screens, missingness restoration, exact passthrough
columns and the NPZ decoder format are unchanged. Receiver reconstruction and
encoding remain NumPy/CPU operations; receivers do not need a GPU or CuPy.
`phase4_comparison.csv` records backend, actual device, training dtype, requested
and effective batch size, CPU thread request, achieved epochs/loss and stopping
information. GPU rows also record CuPy, runtime and driver versions. Configuration
is saved in the final run manifest; Phase 4 metadata saves the execution parameters.
SHA-256 checks still apply to outgoing payloads and sidecars.

## Timing interpretation

`fit_seconds` includes scaling, model initialization, training data upload, GPU
training and decoder-weight download. GPU work is synchronized before returning.
Availability preflight is infrastructure setup outside the delivery proxy. Kernel
compilation occurring inside fit is included. Encoding is timed separately as before.
The `fresh_data` scenario charges fit (divided by the stated model reuse count),
encoding and initial payload creation. `existing_payload` excludes these preparation
costs in scoring; it does not skip training when constructing a new experimental
payload. Phase 6 wrapper costs remain in both scenarios.

Progress messages give epoch, training loss, elapsed training time and a rough time
remaining **to the maximum epoch budget**, not a promised completion time. Early
stopping can finish sooner; system load can make the estimate change. Messages flow
into the same consolidated `pipeline.log` shown by the dashboard.

## Measured synthetic throughput on this laptop

A five-epoch k=2 probe used 790,215 synthetic rows, 34 predictors and one CPU BLAS
thread. These are short, unconverged measurements, taken while another CPU research
experiment was active. They are not clinical results or an isolated hardware study.

| Execution | Batch | Fit including scaling/setup | Reconstruction R² after 5 epochs |
|---|---:|---:|---:|
| CPU / sklearn float64 | 256 | 55.72 s | 0.52554 |
| CPU / sklearn float64 | 4096 | 38.70 s | 0.46736 |
| GPU / CuPy float32 | 4096 | 27.02 s | 0.46732 |

The GPU fit was approximately **2.06× faster** than CPU/batch-256 and **1.43× faster**
than CPU at the same batch size. The larger batch had worse reconstruction after
five epochs. These timings cannot establish equal-quality speedup, predict the
number of epochs to converge, or guarantee the duration of the full six-phase run.
A small 32,768-row probe also showed GPU overhead can make batch-256 slower than CPU.
Use quality-versus-time measurements when choosing the final thesis configuration.

Reproduce the cohort-sized probe without SSH:

```bash
../thesis/bin/python tests/benchmark_ae.py --rows 790215 --epochs 5 --output benchmark.json
```

Saved measurements are `validation_v7/gpu_benchmark.json` and `.log`. Validation
also includes CPU equivalence, stopping behavior, explicit GPU failures, real-GPU
portable decoder checks, all-phase synthetic execution and checkpoint reuse, and
dashboard option validation. See `VALIDATION_V7.md` for the final test totals.

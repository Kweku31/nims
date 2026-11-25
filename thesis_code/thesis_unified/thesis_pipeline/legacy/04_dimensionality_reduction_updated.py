"""04_dimensionality_reduction.py — Phase 4 (hospital -> university).

Evaluate PCA and a nonlinear autoencoder plus multiple LOSSLESS baselines on raw or Phase-3-selected *wide*
clinical CSV data.  This is a data-transfer / reconstruction experiment,
not a sepsis-prediction experiment: no train/validation/test patient split.

At the hospital: median-impute *only for fitting*, standardize, fit a model,
encode clinical predictors, and serialize one portable NPZ payload containing:
  - float32 reduced coordinates, Z
  - fitted inverse/decoder parameters (the SAME learned model)
  - a bit-packed mask to restore which clinical entries were originally missing
  - unmodified patient IDs, time, label, and configured passthrough fields,
    including Age, HospAdmTime and ICULOS by default (clinical/temporal invariants)
  - column names/order and a small manifest.

Every outgoing payload has a mandatory .sha256 sidecar. The university MUST
verify it before opening the NPZ; missing or mismatched checksums are fatal.


At the university: load the actual payload, invert using the supplied decoder,
restore the original missingness mask, and reorder the columns. Reconstruction
is lossy for measured clinical values, but missingness and structural values
are retained exactly.  The receiver never independently fits a new model.

Actual on-disk file size, NOT Z.nbytes plus an estimated model size, is used
for transfer-size calculations. --bandwidth-mbps gives only an IDEALIZED
transmission time; use the Phase-2/6 SCP benchmark for observed network times.

FIDDLE is excluded from the main pipeline by methodological decision.
PCA and nonlinear autoencoder are the only dimensionality-reduction methods.

Dependencies: numpy, pandas, scipy (sklearn dependency), scikit-learn.
Optional lossless tools: `zstd` command or `zstandard` Python package, and pyarrow for Parquet.
Any unavailable optional baseline is marked unavailable, never claimed benchmarked.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import platform
import subprocess
import re
import shutil
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from threadpoolctl import threadpool_limits
try:
    from thesis_pipeline.legacy.ae_runtime import ProgressMLPRegressor, cuda_module, device_details, fit_array_autoencoder
except ModuleNotFoundError as exc:
    if exc.name != "thesis_pipeline":
        raise
    from ae_runtime import ProgressMLPRegressor, cuda_module, device_details, fit_array_autoencoder
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning
from pandas.testing import assert_frame_equal


@dataclass
class TransferTiming:
    t_fit: float = 0.0
    t_compress: float = 0.0
    t_package: float = 0.0
    t_verify_checksum: float = 0.0
    t_transmit_simulated: float = 0.0
    t_load: float = 0.0
    t_reconstruct: float = 0.0
    t_evaluate: float = 0.0

    @property
    def t_total_simulated(self) -> float:
        return (self.t_fit + self.t_compress + self.t_package
                + self.t_transmit_simulated + self.t_verify_checksum
                + self.t_load + self.t_reconstruct)


def simulated_transmission_time(payload_bytes: int, bandwidth_mbps: float) -> float:
    """Ideal payload-serialization time; ignores protocol/SSH/network overhead."""
    return (payload_bytes * 8) / (bandwidth_mbps * 1_000_000)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()



def checksum_sidecar_path(payload: Path) -> Path:
    """A separate SHA-256 manifest that accompanies every transferred file."""
    return payload.with_name(payload.name + '.sha256')


def create_checksum_sidecar(payload: Path) -> tuple[Path, str]:
    """Sender: write a standard one-line SHA-256 file for exact payload bytes."""
    digest = sha256_file(payload)
    sidecar = checksum_sidecar_path(payload)
    sidecar.write_text(f'{digest}  {payload.name}\n', encoding='utf-8')
    return sidecar, digest


def verify_payload_checksum(payload: Path, checksum_file: Path | None = None) -> str:
    """Receiver: MUST verify trusted SHA-256 sidecar before reading a payload.

    No unchecked receiver mode is available. This detects accidental damage;
    authenticate the manifest separately if malicious tampering is in scope.
    """
    payload = Path(payload)
    manifest = Path(checksum_file) if checksum_file is not None else checksum_sidecar_path(payload)
    if not payload.is_file():
        raise FileNotFoundError(f'Received payload not found: {payload}')
    if not manifest.is_file():
        raise FileNotFoundError(
            f'Required checksum file missing: {manifest}. '
            'Refusing to reconstruct without SHA-256 verification.'
        )
    lines = manifest.read_text(encoding='utf-8').splitlines()
    if len(lines) != 1:
        raise ValueError(f'Checksum file must contain exactly one SHA-256 entry: {manifest}')
    match = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?(.+)', lines[0])
    if match is None or match.group(2) != payload.name:
        raise ValueError(
            f'Malformed checksum entry or filename mismatch for {payload.name}: {manifest}'
        )
    expected = match.group(1).lower()
    measured = sha256_file(payload)
    if not hmac.compare_digest(measured, expected):
        raise ValueError(
            f'SHA-256 MISMATCH for {payload.name}: expected {expected}, '
            f'actual {measured}. Refusing reconstruction.'
        )
    return measured


def verify_gzip_content(gzip_path: Path, expected_source_sha256: str) -> float:
    """Verify the full decompressed gzip bytes match the original CSV."""
    tick = time.perf_counter()
    h = hashlib.sha256()
    with gzip.open(gzip_path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    if not hmac.compare_digest(h.hexdigest(), expected_source_sha256):
        raise ValueError('Lossless gzip baseline did not reproduce the original CSV bytes')
    return time.perf_counter() - tick


def elapsed_gzip_baseline(source: Path, target: Path) -> tuple[int, float]:
    t0 = time.perf_counter()
    with source.open('rb') as fin, gzip.open(target, 'wb', compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
    return target.stat().st_size, time.perf_counter() - t0


class MissingOptionalDependency(RuntimeError):
    pass


def write_zstd_lossless(source: Path, target: Path, level: int = 3) -> tuple[int, float]:
    """Compress CSV bytes losslessly. Prefer installed zstd command, fallback to Python module."""
    tick = time.perf_counter()
    zstd_cmd = shutil.which('zstd')
    if zstd_cmd:
        with target.open('wb') as out:
            subprocess.run([zstd_cmd, '-q', '-f', f'-{level}', '-c', str(source)],
                           stdout=out, check=True)
    else:
        try:
            import zstandard as zstd
        except ImportError as exc:
            raise MissingOptionalDependency('Zstandard requires zstd executable or pip install zstandard') from exc
        with source.open('rb') as fin, target.open('wb') as fout:
            zstd.ZstdCompressor(level=level).copy_stream(fin, fout)
    return target.stat().st_size, time.perf_counter() - tick


def verify_zstd_roundtrip(target: Path, expected_source_sha256: str) -> float:
    """SHA-256 of decompressed CSV bytes must match the source."""
    tick = time.perf_counter()
    digest = hashlib.sha256()
    zstd_cmd = shutil.which('zstd')
    if zstd_cmd:
        proc = subprocess.Popen([zstd_cmd, '-q', '-d', '-c', str(target)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b''):
            digest.update(chunk)
        proc.stdout.close()
        stderr = proc.stderr.read() if proc.stderr else b''
        rc = proc.wait()
        if rc:
            raise RuntimeError(f'Zstandard decompression failed: {stderr.decode(errors="replace")}')
    else:
        import zstandard as zstd
        with target.open('rb') as fin, zstd.ZstdDecompressor().stream_reader(fin) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected_source_sha256):
        raise ValueError('Zstandard decompression did not restore exact source CSV bytes')
    return time.perf_counter() - tick


def write_verify_parquet(source_df: pd.DataFrame, target: Path) -> tuple[int, float, float]:
    """Write Parquet+zstd; require exact DataFrame value and missingness recovery."""
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise MissingOptionalDependency('Parquet baseline requires pip install pyarrow') from exc
    tick = time.perf_counter()
    source_df.to_parquet(target, engine='pyarrow', compression='zstd', index=False)
    write_seconds = time.perf_counter() - tick
    tick = time.perf_counter()
    restored = pd.read_parquet(target, engine='pyarrow')
    assert_frame_equal(source_df.reset_index(drop=True), restored.reset_index(drop=True),
                       check_dtype=False, check_exact=True, check_names=True)
    read_seconds = time.perf_counter() - tick
    return target.stat().st_size, write_seconds, read_seconds


def measure_lossless_baselines(source_path: Path, source_df: pd.DataFrame,
                               output_dir: Path, source_sha: str,
                               formats: list[str], bandwidth_mbps: float,
                               strict: bool = False) -> list[dict]:
    """Separate lossless baselines from lossy PCA/AE experiments."""
    baselines = []
    for fmt in formats:
        filename = {'gzip': 'source_csv_gzip6.csv.gz',
                    'zstd': 'source_csv_zstd3.csv.zst',
                    'parquet': 'source_parquet_zstd.parquet'}[fmt]
        target = output_dir / filename
        print(f'Lossless baseline: {fmt}', flush=True)
        try:
            if fmt == 'gzip':
                n_bytes, packaging_seconds = elapsed_gzip_baseline(source_path, target)
            elif fmt == 'zstd':
                n_bytes, packaging_seconds = write_zstd_lossless(source_path, target)
            else:
                n_bytes, packaging_seconds, _ = write_verify_parquet(source_df, target)
            checksum_path, digest = create_checksum_sidecar(target)
            tick = time.perf_counter()
            if verify_payload_checksum(target, checksum_path) != digest:
                raise RuntimeError('SHA-256 verification error')
            verify_seconds = time.perf_counter() - tick
            if fmt == 'gzip':
                decode_seconds = verify_gzip_content(target, source_sha)
            elif fmt == 'zstd':
                decode_seconds = verify_zstd_roundtrip(target, source_sha)
            else:
                tick = time.perf_counter()
                restored = pd.read_parquet(target, engine='pyarrow')
                assert_frame_equal(source_df.reset_index(drop=True), restored.reset_index(drop=True),
                                   check_dtype=False, check_exact=True, check_names=True)
                decode_seconds = time.perf_counter() - tick
            transferred = n_bytes + checksum_path.stat().st_size
            baselines.append({
                'method': fmt, 'status': 'verified', 'error': '',
                'payload_filename': filename, 'sha256': digest,
                'payload_bytes': n_bytes,
                'checksum_bytes': checksum_path.stat().st_size,
                'transmitted_total_bytes': transferred,
                'size_reduction_pct_vs_source_csv': 100 * (1 - transferred / source_path.stat().st_size),
                'packaging_seconds': packaging_seconds,
                'receiver_checksum_verification_seconds': verify_seconds,
                'receiver_decompression_or_read_seconds': decode_seconds,
                'transmission_seconds_SIMULATED': simulated_transmission_time(transferred, bandwidth_mbps),
                'total_seconds_SIMULATED': (packaging_seconds + verify_seconds + decode_seconds
                    + simulated_transmission_time(transferred, bandwidth_mbps)),
                'roundtrip_verified': True,
                'roundtrip_definition': ('byte-identical original CSV'
                                        if fmt in ('gzip', 'zstd') else
                                        'equal DataFrame values, missingness, order and columns'),
            })
        except MissingOptionalDependency as exc:
            if strict:
                raise
            print(f'  Baseline unavailable or failed: {fmt}: {exc}', flush=True)
            baselines.append({'method': fmt, 'status': 'unavailable_or_failed',
                              'error': str(exc), 'roundtrip_verified': False})
    if not any(x['status'] == 'verified' for x in baselines):
        raise RuntimeError('No lossless baselines could be verified')
    return baselines


# Exploratory broad vital-sign data-quality screens for this research prototype.
# They are NOT universal clinically validated acceptance thresholds.
# Values outside are flagged, never clipped or changed automatically.
PHYSIOLOGICAL_SCREEN_RANGES = {
    'HR': (5., 300.),
    'O2Sat': (0., 100.),
    'SaO2': (0., 100.),
    'Temp': (25., 45.),
    'SBP': (20., 300.),
    'MAP': (10., 250.),
    'DBP': (5., 225.),
}


def json_safe_float(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


class PCACompressor:
    name = 'pca'

    def __init__(self, k: int, seed: int = 42):
        self.k = k
        self.scaler = StandardScaler()
        self.model = PCA(n_components=k, random_state=seed)

    def fit(self, X: np.ndarray) -> 'PCACompressor':
        self.model.fit(self.scaler.fit_transform(X))
        return self

    def compress(self, X: np.ndarray) -> np.ndarray:
        return self.model.transform(self.scaler.transform(X)).astype(np.float32)

    def decoder_arrays(self) -> dict[str, np.ndarray]:
        # Sender encoder is NOT needed at receiver; share the exact decoder.
        return {
            'pca_components': np.asarray(self.model.components_, dtype=np.float32),
            'pca_mean': np.asarray(self.model.mean_, dtype=np.float32),
            'scaler_mean': np.asarray(self.scaler.mean_, dtype=np.float32),
            'scaler_scale': np.asarray(self.scaler.scale_, dtype=np.float32),
        }

    @property
    def explained_variance(self) -> float:
        return float(self.model.explained_variance_ratio_.sum())


class AutoencoderCompressor:
    name = 'autoencoder'

    def __init__(self, k: int, hidden: tuple[int, ...] = (32,),
                 max_iter: int = 300, seed: int = 42, tol: float = 1e-4,
                 patience: int = 20, backend: str = "cpu", batch_size: int = 256,
                 cpu_threads: int = 0, progress_interval: int = 10):
        self.k = k
        self.hidden = hidden
        self.bottleneck_layer = len(hidden)
        self.max_iter = max_iter
        self.tol = tol
        self.patience = patience
        if backend not in ('cpu', 'gpu'):
            raise ValueError('AE backend must be cpu or gpu')
        for label, value, minimum in [('batch_size', batch_size, 1), ('cpu_threads', cpu_threads, 0),
                                      ('progress_interval', progress_interval, 1)]:
            if type(value) is not int or value < minimum:
                raise ValueError(f'AE {label} must be an integer >= {minimum}')
        self.backend, self.batch_size = backend, batch_size
        self.cpu_threads, self.progress_interval = cpu_threads, progress_interval
        self.seed = seed
        self.device_info = {'autoencoder_device': 'CPU'}
        self.scaler = StandardScaler()
        # MLPRegressor is trained to reconstruct its input (unsupervised).
        # early_stopping=False means it creates no internal validation split.
        self.model = ProgressMLPRegressor(
            hidden_layer_sizes=(*hidden, k, *reversed(hidden)),
            activation='relu', solver='adam', batch_size=batch_size,
            early_stopping=False, max_iter=max_iter,
            random_state=seed, tol=tol, n_iter_no_change=patience,
        )

    def fit(self, X: np.ndarray) -> 'AutoencoderCompressor':
        scaled = self.scaler.fit_transform(X)
        self.training_dtype = 'float32' if self.backend == 'gpu' else str(scaled.dtype)
        self.effective_batch_size = min(self.batch_size, len(scaled))
        # Record convergence warnings instead of silently suppressing them.
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter('always', ConvergenceWarning)
            if self.backend == 'gpu':
                cp = cuda_module()
                self.device_info = device_details(cp)
                self.model, reached_limit = fit_array_autoencoder(
                    scaled, hidden=self.hidden, k=self.k, max_iter=self.max_iter,
                    seed=self.seed, tol=self.tol, patience=self.patience,
                    batch_size=self.batch_size, xp=cp, dtype='float32',
                    progress_interval=self.progress_interval)
                cp.cuda.Stream.null.synchronize()
                if reached_limit:
                    warnings.warn('Maximum AE iterations reached before convergence', ConvergenceWarning)
            else:
                self.model.progress_interval = self.progress_interval
                self.model.progress_started = time.perf_counter()
                with threadpool_limits(limits=self.cpu_threads or None):
                    self.model.fit(scaled, scaled)
        self.convergence_warning = any(
            issubclass(w.category, ConvergenceWarning) for w in recorded
        )
        return self

    def compress(self, X: np.ndarray) -> np.ndarray:
        a = self.scaler.transform(X)
        for i in range(self.bottleneck_layer + 1):
            a = np.maximum(0, a @ self.model.coefs_[i] + self.model.intercepts_[i])
        return np.asarray(a, dtype=np.float32)

    def decoder_arrays(self) -> dict[str, np.ndarray]:
        # Send decoder ONLY, not the encoder, since inversion uses just this.
        out: dict[str, np.ndarray] = {
            'scaler_mean': np.asarray(self.scaler.mean_, dtype=np.float32),
            'scaler_scale': np.asarray(self.scaler.scale_, dtype=np.float32),
        }
        start = self.bottleneck_layer + 1
        for j, i in enumerate(range(start, len(self.model.coefs_))):
            out[f'decoder_w_{j}'] = np.asarray(self.model.coefs_[i], dtype=np.float32)
            out[f'decoder_b_{j}'] = np.asarray(self.model.intercepts_[i], dtype=np.float32)
        out['decoder_layers'] = np.array(len(self.model.coefs_) - start, dtype=np.int64)
        return out

    @property
    def iterations(self) -> int:
        return int(self.model.n_iter_)

    @property
    def loss(self) -> float:
        return float(self.model.loss_)

    def training_diagnostics(self) -> dict:
        """Training stop diagnostics; these do not prove global optimality."""
        curve = [float(x) for x in self.model.loss_curve_]
        last_n = min(10, max(0, len(curve) - 1))
        rel_change = (
            (curve[-1 - last_n] - curve[-1]) / max(abs(curve[-1 - last_n]), 1e-12)
            if last_n else None
        )
        return {
            'autoencoder_backend': self.backend,
            'autoencoder_training_dtype': self.training_dtype,
            'autoencoder_batch_size_effective': self.effective_batch_size,
            'autoencoder_batch_size_requested': self.batch_size,
            'autoencoder_cpu_threads_requested': self.cpu_threads,
            **self.device_info,
            'autoencoder_iterations': self.iterations,
            'autoencoder_training_loss': self.loss,
            'autoencoder_first_loss': curve[0] if curve else None,
            'autoencoder_relative_loss_improvement_last_10': rel_change,
            'autoencoder_convergence_warning': bool(self.convergence_warning),
            'autoencoder_stopped_before_iteration_budget': self.iterations < self.max_iter,
            'autoencoder_optimizer_stopped_by_criterion': (
                not self.convergence_warning and self.iterations < self.max_iter
            ),
            'autoencoder_max_iter': self.max_iter,
            'autoencoder_tol': self.tol,
            'autoencoder_patience': self.patience,
        }


# Patient-level and time-related fields should not be learned as continuous
# measurements by a row-wise autoencoder/PCA. Exact preservation prevents the
# model from inventing within-patient age fluctuations or irregular ICU hours.
DEFAULT_EXACT_CLINICAL_COLUMNS = ('Age', 'HospAdmTime', 'ICULOS')


def choose_columns(df: pd.DataFrame, args: argparse.Namespace) -> tuple[list[str], list[str]]:
    if args.id_column not in df or args.time_column not in df:
        raise ValueError(f'Required columns {args.id_column!r} and/or {args.time_column!r} not found')
    if args.outcome_column not in df:
        raise ValueError(f'Required column {args.outcome_column!r} not found')
    protected = {args.id_column, args.time_column, args.outcome_column}
    protected.update(x for x in args.passthrough if x in df.columns)
    # These are also protected when callers override --passthrough: the
    # separate --exact-clinical-columns flag controls this protection.
    protected.update(x for x in args.exact_clinical_columns if x in df.columns)
    # Other likely identifiers are preserved, never used as numerical predictors.
    protected.update(c for c in df if re.search(r'(^id$|[_\-\s]id$|(?:Id|ID)$)', str(c)))
    passthrough = [c for c in df.columns if c in protected]
    predictors = [c for c in df.columns if c not in protected]
    if not predictors:
        raise ValueError('No analytical predictors left after excluding structural/passthrough columns')
    if any(not pd.api.types.is_numeric_dtype(df[c]) for c in predictors):
        bad = [c for c in predictors if not pd.api.types.is_numeric_dtype(df[c])]
        raise ValueError(f'Non-numeric predictor columns: {bad}. Add them to --passthrough.')
    return predictors, passthrough


def fit_input(df: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    observed = np.isfinite(df[columns].to_numpy(dtype=np.float64))
    raw = df[columns].to_numpy(dtype=np.float64)
    if np.isinf(raw).any():
        raise ValueError('Infinite clinical values found. Clean or exclude them before Phase 4.')
    # All-missing columns are permissible: their imputation value is zero,
    # and the saved mask ensures they are reconstructed as all missing.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=RuntimeWarning)
        medians = np.nanmedian(raw, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    X = np.where(observed, raw, medians).astype(np.float32)
    return X, observed, np.asarray(medians, dtype=np.float32)


def create_payload(path: Path, *, method: str, k: int, Z: np.ndarray,
                   decoder_arrays: dict[str, np.ndarray],
                   medians: np.ndarray, observed: np.ndarray, df: pd.DataFrame,
                   predictors: list[str], passthrough: list[str],
                   bundle_compression: str) -> int:
    manifest = {
        'format_version': 1,
        'method': method,
        'k': k,
        'n_rows': len(df),
        'n_predictors_encoded': len(predictors),
        'n_passthrough_columns': len(passthrough),
        'mask_bitorder': 'little',
        'encoding': 'float32',
        'missingness_restored_exactly': True,
        'measurement_reconstruction_is_lossy': True,
    }
    arrays: dict[str, np.ndarray] = {
        'manifest_json': np.asarray(json.dumps(manifest)),
        'Z': np.asarray(Z, dtype=np.float32),
        'observed_mask_packed': np.packbits(observed.reshape(-1), bitorder='little'),
        'all_columns': np.asarray(df.columns.to_list(), dtype=np.str_),
        'predictor_columns': np.asarray(predictors, dtype=np.str_),
        'passthrough_columns': np.asarray(passthrough, dtype=np.str_),
        'imputation_medians': medians,
    }
    arrays.update(decoder_arrays)
    for j, column in enumerate(passthrough):
        vals = df[column]
        if pd.api.types.is_numeric_dtype(vals):
            arrays[f'passthrough_{j}'] = vals.to_numpy()
        else:
            if vals.isna().any():
                raise ValueError(f'Non-numeric passthrough {column!r} has missing values; handle it explicitly')
            arrays[f'passthrough_{j}'] = vals.astype(str).to_numpy(dtype=np.str_)
    writer = np.savez_compressed if bundle_compression == 'deflate' else np.savez
    writer(path, **arrays)
    return path.stat().st_size


def load_bundle_arrays(path: Path) -> dict[str, np.ndarray]:
    """Load/decompress the actual transferred file; separate from inversion time."""
    with np.load(path, allow_pickle=False) as bundle:
        return {key: np.asarray(bundle[key]).copy() for key in bundle.files}


def reconstruct_arrays(bundle: dict[str, np.ndarray]) -> pd.DataFrame:
    """Invert using only receiver-side arrays loaded from the transfer file."""
    manifest = json.loads(str(bundle['manifest_json'].item()))
    if manifest['format_version'] != 1:
        raise ValueError('Unsupported transfer payload version')
    Z = np.asarray(bundle['Z'], dtype=np.float32)
    n, k = Z.shape
    columns = bundle['all_columns'].tolist()
    features = bundle['predictor_columns'].tolist()
    passthrough = bundle['passthrough_columns'].tolist()
    if n != manifest['n_rows'] or k != manifest['k'] or len(features) != manifest['n_predictors_encoded']:
        raise ValueError('Inconsistent manifest or encoded dimensions')
    mean = bundle['scaler_mean']
    scale = bundle['scaler_scale']
    if manifest['method'] == 'pca':
        standardized = Z @ bundle['pca_components'] + bundle['pca_mean']
    elif manifest['method'] == 'autoencoder':
        standardized = Z
        layers = int(bundle['decoder_layers'])
        for j in range(layers):
            standardized = standardized @ bundle[f'decoder_w_{j}'] + bundle[f'decoder_b_{j}']
            if j < layers - 1:
                standardized = np.maximum(0, standardized)
    else:
        raise ValueError(f"Unrecognized compressor: {manifest['method']}")
    X_hat = standardized * scale + mean
    mask = np.unpackbits(bundle['observed_mask_packed'], bitorder='little')
    mask = mask[:n * len(features)].reshape(n, len(features)).astype(bool)
    X_hat[~mask] = np.nan  # preserve original missingness precisely
    data: dict[str, np.ndarray] = {col: X_hat[:, j] for j, col in enumerate(features)}
    for j, col in enumerate(passthrough):
        data[col] = bundle[f'passthrough_{j}'].copy()
    if set(data) != set(columns):
        raise ValueError('Reconstructed column names do not match original manifest')
    return pd.DataFrame(data, columns=columns)


def reconstruct_bundle(path: Path) -> pd.DataFrame:
    """Receiver-friendly entry point, for one received NPZ payload."""
    return reconstruct_arrays(load_bundle_arrays(path))


def evaluate_reconstruction(source: pd.DataFrame, reconstructed: pd.DataFrame,
                            predictors: list[str], passthrough: list[str],
                            method: str, k: int) -> tuple[dict, list[dict]]:
    if reconstructed.shape != source.shape:
        raise ValueError('Reconstructed shape does not match source')
    if list(reconstructed.columns) != list(source.columns):
        raise ValueError('Reconstructed column order does not match source')
    for c in passthrough:
        if not source[c].equals(reconstructed[c]):
            raise ValueError(f'Passthrough column {c!r} differs after reconstruction')
    original = source[predictors].to_numpy(dtype=np.float64)
    recovered = reconstructed[predictors].to_numpy(dtype=np.float64)
    observed = np.isfinite(original)
    if not np.array_equal(observed, np.isfinite(recovered)):
        raise ValueError('Missingness mask changed during reconstruction')

    feature_rows = []
    total_sse = total_ae = 0.0
    count = 0
    total_scaled_sse = scaled_count = 0
    source_outside_total = reconstructed_outside_total = new_violation_total = 0
    screened_count = 0
    for j, col in enumerate(predictors):
        valid = observed[:, j]
        n_obs = int(valid.sum())
        mae = rmse = nrmse = nmae = sd = None
        if n_obs:
            dif = recovered[valid, j] - original[valid, j]
            mae = float(np.mean(np.abs(dif)))
            rmse = float(np.sqrt(np.mean(dif ** 2)))
            sd = float(np.std(original[valid, j]))
            nrmse = float(rmse / sd) if sd > 1e-12 else None
            nmae = float(mae / sd) if sd > 1e-12 else None
            total_sse += float(np.sum(dif ** 2))
            total_ae += float(np.sum(np.abs(dif)))
            count += n_obs
            if nrmse is not None:
                total_scaled_sse += float(np.sum((dif / sd) ** 2))
                scaled_count += n_obs
        bounds = PHYSIOLOGICAL_SCREEN_RANGES.get(col)
        original_violations = reconstructed_violations = new_violations = None
        if bounds is not None:
            lo, hi = bounds
            orig_out = valid & ((original[:, j] < lo) | (original[:, j] > hi))
            recon_out = valid & ((recovered[:, j] < lo) | (recovered[:, j] > hi))
            original_violations = int(orig_out.sum())
            reconstructed_violations = int(recon_out.sum())
            new_violations = int((recon_out & ~orig_out).sum())
            screened_count += n_obs
            source_outside_total += original_violations
            reconstructed_outside_total += reconstructed_violations
            new_violation_total += new_violations
        feature_rows.append({
            'method': method, 'k': k, 'feature': col, 'observed_rows': n_obs,
            'missing_pct': (1 - n_obs / len(source)) * 100,
            'mae': mae, 'rmse': rmse,
            'observed_sd': sd,
            'nrmse_by_feature_sd': nrmse,
            'nmae_by_feature_sd': nmae,
            'clinical_screen_low': bounds[0] if bounds else None,
            'clinical_screen_high': bounds[1] if bounds else None,
            'original_out_of_range': original_violations,
            'reconstructed_out_of_range': reconstructed_violations,
            'new_out_of_range_from_originally_valid': new_violations,
        })
    aggregate = {
        'observed_cells': count,
        'raw_rmse_observed': (total_sse / count) ** .5 if count else None,
        'raw_mae_observed': total_ae / count if count else None,
        'standardized_rmse_observed': (
            (total_scaled_sse / scaled_count) ** .5 if scaled_count else None),
        'median_per_feature_nrmse': (
            float(np.median([r['nrmse_by_feature_sd'] for r in feature_rows
                             if r['nrmse_by_feature_sd'] is not None]))
            if any(r['nrmse_by_feature_sd'] is not None for r in feature_rows) else None),
        'clinical_screen_observed_cells': screened_count,
        'clinical_screen_original_out_of_range': source_outside_total,
        'clinical_screen_reconstructed_out_of_range': reconstructed_outside_total,
        'clinical_screen_new_out_of_range': new_violation_total,
        'clinical_screen_new_violation_pct': 100 * new_violation_total / screened_count
            if screened_count else None,
        'exact_missingness_restored': True,
        'passthrough_values_restored_exactly': True,
    }
    return aggregate, feature_rows


def exact_preservation_audit(source: pd.DataFrame, recovered: pd.DataFrame,
                             passthrough: list[str], id_col: str,
                             time_col: str) -> list[dict]:
    """Audit columns that are never encoded, including structural/temporal fields.

    This checks exact values, null positions and per-patient baseline
    consistency. It does not attempt to repair or enforce clinical patterns.
    """
    audit = []
    for col in passthrough:
        values = source[col]
        rec_values = recovered[col]
        exact = bool(values.equals(rec_values))
        if not exact:
            raise ValueError(f'Exact-preservation audit failed for {col!r}')
        same_nulls = bool(values.isna().equals(rec_values.isna()))
        if not same_nulls:
            raise ValueError(f'Missingness changed for exact column {col!r}')
        row = {
            'column': col,
            'source_dtype': str(values.dtype),
            'observed_rows': int(values.notna().sum()),
            'missing_rows': int(values.isna().sum()),
            'identical_original_and_reconstructed': exact,
            'missingness_identical': same_nulls,
            'source_patients_with_multiple_observed_values': None,
            'reconstructed_patients_with_multiple_observed_values': None,
            'source_within_patient_decreasing_transitions': None,
            'reconstructed_within_patient_decreasing_transitions': None,
        }
        if col in ('Age', 'HospAdmTime'):
            src_counts = source.groupby(id_col, dropna=False)[col].nunique(dropna=True)
            rec_counts = recovered.groupby(id_col, dropna=False)[col].nunique(dropna=True)
            row['source_patients_with_multiple_observed_values'] = int((src_counts > 1).sum())
            row['reconstructed_patients_with_multiple_observed_values'] = int((rec_counts > 1).sum())
        if col == 'ICULOS':
            for label, df in [('source', source), ('reconstructed', recovered)]:
                ordered = df[[id_col, time_col, col]].sort_values(
                    [id_col, time_col], kind='mergesort'
                )
                diffs = ordered.groupby(id_col, dropna=False)[col].diff()
                row[f'{label}_within_patient_decreasing_transitions'] = int(
                    (diffs < 0).sum()
                )
        audit.append(row)
    return audit


def run_experiment(args: argparse.Namespace) -> Path:
    input_path = Path(args.dataset).expanduser().resolve()
    if not input_path.is_file() or input_path.suffix.lower() != '.csv':
        raise ValueError('Provide an existing Phase-3 selected_dataset.csv or raw .csv input')

    t0 = time.perf_counter()
    source = pd.read_csv(input_path, low_memory=False)
    read_seconds = time.perf_counter() - t0
    prep_tick = time.perf_counter()
    predictors, passthrough = choose_columns(source, args)
    X, mask, medians = fit_input(source, predictors)
    preprocessing_seconds = time.perf_counter() - prep_tick
    n, p = X.shape
    if n < 2:
        raise ValueError('At least two observations required')

    tag = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    output_dir = Path(args.output_dir).expanduser().resolve() / f'{input_path.stem}_{tag}'
    output_dir.mkdir(parents=True, exist_ok=False)
    source_bytes = input_path.stat().st_size
    source_sha = sha256_file(input_path)
    lossless = measure_lossless_baselines(
        input_path, source, output_dir, source_sha,
        args.lossless_formats, args.bandwidth_mbps, strict=args.strict_lossless,
    )
    pd.DataFrame(lossless).to_csv(output_dir / 'phase4_lossless_baselines.csv', index=False)
    verified_baselines = [row for row in lossless if row['status'] == 'verified']
    smallest_lossless = min(verified_baselines, key=lambda r: r['transmitted_total_bytes'])
    gzip_baseline = next((b for b in verified_baselines if b['method'] == 'gzip'), None)
    gzip_bytes = gzip_baseline['payload_bytes'] if gzip_baseline is not None else None
    gzip_transfer_bytes = (gzip_baseline['transmitted_total_bytes']
                           if gzip_baseline is not None else None)
    summary_rows, feature_rows, training_loss_rows = [], [], []
    exact_audit_rows = None

    print(f'Input : {input_path}\nRows  : {n:,}\nEncoded numerical predictors: {p}')
    print(f'Preserved exactly: {passthrough}')
    print(f'Exact clinical variables present: '
          f'{[c for c in args.exact_clinical_columns if c in passthrough]}')
    print(f'CSV   : {source_bytes:,} bytes; smallest verified lossless: '
          f"{smallest_lossless['method']} ({smallest_lossless['transmitted_total_bytes']:,} bytes)")
    print(f'Output: {output_dir}')
    for method in args.methods:
        for k in args.k:
            if k < 1 or k > min(n, p):
                print(f'SKIP {method} k={k}: k must be between 1 and {min(n,p)}')
                continue
            print(f'Running {method}, k={k} ...', flush=True)
            model = (PCACompressor(k, seed=args.seed) if method == 'pca' else
                     AutoencoderCompressor(k, hidden=(args.ae_hidden,),
                                          max_iter=args.ae_max_iter, seed=args.seed,
                                          tol=args.ae_tol, patience=args.ae_patience,
                                          backend=args.ae_backend, batch_size=args.ae_batch_size,
                                          cpu_threads=args.ae_cpu_threads,
                                          progress_interval=args.ae_progress_interval))
            times = TransferTiming()
            tick = time.perf_counter()
            model.fit(X)
            times.t_fit = time.perf_counter() - tick
            tick = time.perf_counter()
            Z = model.compress(X)
            times.t_compress = time.perf_counter() - tick

            filename = f'{method}_k{k}_transfer_payload.npz'
            bundle_path = output_dir / filename
            tick = time.perf_counter()
            payload_bytes = create_payload(
                bundle_path, method=method, k=k, Z=Z,
                decoder_arrays=model.decoder_arrays(), medians=medians,
                observed=mask, df=source, predictors=predictors,
                passthrough=passthrough, bundle_compression=args.bundle_compression,
            )
            checksum_path, payload_sha = create_checksum_sidecar(bundle_path)
            times.t_package = time.perf_counter() - tick
            checksum_bytes = checksum_path.stat().st_size
            transfer_bytes = payload_bytes + checksum_bytes
            times.t_transmit_simulated = simulated_transmission_time(
                transfer_bytes, args.bandwidth_mbps
            )

            # Mandatory receiver-side integrity gate, BEFORE opening NPZ.
            tick = time.perf_counter()
            verified_sha = verify_payload_checksum(bundle_path, checksum_path)
            times.t_verify_checksum = time.perf_counter() - tick
            if verified_sha != payload_sha:
                raise AssertionError('Verified checksum differs from sender checksum')

            tick = time.perf_counter()
            received_arrays = load_bundle_arrays(bundle_path)
            times.t_load = time.perf_counter() - tick
            tick = time.perf_counter()
            recovered = reconstruct_arrays(received_arrays)
            times.t_reconstruct = time.perf_counter() - tick
            tick = time.perf_counter()
            aggregate, per_feature = evaluate_reconstruction(
                source, recovered, predictors, passthrough, method, k
            )
            times.t_evaluate = time.perf_counter() - tick
            # Each model is required to recover all passthrough fields identically.
            # Audit once; evaluate_reconstruction above enforces it for every model.
            if exact_audit_rows is None:
                exact_audit_rows = exact_preservation_audit(
                    source, recovered, passthrough, args.id_column, args.time_column
                )
            if args.write_reconstructed:
                recovered.to_csv(output_dir / f'{method}_k{k}_reconstructed.csv', index=False)
            feature_rows.extend(per_feature)
            model_details = (
                {'pca_explained_variance_ratio': model.explained_variance}
                if method == 'pca' else model.training_diagnostics()
            )
            if method == 'autoencoder':
                training_loss_rows.extend({
                    'method': method, 'k': k, 'iteration': i + 1,
                    'training_loss': float(loss)
                } for i, loss in enumerate(model.model.loss_curve_))
                if model.convergence_warning:
                    print(f'  WARNING: AE k={k} reached {model.iterations} iterations '
                          'without optimizer stopping by tolerance. Treat result as preliminary.')
            summary_rows.append({
                'method': method, 'k': k, 'patients': source[args.id_column].nunique(),
                'rows': n, 'encoded_predictors': p,
                'passthrough_columns': len(passthrough),
                'exact_clinical_columns_present': ','.join(
                    c for c in args.exact_clinical_columns if c in passthrough),
                'input_csv_bytes': source_bytes, 'source_gzip6_bytes': gzip_bytes,
                'payload_bytes': payload_bytes,
                'checksum_bytes': checksum_bytes,
                'transmitted_total_bytes': transfer_bytes,
                'payload_pct_change_vs_csv': 100 * (payload_bytes / source_bytes - 1),
                'payload_pct_change_vs_gzip6': (100 * (payload_bytes / gzip_bytes - 1)
                    if gzip_bytes else None),
                'total_transfer_pct_change_vs_gzip6_with_checksum': (
                    100 * (transfer_bytes / gzip_transfer_bytes - 1) if gzip_transfer_bytes else None),
                'smallest_lossless_method': smallest_lossless['method'],
                'smallest_lossless_transfer_bytes': smallest_lossless['transmitted_total_bytes'],
                'total_transfer_pct_change_vs_smallest_lossless': (
                    100 * (transfer_bytes / smallest_lossless['transmitted_total_bytes'] - 1)),
                'payload_sha256': payload_sha,
                'payload_filename': filename,
                'checksum_filename': checksum_path.name,
                'receiver_checksum_verified': True,
                'receiver_checksum_verification_seconds': times.t_verify_checksum,
                'bundle_compression': args.bundle_compression,
                'bandwidth_mbps_assumed': args.bandwidth_mbps,
                'fit_seconds': times.t_fit,
                'encode_seconds': times.t_compress,
                'packaging_seconds': times.t_package,
                'transmission_seconds_SIMULATED': times.t_transmit_simulated,
                'receiver_loading_seconds': times.t_load,
                'receiver_reconstruction_seconds': times.t_reconstruct,
                'metric_evaluation_seconds_EXCLUDED_FROM_TOTAL': times.t_evaluate,
                'source_gzip6_seconds_SIMULATED': (
                    gzip_baseline['total_seconds_SIMULATED'] if gzip_baseline else None),
                'smallest_lossless_seconds_SIMULATED': smallest_lossless['total_seconds_SIMULATED'],
                'total_seconds_SIMULATED_excl_read_preprocess': times.t_total_simulated,
                'read_dataset_seconds': read_seconds,
                'prepare_numeric_input_seconds': preprocessing_seconds,
                'end_to_end_seconds_SIMULATED': (
                    read_seconds + preprocessing_seconds + times.t_total_simulated
                ),
                **model_details, **aggregate,
            })
            print(f'  Payload {payload_bytes:,} bytes; '
                  f'normalized RMSE {aggregate["standardized_rmse_observed"]}')

    if not summary_rows:
        raise ValueError('No valid (method, k) combinations. Check --k against feature count')
    pd.DataFrame(summary_rows).to_csv(output_dir / 'phase4_comparison.csv', index=False)
    pd.DataFrame(exact_audit_rows).to_csv(
        output_dir / 'phase4_exact_preservation_audit.csv', index=False)
    pd.DataFrame(feature_rows).to_csv(output_dir / 'phase4_per_feature_reconstruction.csv', index=False)
    pd.DataFrame(training_loss_rows, columns=['method', 'k', 'iteration', 'training_loss']).to_csv(
        output_dir / 'phase4_autoencoder_loss_curve.csv', index=False)
    metadata = {
        'phase': 'Phase 4 - PCA and nonlinear autoencoder (non-predictive)',
        'input_path': str(input_path), 'source_sha256': source_sha,
        'input_csv_bytes': source_bytes,
        'lossless_baselines': lossless,
        'smallest_verified_lossless': smallest_lossless['method'],
        'source_gzip6_bytes': gzip_bytes,
        'source_gzip6_total_transfer_bytes': gzip_transfer_bytes,
        'lossless_roundtrip_checks': 'gzip/zstd byte-exact SHA-256; parquet exact DataFrame values/order/missingness',
        'rows': n, 'patients': int(source[args.id_column].nunique()),
        'original_columns': list(source.columns),
        'encoded_predictors': predictors, 'preserved_exactly': passthrough,
        'exact_clinical_columns_requested': list(args.exact_clinical_columns),
        'exact_clinical_columns_present': [
            c for c in args.exact_clinical_columns if c in passthrough],
        'exact_preservation_audit': 'phase4_exact_preservation_audit.csv',
        'exact_clinical_policy': (
            'Age, HospAdmTime, ICULOS transferred without PCA/AE encoding; '
            'their source row values and missingness are retained exactly. '
            'Source data patterns are not repaired.'),
        'observed_cells': int(mask.sum()),
        'missing_cells': int(mask.size - mask.sum()),
        'imputation': 'median for model fitting; original missingness restored from bit mask',
        'scaling': 'StandardScaler fitted on complete provided dataset',
        'dataset_splitting': False,
        'bundle_compression': args.bundle_compression,
        'transmission': 'idealized bitrate calculation ONLY, not real SCP timing',
        'integrity': 'mandatory SHA-256 verification of every bundle before reconstruction; gzip integrity and exact source roundtrip verified',
        'checksum_authenticity_note': 'SHA-256 detects corruption; authenticate the sidecar (for example via a trusted channel) to protect against deliberate modification',
        'reconstruction_policy': 'always reconstruct and assess in memory; writing a reconstructed CSV is optional',
        'model_distribution': 'hospital-trained decoder transmitted in payload; receiver does NOT train',
        'privacy_mode': 'not implemented: mismatched decoders do not ensure accurate recovery or privacy',
        'input_feature_set_note': ('Reconstruction errors measure only columns present in this input CSV; '                                    'columns removed earlier in Phase 3 cannot be recovered.'),
        'temporal_note': ('PCA and the MLP autoencoder encode each hourly observation row independently; '                           'they do not explicitly model longitudinal temporal dynamics.'),
        'fiddle': 'excluded from main Phase 4 methods (feature extraction, not a compressor)',
        'clinical_screen_note': 'Screen ranges are study-specific, not clinical acceptability thresholds; values are flagged, never clipped',
        'read_csv_seconds': read_seconds,
        'prepare_numeric_input_seconds': preprocessing_seconds,
        'parameters': vars(args),
        'python': platform.python_version(),
        'numpy': np.__version__, 'pandas': pd.__version__,
        'run_timestamp_utc': tag,
    }
    (output_dir / 'phase4_metadata.json').write_text(json.dumps(metadata, indent=2, default=str))
    print('\nCOMPLETE. Main result:', output_dir / 'phase4_comparison.csv')
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('dataset', nargs='?', help='Raw or Phase-3 selected wide CSV')
    parser.add_argument('--output-dir', default='output/sepsis2019/phase4')
    parser.add_argument('--methods', nargs='+', choices=['pca', 'autoencoder'],
                        default=['pca', 'autoencoder'])
    parser.add_argument('--k', nargs='+', type=int, default=[2, 4, 8, 16])
    parser.add_argument('--ae-backend', choices=['cpu', 'gpu'], default='cpu')
    parser.add_argument('--ae-batch-size', type=int, default=256,
                        help='Training rows per optimizer step; larger batches change learning dynamics')
    parser.add_argument('--ae-cpu-threads', type=int, default=0, help='CPU BLAS thread limit; 0 uses library defaults')
    parser.add_argument('--ae-progress-interval', type=int, default=10, help='Log training progress every N epochs')
    parser.add_argument('--ae-hidden', type=int, default=32)
    parser.add_argument('--ae-max-iter', type=int, default=300,
                        help='Upper bound on autoencoder optimizer iterations; inspect convergence diagnostics')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--id-column', default='patient_id')
    parser.add_argument('--time-column', default='time')
    parser.add_argument('--outcome-column', default='SepsisLabel')
    parser.add_argument('--passthrough', nargs='*', default=['Gender', 'Unit1', 'Unit2'],
                        help='Additional clinical columns preserved losslessly instead of PCA/AE')
    parser.add_argument('--exact-clinical-columns', nargs='*',
                        default=list(DEFAULT_EXACT_CLINICAL_COLUMNS),
                        help='Exact patient-level/time-related fields excluded from PCA/AE '
                             '(default: Age HospAdmTime ICULOS; columns absent from '
                             'the current dataset are ignored)')
    parser.add_argument('--bundle-compression', choices=['none', 'deflate'], default='deflate')
    parser.add_argument('--lossless-formats', nargs='+', choices=['gzip', 'zstd', 'parquet'],
                        default=['gzip', 'zstd', 'parquet'],
                        help='Benchmark gzip-6, Zstandard-3, and Parquet+Zstandard lossless baselines')
    parser.add_argument('--strict-lossless', action='store_true',
                        help='Fail if a requested codec is unavailable or its roundtrip verification fails')
    parser.add_argument('--compare-with', nargs='+', type=Path, default=[],
                        help='Additional Phase-3 selected CSV files to benchmark under identical settings')
    parser.add_argument('--ae-tol', type=float, default=1e-4,
                        help='Sklearn optimizer minimum improvement tolerance')
    parser.add_argument('--ae-patience', type=int, default=20,
                        help='Iterations without optimizer improvement before stopping')
    parser.add_argument('--bandwidth-mbps', type=float, default=100.0)
    parser.add_argument('--write-reconstructed', action='store_true')
    parser.add_argument('--reconstruct-bundle', type=Path,
                        help='University-only mode: reconstruct a received NPZ payload')
    parser.add_argument('--reconstructed-output', type=Path,
                        help='Destination CSV for --reconstruct-bundle')
    parser.add_argument('--checksum-file', type=Path,
                        help='Trusted SHA-256 sidecar path (default: PAYLOAD.npz.sha256); verification is mandatory')
    args = parser.parse_args()
    if args.reconstruct_bundle:
        p = args.reconstruct_bundle
        try:
            digest = verify_payload_checksum(p, args.checksum_file)
        except (ValueError, FileNotFoundError) as exc:
            parser.error(str(exc))
        print(f'SHA-256 verified for {p.name}: {digest}')
        out = args.reconstructed_output or p.with_name(p.stem + '_reconstructed.csv')
        out.parent.mkdir(parents=True, exist_ok=True)
        df = reconstruct_bundle(p)
        df.to_csv(out, index=False)
        print(f'Reconstructed {len(df):,} rows and {df.shape[1]} columns -> {out}')
        return
    if not args.dataset:
        parser.error('Provide a CSV dataset, or use --reconstruct-bundle')
    if args.checksum_file is not None:
        parser.error('--checksum-file is used only with --reconstruct-bundle')
    if args.bandwidth_mbps <= 0 or args.ae_hidden <= 0 or args.ae_max_iter <= 0 or args.ae_patience <= 0 or args.ae_tol <= 0:
        parser.error('Bandwidth, AE hidden units, and AE maximum iterations must be positive')
    if any(k <= 0 for k in args.k):
        parser.error('Every --k must be positive')
    if args.ae_batch_size < 1 or args.ae_cpu_threads < 0 or args.ae_progress_interval < 1:
        parser.error('AE batch size/progress interval must be positive; CPU threads must be nonnegative')
    if args.ae_backend == 'gpu' and 'autoencoder' in args.methods:
        cuda_module()  # Reject unavailable acceleration before running the benchmarks.
    datasets = [args.dataset] + [str(x) for x in args.compare_with]
    if len({str(Path(x).resolve()) for x in datasets}) != len(datasets):
        parser.error('Repeated input files in --compare-with')
    gathered = []
    for input_file in datasets:
        run_args = argparse.Namespace(**vars(args))
        run_args.dataset = input_file
        output_path = run_experiment(run_args)
        frame = pd.read_csv(output_path / 'phase4_comparison.csv')
        frame.insert(0, 'input_dataset', Path(input_file).name)
        frame.insert(1, 'input_sha256', sha256_file(Path(input_file)))
        frame.insert(2, 'run_output_dir', str(output_path))
        gathered.append(frame)
    if len(gathered) > 1:
        root = Path(args.output_dir).expanduser().resolve()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
        all_path = root / f'phase4_across_datasets_{stamp}.csv'
        pd.concat(gathered, ignore_index=True).to_csv(all_path, index=False)
        print('Cross-dataset comparison:', all_path)
        print('IMPORTANT: RMSE across datasets with different feature sets is not directly comparable.')


if __name__ == '__main__':
    main()

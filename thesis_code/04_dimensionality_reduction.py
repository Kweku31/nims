"""04_dimensionality_reduction.py — Phase 4 (hospital -> university).

Evaluate PCA, a nonlinear autoencoder, and optional real FIDDLE on *wide*
clinical CSV data.  This is a data-transfer / reconstruction experiment,
not a sepsis-prediction experiment: no train/validation/test patient split.

At the hospital: median-impute *only for fitting*, standardize, fit a model,
encode clinical predictors, and serialize one portable NPZ payload containing:
  - float32 reduced coordinates, Z
  - fitted inverse/decoder parameters (the SAME learned model)
  - a bit-packed mask to restore which clinical entries were originally missing
  - unmodified patient IDs, time, label, and configured passthrough fields
  - column names/order and a small manifest.

At the university: load the actual payload, invert using the supplied decoder,
restore the original missingness mask, and reorder the columns. Reconstruction
is lossy for measured clinical values, but missingness and structural values
are retained exactly.  The receiver never independently fits a new model.

Actual on-disk file size, NOT Z.nbytes plus an estimated model size, is used
for transfer-size calculations. --bandwidth-mbps gives only an IDEALIZED
transmission time; use the Phase-2/6 SCP benchmark for observed network times.

FIDDLE is available with --with-fiddle (official FIDDLE.run in local repo).
FIDDLE reconstruction metrics refer to ENGINEERED FIDDLE FEATURES, not the
original clinical observations; reported transfer size is not equal utility.

Dependencies: numpy, pandas, scipy (sklearn dependency), scikit-learn.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
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
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler


@dataclass
class TransferTiming:
    t_fit: float = 0.0
    t_compress: float = 0.0
    t_package: float = 0.0
    t_transmit_simulated: float = 0.0
    t_load: float = 0.0
    t_reconstruct: float = 0.0
    t_evaluate: float = 0.0

    @property
    def t_total_simulated(self) -> float:
        return (self.t_fit + self.t_compress + self.t_package
                + self.t_transmit_simulated + self.t_load + self.t_reconstruct)


def simulated_transmission_time(payload_bytes: int, bandwidth_mbps: float) -> float:
    """Ideal payload-serialization time; ignores protocol/SSH/network overhead."""
    return (payload_bytes * 8) / (bandwidth_mbps * 1_000_000)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def elapsed_gzip_baseline(source: Path, target: Path) -> tuple[int, float]:
    t0 = time.perf_counter()
    with source.open('rb') as fin, gzip.open(target, 'wb', compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
    return target.stat().st_size, time.perf_counter() - t0


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
                 max_iter: int = 80, seed: int = 42):
        self.k = k
        self.hidden = hidden
        self.bottleneck_layer = len(hidden)
        self.scaler = StandardScaler()
        # MLPRegressor is trained to reconstruct its input (unsupervised).
        # early_stopping=False means it creates no internal validation split.
        self.model = MLPRegressor(
            hidden_layer_sizes=(*hidden, k, *reversed(hidden)),
            activation='relu', solver='adam', batch_size=256,
            early_stopping=False, max_iter=max_iter,
            random_state=seed, tol=1e-4, n_iter_no_change=12,
        )

    def fit(self, X: np.ndarray) -> 'AutoencoderCompressor':
        scaled = self.scaler.fit_transform(X)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='Stochastic Optimizer:')
            self.model.fit(scaled, scaled)
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


def choose_columns(df: pd.DataFrame, args: argparse.Namespace) -> tuple[list[str], list[str]]:
    if args.id_column not in df or args.time_column not in df:
        raise ValueError(f'Required columns {args.id_column!r} and/or {args.time_column!r} not found')
    if args.outcome_column not in df:
        raise ValueError(f'Required column {args.outcome_column!r} not found')
    protected = {args.id_column, args.time_column, args.outcome_column}
    protected.update(x for x in args.passthrough if x in df.columns)
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
        raise ValueError('Missingness mask changed during hospital -> university reconstruction')

    per_feature = []
    total_sse, total_ae, count = 0.0, 0.0, 0
    total_scaled_sse, scaled_count = 0.0, 0
    for j, col in enumerate(predictors):
        use = observed[:, j]
        n_obs = int(use.sum())
        if n_obs:
            dif = recovered[use, j] - original[use, j]
            mae = float(np.mean(np.abs(dif)))
            rmse = float(np.sqrt(np.mean(dif ** 2)))
            sd = float(np.std(original[use, j]))
            nrmse = (rmse / sd) if sd > 1e-12 else None
            total_sse += float(np.sum(dif ** 2))
            total_ae += float(np.sum(np.abs(dif)))
            count += n_obs
            if sd > 1e-12:
                total_scaled_sse += float(np.sum((dif / sd) ** 2))
                scaled_count += n_obs
        else:
            mae = rmse = nrmse = None
        per_feature.append({
            'method': method, 'k': k, 'feature': col, 'observed_rows': n_obs,
            'missing_pct': (1 - n_obs / len(source)) * 100,
            'mae': mae, 'rmse': rmse, 'nrmse_by_feature_sd': nrmse,
        })
    aggregate = {
        'observed_cells': count,
        'raw_rmse_observed': (total_sse / count) ** .5 if count else None,
        'raw_mae_observed': total_ae / count if count else None,
        'standardized_rmse_observed': (
            (total_scaled_sse / scaled_count) ** .5 if scaled_count else None
        ),
        'exact_missingness_restored': True,
        'passthrough_values_restored_exactly': True,
    }
    return aggregate, per_feature


def run_experiment(args: argparse.Namespace) -> None:
    input_path = Path(args.dataset).expanduser().resolve()
    if not input_path.is_file() or input_path.suffix.lower() != '.csv':
        raise ValueError('Provide an existing Phase-3 selected_dataset.csv or raw .csv input')

    t0 = time.perf_counter()
    source = pd.read_csv(input_path, low_memory=False)
    read_seconds = time.perf_counter() - t0
    original_input_path = input_path
    original_source_bytes = input_path.stat().st_size
    if args.with_fiddle:
        time_values = pd.to_numeric(source[args.time_column], errors='coerce')
        if time_values.isna().any():
            raise ValueError('FIDDLE requires numeric relative-hour values in time column')
        # Common [0, T) horizon across direct and FIDDLE branches.
        keep = (time_values >= 0) & (time_values < args.fiddle_T)
        source = source.loc[keep].reset_index(drop=True)
        if source.empty:
            raise ValueError('No data in the matched FIDDLE time horizon')
        tag = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
        matched_dir = Path(args.output_dir).expanduser().resolve() / f'{input_path.stem}_{tag}'
        matched_dir.mkdir(parents=True, exist_ok=False)
        window_path = matched_dir / 'matched_observation_window.csv'
        source.to_csv(window_path, index=False)
        input_path = window_path
    predictors, passthrough = choose_columns(source, args)
    X, mask, medians = fit_input(source, predictors)
    n, p = X.shape
    if n < 2:
        raise ValueError('At least two observations required')

    if args.with_fiddle:
        output_dir = matched_dir
    else:
        tag = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
        output_dir = Path(args.output_dir).expanduser().resolve() / f'{input_path.stem}_{tag}'
        output_dir.mkdir(parents=True, exist_ok=False)
    gzip_path = output_dir / 'source_csv_gzip6.csv.gz'
    gzip_bytes, gzip_seconds = elapsed_gzip_baseline(input_path, gzip_path)
    tick = time.perf_counter()
    with gzip.open(gzip_path, 'rb') as baseline_in:
        while baseline_in.read(1024 * 1024):
            pass
    gzip_receiver_decompression_seconds = time.perf_counter() - tick
    source_bytes = input_path.stat().st_size
    source_sha = sha256_file(input_path)
    summary_rows, feature_rows = [], []
    # Explicit lossless baselines belong in the same comparison table.
    for method, nbytes, packaging_seconds, receiver_seconds in [
        ('raw_csv', source_bytes, 0.0, 0.0),
        ('gzip6', gzip_bytes, gzip_seconds, gzip_receiver_decompression_seconds),
    ]:
        ideal_seconds = simulated_transmission_time(nbytes, args.bandwidth_mbps)
        summary_rows.append({
            'method': method,
            'representation': 'original_clinical_rows_lossless',
            'fidelity_reference': 'exact original clinical CSV bytes',
            'original_clinical_rows_reconstructable': True,
            'compression_lossy': False,
            'status': 'completed',
            'patients': int(source[args.id_column].nunique()),
            'rows': len(source),
            'input_csv_bytes': source_bytes,
            'source_gzip6_bytes': gzip_bytes,
            'payload_bytes': nbytes,
            'payload_pct_change_vs_csv': 100 * (nbytes / source_bytes - 1),
            'payload_pct_change_vs_gzip6': 100 * (nbytes / gzip_bytes - 1),
            'payload_filename': (str(input_path) if method == 'raw_csv' else gzip_path.name),
            'payload_sha256': (source_sha if method == 'raw_csv' else sha256_file(gzip_path)),
            'packaging_seconds': packaging_seconds,
            'transmission_seconds_SIMULATED': ideal_seconds,
            'receiver_reconstruction_seconds': receiver_seconds,
            'total_seconds_SIMULATED': packaging_seconds + ideal_seconds + receiver_seconds,
            'exact_missingness_restored': True,
            'passthrough_values_restored_exactly': True,
        })

    print(f'Input : {input_path}\nRows  : {n:,}\nEncoded numerical predictors: {p}')
    print(f'Preserved exactly: {passthrough}')
    print(f'CSV   : {source_bytes:,} bytes; gzip-6: {gzip_bytes:,} bytes')
    print(f'Output: {output_dir}')
    for method in ([] if args.skip_direct else args.methods):
        for k in args.k:
            if k < 1 or k > min(n, p):
                print(f'SKIP {method} k={k}: k must be between 1 and {min(n,p)}')
                continue
            print(f'Running {method}, k={k} ...', flush=True)
            model = (PCACompressor(k, seed=args.seed) if method == 'pca' else
                     AutoencoderCompressor(k, hidden=(args.ae_hidden,),
                                          max_iter=args.ae_max_iter, seed=args.seed))
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
            times.t_package = time.perf_counter() - tick
            payload_sha = sha256_file(bundle_path)
            times.t_transmit_simulated = simulated_transmission_time(
                payload_bytes, args.bandwidth_mbps
            )

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
            if args.write_reconstructed:
                recovered.to_csv(output_dir / f'{method}_k{k}_reconstructed.csv', index=False)
            feature_rows.extend(per_feature)
            model_details = (
                {'pca_explained_variance_ratio': model.explained_variance}
                if method == 'pca' else {'autoencoder_iterations': model.iterations, 'autoencoder_training_loss': model.loss}
            )
            summary_rows.append({
                'method': method, 'k': k,
                'representation': 'original_clinical_numeric_features',
                'fidelity_reference': 'observed original clinical values',
                'original_clinical_rows_reconstructable': True,
                'status': 'completed',
                'compression_lossy': True,
                'patients': source[args.id_column].nunique(),
                'rows': n, 'encoded_predictors': p,
                'passthrough_columns': len(passthrough),
                'input_csv_bytes': source_bytes, 'source_gzip6_bytes': gzip_bytes,
                'payload_bytes': payload_bytes,
                'payload_pct_change_vs_csv': 100 * (payload_bytes / source_bytes - 1),
                'payload_pct_change_vs_gzip6': 100 * (payload_bytes / gzip_bytes - 1),
                'payload_sha256': payload_sha,
                'payload_filename': filename,
                'bundle_compression': args.bundle_compression,
                'bandwidth_mbps_assumed': args.bandwidth_mbps,
                'fit_seconds': times.t_fit,
                'encode_seconds': times.t_compress,
                'packaging_seconds': times.t_package,
                'transmission_seconds_SIMULATED': times.t_transmit_simulated,
                'receiver_loading_seconds': times.t_load,
                'receiver_reconstruction_seconds': times.t_reconstruct,
                'metric_evaluation_seconds_EXCLUDED_FROM_TOTAL': times.t_evaluate,
                'source_gzip6_seconds_SIMULATED': (gzip_seconds +
                    simulated_transmission_time(gzip_bytes, args.bandwidth_mbps)
                    + gzip_receiver_decompression_seconds),
                'total_seconds_SIMULATED': times.t_total_simulated,
                **model_details, **aggregate,
            })
            print(f'  Payload {payload_bytes:,} bytes; '
                  f'normalized RMSE {aggregate["standardized_rmse_observed"]}')

    if args.with_fiddle:
        fiddle_rows = run_fiddle_experiments(
            args, source, output_dir, source_bytes, gzip_bytes
        )
        summary_rows.extend(fiddle_rows)
    if not summary_rows:
        raise ValueError('No completed experiments. Check methods, k and FIDDLE options')
    for row in summary_rows:
        row['original_input_filename'] = original_input_path.name
        row['original_input_sha256'] = sha256_file(original_input_path)
        row['comparison_window_hours'] = args.fiddle_T if args.with_fiddle else None
    pd.DataFrame(summary_rows).to_csv(output_dir / 'phase4_comparison.csv', index=False)
    pd.DataFrame(feature_rows).to_csv(output_dir / 'phase4_per_feature_reconstruction.csv', index=False)
    metadata = {
        'phase': 'Phase 4 - PCA, nonlinear autoencoder and optional FIDDLE (non-predictive)',
        'input_path': str(input_path), 'source_sha256': source_sha,
        'input_csv_bytes': source_bytes, 'source_gzip6_bytes': gzip_bytes,
        'gzip6_packaging_seconds': gzip_seconds,
        'gzip6_receiver_decompression_seconds': gzip_receiver_decompression_seconds,
        'rows': n, 'patients': int(source[args.id_column].nunique()),
        'original_columns': list(source.columns),
        'encoded_predictors': predictors, 'preserved_exactly': passthrough,
        'observed_cells': int(mask.sum()),
        'missing_cells': int(mask.size - mask.sum()),
        'imputation': 'median for model fitting; original missingness restored from bit mask',
        'scaling': 'StandardScaler fitted on complete provided dataset',
        'dataset_splitting': False,
        'bundle_compression': args.bundle_compression,
        'transmission': 'idealized bitrate calculation ONLY, not real SCP timing',
        'model_distribution': 'hospital-trained decoder transmitted in payload; receiver does NOT train',
        'privacy_mode': 'not implemented: mismatched decoders do not ensure accurate recovery or privacy',
        'fiddle': ('official FIDDLE.run executed/reused; FIDDLE feature space is not original raw data' if args.with_fiddle else 'not run'),
        'original_input_file_bytes': original_source_bytes,
        'original_input_path': str(original_input_path),
        'matched_window_csv': str(input_path) if args.with_fiddle else None,
        'read_csv_seconds': read_seconds,
        'parameters': vars(args),
        'python': platform.python_version(),
        'numpy': np.__version__, 'pandas': pd.__version__,
        'run_timestamp_utc': tag,
    }
    (output_dir / 'phase4_metadata.json').write_text(json.dumps(metadata, indent=2))
    print('\nCOMPLETE. Main result:', output_dir / 'phase4_comparison.csv')


# ===========================================================================
# FIDDLE branch -- original implementation (Tang et al., 2020), not emulated
# ===========================================================================


def _find_fiddle_file(out: Path, name: str) -> Path:
    for candidate in (out / name, out / (name[:1].lower() + name[1:])):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f'Missing FIDDLE artifact {name} in {out}')


def _sparse_coo_npz(path: Path) -> tuple[tuple[int, ...], np.ndarray, np.ndarray]:
    """Read standard pydata/sparse COO .npz without converting it to dense.

    FIDDLE normally writes sparse.save_npz archives; the COO on-disk schema
    consists of coords, data, shape, and fill_value. Only zero fill is valid
    for our temporal/volume experiment.
    """
    with np.load(path, allow_pickle=False) as a:
        required = {'coords', 'data', 'shape'}
        if not required.issubset(a.files):
            raise ValueError(f'{path} is not a pydata/sparse COO archive: {a.files}')
        shape = tuple(int(x) for x in a['shape'].tolist())
        coords = np.asarray(a['coords'], dtype=np.int64)
        data = np.asarray(a['data'])
        if 'fill_value' in a.files:
            fill = np.asarray(a['fill_value']).item()
            if fill != 0:
                raise ValueError(f'{path}: nonzero sparse fill value not supported')
    if coords.shape != (len(shape), data.size):
        raise ValueError(f'Invalid coordinates in sparse file {path}')
    return shape, coords, data


def _sparse_to_csr_2d(path: Path):
    from scipy.sparse import coo_matrix
    shape, coords, data = _sparse_coo_npz(path)
    if len(shape) != 2:
        raise ValueError(f'Expected 2D static output, got {shape}')
    return coo_matrix((data, (coords[0], coords[1])), shape=shape).tocsr()


def _sparse_dynamic_to_csr(path: Path):
    from scipy.sparse import coo_matrix
    shape, coords, data = _sparse_coo_npz(path)
    if len(shape) != 3:
        raise ValueError(f'Expected 3D dynamic output, got {shape}')
    N, L, D = shape
    return coo_matrix((data, (coords[0] * L + coords[1], coords[2])),
                      shape=(N * L, D)).tocsr(), shape


def _write_fiddle_input(window_df: pd.DataFrame, args: argparse.Namespace, out: Path) -> tuple[Path, Path, float, list[str]]:
    """Write actual FIDDLE ID/t/name/value input, excluding labels & IDs.

    Time-invariant features are emitted once per patient (t is blank). They
    must not change within a patient; changing values stay dynamic instead.
    This uses row chunks for the otherwise enormous long-format event table.
    """
    tick = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    events = out / 'fiddle_events.csv'
    population = out / 'fiddle_population.csv'
    ids = sorted(window_df[args.id_column].astype(str).unique().tolist())
    pd.DataFrame({'ID': ids}).to_csv(population, index=False)
    protected = {args.id_column, args.time_column, args.outcome_column}
    eligible = [c for c in window_df.columns if c not in protected]
    static = []
    for c in args.fiddle_static:
        if c not in eligible:
            continue
        # A "static" field that varies within a stay must remain temporal.
        if (window_df.groupby(args.id_column, sort=False)[c]
                .nunique(dropna=True).le(1).all()):
            static.append(c)
        else:
            print(f'FIDDLE: {c} changes within a patient; treating it as dynamic.')
    dynamic = [c for c in eligible if c not in set(static)]
    wrote = False
    if static:
        sub = window_df.groupby(args.id_column, sort=False)[static].first().reset_index()
        long = sub.melt(id_vars=[args.id_column], value_vars=static,
                        var_name='variable_name', value_name='variable_value')
        long = long.dropna(subset=['variable_value'])
        long['t'] = np.nan
        long = long.rename(columns={args.id_column: 'ID'})
        long['ID'] = long['ID'].astype(str)
        long[['ID', 't', 'variable_name', 'variable_value']].to_csv(events, index=False)
        wrote = True
    for start in range(0, len(window_df), args.fiddle_event_chunk_rows):
        chunk = window_df.iloc[start:start + args.fiddle_event_chunk_rows]
        long = chunk[[args.id_column, args.time_column, *dynamic]].melt(
            id_vars=[args.id_column, args.time_column], value_vars=dynamic,
            var_name='variable_name', value_name='variable_value'
        ).dropna(subset=['variable_value'])
        if long.empty:
            continue
        long.rename(columns={args.id_column: 'ID', args.time_column: 't'}, inplace=True)
        long['ID'] = long['ID'].astype(str)
        long[['ID', 't', 'variable_name', 'variable_value']].to_csv(
            events, index=False, header=not wrote, mode='a' if wrote else 'w'
        )
        wrote = True
    if not wrote:
        raise ValueError('No observed clinical values available for FIDDLE')
    return events, population, time.perf_counter() - tick, static


def _run_official_fiddle(args: argparse.Namespace, events: Path, population: Path,
                         out: Path, dt: float) -> float:
    import subprocess
    import sys
    repo = Path(args.fiddle_repo).expanduser().resolve()
    if not (repo / 'FIDDLE' / 'run.py').is_file():
        raise FileNotFoundError(
            f'Cannot find FIDDLE/run.py under {repo}. '
            'Clone https://github.com/MLD3/FIDDLE and use --fiddle-repo PATH.'
        )
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, '-m', 'FIDDLE.run',
           f'--data_fname={events}', f'--population_fname={population}',
           f'--output_dir={out}', f'--T={args.fiddle_T}', f'--dt={dt}',
           f'--theta_1={args.fiddle_theta_1}', f'--theta_2={args.fiddle_theta_2}',
           f'--theta_freq={args.fiddle_theta_freq}', '--stats_functions',
           *args.fiddle_stats]
    print('Running official FIDDLE:', ' '.join(cmd), flush=True)
    t0 = time.perf_counter()
    with (out / 'fiddle_stdout_stderr.log').open('w') as log:
        try:
            subprocess.run(cmd, cwd=repo, check=True, stdout=log,
                           stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            raise RuntimeError(
                f'FIDDLE failed with exit code {err.returncode}; see '
                f'{out / "fiddle_stdout_stderr.log"}'
            ) from err
    return time.perf_counter() - t0


def _fiddle_sidecar(window_df: pd.DataFrame, args: argparse.Namespace,
                    dt: float, out: Path) -> Path:
    """Store patient order and original row/time/outcome EXACTLY.

    Does not claim original clinical measurements can be recovered from FIDDLE.
    """
    ids = sorted(window_df[args.id_column].astype(str).unique().tolist())
    offsets = window_df[args.id_column].astype(str).map({v: i for i, v in enumerate(ids)})
    out.mkdir(parents=True, exist_ok=True)
    out_path = out / 'fiddle_structural_sidecar.npz'
    np.savez_compressed(
        out_path,
        patient_ids=np.asarray(ids, dtype=np.str_),
        row_patient_index=offsets.to_numpy(dtype=np.int32),
        row_times=window_df[args.time_column].to_numpy(),
        row_outcome=window_df[args.outcome_column].to_numpy(),
        original_columns=np.asarray(window_df.columns, dtype=np.str_),
        horizon_hours=np.asarray(args.fiddle_T),
        time_bin_hours=np.asarray(dt),
    )
    return out_path


def _fiddle_common_files(fiddle_dir: Path, sidecar: Path) -> dict[str, Path]:
    static = _find_fiddle_file(fiddle_dir, 'S.npz')
    dynamic = _find_fiddle_file(fiddle_dir, 'X.npz')
    result = {'S.npz': static, 'X.npz': dynamic, 'structural_sidecar.npz': sidecar}
    for name in ('S.feature_names.json', 'X.feature_names.json'):
        result[name] = _find_fiddle_file(fiddle_dir, name)
    # Filenames for optional alias/dictionary metadata vary between versions.
    for f in fiddle_dir.iterdir():
        if f.suffix == '.json' and f.name not in result:
            result[f.name] = f
    return result


def _zip_payload(dest: Path, files: dict[str, Path]) -> int:
    import zipfile
    with zipfile.ZipFile(dest, mode='w', compression=zipfile.ZIP_STORED) as z:
        for alias, file in files.items():
            z.write(file, arcname=alias)
    return dest.stat().st_size


def _fiddle_encoder_bundle(path: Path, model, X_rows: np.ndarray,
                           N: int, L: int, k: int, method: str) -> int:
    """Package encoded FIDDLE dynamics and its exact *feature-space* decoder."""
    encoded = model.compress(X_rows).reshape(N, L, k)
    arrays = {'Z': np.asarray(encoded, dtype=np.float32),
              'representation': np.asarray('fiddle_feature_space'),
              'method': np.asarray(method), 'N': np.asarray(N),
              'L': np.asarray(L), 'D': np.asarray(X_rows.shape[1])}
    arrays.update(model.decoder_arrays())
    np.savez_compressed(path, **arrays)
    return path.stat().st_size


def _decode_fiddle_feature_payload(arrays: dict[str, np.ndarray]) -> np.ndarray:
    """University: reconstruct engineered dynamic features without fitting anything.

    Result is (N,L,D), not the original clinical measurements.
    """
    N = int(arrays['N'])
    L = int(arrays['L'])
    D = int(arrays['D'])
    method = str(arrays['method'].item())
    Z = np.asarray(arrays['Z'], dtype=np.float32)
    if Z.shape[:2] != (N, L):
        raise ValueError('Encoded FIDDLE tensor shape does not match metadata')
    a = Z.reshape(N * L, -1)
    if method == 'pca':
        a = a @ arrays['pca_components'] + arrays['pca_mean']
    elif method == 'autoencoder':
        n_layers = int(arrays['decoder_layers'])
        for j in range(n_layers):
            a = a @ arrays[f'decoder_w_{j}'] + arrays[f'decoder_b_{j}']
            if j < n_layers - 1:
                a = np.maximum(0, a)
    else:
        raise ValueError(f'Unsupported FIDDLE encoder method {method}')
    X_hat = a * arrays['scaler_scale'] + arrays['scaler_mean']
    if X_hat.shape != (N * L, D):
        raise ValueError('Reconstructed engineered feature dimensions are inconsistent')
    return np.asarray(X_hat.reshape(N, L, D), dtype=np.float32)


def receive_fiddle_archive(archive: Path, destination: Path,
                           max_dense_mib: float) -> None:
    """Unpack official FIDDLE artifacts at university; decode if necessary.

    FIDDLE-only outputs remain sparse. For FIDDLE+PCA/AE, reconstructed dynamic
    features are stored in receiver_X_reconstructed.npz, bounded by a RAM cap.
    Never claims to reconstruct original hourly clinical values.
    """
    import zipfile
    archive = Path(archive).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        invalid = [name for name in bundle.namelist()
                   if name.startswith('/') or '..' in Path(name).parts or '\\' in name]
        if invalid:
            raise ValueError(f'Unsafe ZIP member names: {invalid}')
        if bundle.testzip() is not None:
            raise ValueError('Corrupt FIDDLE ZIP payload')
        bundle.extractall(destination)
    encoded = destination / 'encoded_dynamic_features.npz'
    if encoded.is_file():
        with np.load(encoded, allow_pickle=False) as a:
            N, L, D = (int(a[key]) for key in ('N', 'L', 'D'))
            size_mib = N * L * D * 4 / 1024**2
            if size_mib > max_dense_mib:
                raise MemoryError(f'Reconstruction requires at least {size_mib:.1f} MiB '
                                  f'for output, cap is {max_dense_mib:.1f} MiB')
            restored = _decode_fiddle_feature_payload(
                {key: np.asarray(a[key]).copy() for key in a.files}
            )
        out = destination / 'receiver_X_reconstructed.npz'
        np.savez_compressed(out, X=restored)
        print(f'FIDDLE feature-space reconstruction: {restored.shape} -> {out}')
    elif (destination / 'X.npz').is_file():
        print(f'FIDDLE-only sparse feature archive extracted to {destination}')
    else:
        raise ValueError('ZIP contains neither FIDDLE X.npz nor an encoded dynamic tensor')
    print('These outputs are engineered FIDDLE features, NOT original clinical measurements.')


def _verify_fiddle_encoded(bundle: Path, X_orig: np.ndarray,
                           N: int, L: int, D: int, method: str) -> dict:
    """Receiver reconstruction from DISK; comparisons are in FIDDLE space."""
    with np.load(bundle, allow_pickle=False) as data:
        arrays = {key: np.asarray(data[key]).copy() for key in data.files}
    recovered = _decode_fiddle_feature_payload(arrays).reshape(N * L, D)
    if recovered.shape != (N * L, D):
        raise ValueError('Receiver failed to reconstruct FIDDLE feature shape')
    diff = recovered - X_orig
    nonzero = X_orig != 0
    return {
        'fiddle_feature_rmse_all': float(np.sqrt(np.mean(diff ** 2))),
        'fiddle_feature_mae_all': float(np.mean(np.abs(diff))),
        'fiddle_feature_rmse_nonzero': (
            float(np.sqrt(np.mean(diff[nonzero] ** 2))) if nonzero.any() else None
        ),
    }


def run_fiddle_experiments(args: argparse.Namespace, window_df: pd.DataFrame,
                           run_dir: Path, base_csv_bytes: int,
                           base_gzip_bytes: int) -> list[dict]:
    """FIDDLE alone and optional FIDDLE+PCA/AE across time-bin widths.

    PCA/AE compress time-BIN feature vectors (N*L, D) not raw patient/hour
    measurements. The static FIDDLE matrix remains lossless and is sent with
    the decoder plus sidecar. A size ratio vs original CSV is descriptive,
    NOT an equal-utility comparison; reconstructions remain in feature space.
    """
    root = run_dir / 'fiddle'
    root.mkdir(exist_ok=True)
    if args.fiddle_mode == 'run':
        event_dir = root / 'input'
        events, population, preparation_seconds, static_columns = _write_fiddle_input(
            window_df, args, event_dir
        )
    else:
        events = population = None
        preparation_seconds = 0.0
        static_columns = []
    rows = []
    for dt in args.fiddle_dt:
        label = f'dt_{str(dt).replace(".", "p")}'
        fiddle_dir = ((root / label) if args.fiddle_mode == 'run'
                      else Path(args.fiddle_existing_root).expanduser().resolve() / label)
        fiddle_seconds = (_run_official_fiddle(args, events, population, fiddle_dir, dt)
                          if args.fiddle_mode == 'run' else 0.0)
        static_path = _find_fiddle_file(fiddle_dir, 'S.npz')
        dynamic_path = _find_fiddle_file(fiddle_dir, 'X.npz')
        S_shape, _, _ = _sparse_coo_npz(static_path)
        X_sparse, (N, L, D) = _sparse_dynamic_to_csr(dynamic_path)
        if N != int(window_df[args.id_column].nunique()) or S_shape[0] != N:
            raise ValueError('FIDDLE output population size differs from input cohort')
        expected_L = int(np.floor(args.fiddle_T / dt))
        if L != expected_L:
            raise ValueError(f'FIDDLE L={L} differs from floor(T/dt)={expected_L}')
        sidecar = _fiddle_sidecar(window_df, args, dt, root / label)
        common_files = _fiddle_common_files(fiddle_dir, sidecar)
        sidecar_bytes = sidecar.stat().st_size
        artifacts_bytes = sum(f.stat().st_size for f in common_files.values())
        fiddle_payload = (root / label / 'fiddle_only_transfer.zip')
        fiddle_bytes = _zip_payload(fiddle_payload, common_files)
        base = dict(
            representation='fiddle_temporal_features', input_csv_bytes=base_csv_bytes,
            source_gzip6_bytes=base_gzip_bytes, patients=N,
            source_hourly_rows=len(window_df), fiddle_T_hours=args.fiddle_T,
            dt_hours=dt, time_bins=L, fiddle_static_features=S_shape[1],
            fiddle_dynamic_features_per_bin=D,
            fiddle_dynamic_nnz=int(X_sparse.nnz),
            fiddle_extraction_seconds=fiddle_seconds,
            fiddle_input_preparation_seconds=preparation_seconds,
            fiddle_mode=args.fiddle_mode,
            status='completed',
            compression_lossy=True,
            fidelity_reference='FIDDLE features, NOT original hourly values',
            original_clinical_rows_reconstructable=False,
            transmission_seconds_SIMULATED=None,
            input_population_files_NOT_transferred=True,
            note='FIDDLE pre-/post-filters and discretizes; not lossless original-data transfer',
        )
        rows.append({**base, 'method': 'fiddle', 'k': None,
                     'payload_filename': str(fiddle_payload.relative_to(run_dir)),
                     'payload_bytes': fiddle_bytes, 'payload_sha256': sha256_file(fiddle_payload),
                     'payload_pct_change_vs_csv': 100 * (fiddle_bytes / base_csv_bytes - 1),
                     'payload_pct_change_vs_gzip6': 100 * (fiddle_bytes / base_gzip_bytes - 1),
                     'transmission_seconds_SIMULATED': simulated_transmission_time(
                         fiddle_bytes, args.bandwidth_mbps),
                     'total_seconds_SIMULATED': preparation_seconds + fiddle_seconds
                     + simulated_transmission_time(fiddle_bytes, args.bandwidth_mbps),
                     'fiddle_feature_rmse_all': None,
                     'fiddle_feature_mae_all': None,
                     'fiddle_feature_rmse_nonzero': None,
                     'reconstruction_metric_status': 'not_applicable_fiddle_only',
                     'fiddle_payload_files': len(common_files),
                     'fiddle_input_files_bytes_NOT_TRANSFERRED': (
                         events.stat().st_size + population.stat().st_size
                         if events is not None else None),
                     'fiddle_output_files_bytes_unbundled': artifacts_bytes,
                     'structural_sidecar_bytes': sidecar_bytes})
        if not args.fiddle_reducers:
            continue
        # Dense FIDDLE representations can be gigantic (N*L*D). Explicitly
        # guard memory; do NOT silently allocate hundreds of GB for 20k patients.
        estimated_mib = (N * L * D * 4) / (1024 * 1024)
        if estimated_mib > args.max_fiddle_dense_mib:
            print(f'  SKIP FIDDLE+PCA/AE dt={dt}: dense FIDDLE matrix would need '
                  f'{estimated_mib:.1f} MiB > {args.max_fiddle_dense_mib:.1f} MiB. '
                  'Increase --max-fiddle-dense-mib only if sufficient RAM.')
            for method in args.fiddle_reducers:
                for k in args.k:
                    rows.append({**base, 'method': f'fiddle+{method}', 'k': k,
                                 'status': 'skipped_memory_guard',
                                 'estimated_dense_mib': round(estimated_mib, 1)})
            continue
        X_dense = X_sparse.toarray().astype(np.float32, copy=False)
        for method in args.fiddle_reducers:
            for k in args.k:
                if not (1 <= k <= min(D, N * L)):
                    print(f'  SKIP FIDDLE+{method} dt={dt}, k={k}: exceeds dimensions')
                    continue
                print(f'Running FIDDLE+{method}, dt={dt}, k={k}', flush=True)
                model = (PCACompressor(k, seed=args.seed) if method == 'pca' else
                         AutoencoderCompressor(k, hidden=(args.ae_hidden,),
                                               max_iter=args.ae_max_iter, seed=args.seed))
                tick = time.perf_counter()
                model.fit(X_dense)
                fit_seconds = time.perf_counter() - tick
                encoded_path = root / label / f'{method}_k{k}_fiddle_encoded.npz'
                tick = time.perf_counter()
                _fiddle_encoder_bundle(encoded_path, model, X_dense, N, L, k, method)
                encode_and_package_seconds = time.perf_counter() - tick
                tick = time.perf_counter()
                quality = _verify_fiddle_encoded(
                    encoded_path, X_dense, N, L, D, method
                )
                reconstruct_seconds = time.perf_counter() - tick
                files = {name: f for name, f in common_files.items() if name != 'X.npz'}
                files['encoded_dynamic_features.npz'] = encoded_path
                payload = root / label / f'fiddle_{method}_k{k}_transfer.zip'
                package_start = time.perf_counter()
                payload_bytes = _zip_payload(payload, files)
                packaging_seconds = time.perf_counter() - package_start
                simulated = simulated_transmission_time(payload_bytes,
                                                        args.bandwidth_mbps)
                rows.append({**base, 'method': f'fiddle+{method}', 'k': k,
                             'status': 'completed',
                             'payload_filename': str(payload.relative_to(run_dir)),
                             'payload_bytes': payload_bytes, 'payload_sha256': sha256_file(payload),
                             'payload_pct_change_vs_csv': 100 * (payload_bytes / base_csv_bytes - 1),
                             'payload_pct_change_vs_gzip6': 100 * (payload_bytes / base_gzip_bytes - 1),
                             'fit_seconds': fit_seconds,
                             'encode_and_package_seconds': encode_and_package_seconds + packaging_seconds,
                             'receiver_reconstruction_seconds': reconstruct_seconds,
                             'transmission_seconds_SIMULATED': simulated,
                             'total_seconds_SIMULATED': (preparation_seconds + fiddle_seconds
                                 + fit_seconds + encode_and_package_seconds + packaging_seconds
                                 + simulated + reconstruct_seconds),
                             'estimated_dense_mib': round(estimated_mib, 1),
                             'pca_explained_variance_ratio': (
                                 model.explained_variance if method == 'pca' else None
                             ), **quality})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('dataset', nargs='?', help='Raw or Phase-3 selected wide CSV')
    parser.add_argument('--output-dir', default='output/sepsis2019/phase4')
    parser.add_argument('--methods', nargs='+', choices=['pca', 'autoencoder'],
                        default=['pca', 'autoencoder'])
    parser.add_argument('--k', nargs='+', type=int, default=[2, 4, 8, 16])
    parser.add_argument('--ae-hidden', type=int, default=32)
    parser.add_argument('--ae-max-iter', type=int, default=80)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--id-column', default='patient_id')
    parser.add_argument('--time-column', default='time')
    parser.add_argument('--outcome-column', default='SepsisLabel')
    parser.add_argument('--passthrough', nargs='*', default=['Gender', 'Unit1', 'Unit2'],
                        help='Clinical categories to preserve losslessly instead of PCA/AE')
    parser.add_argument('--bundle-compression', choices=['none', 'deflate'], default='deflate')
    parser.add_argument('--bandwidth-mbps', type=float, default=100.0)
    parser.add_argument('--write-reconstructed', action='store_true')
    # FIDDLE is an explicit additional branch, using the OFFICIAL FIDDLE CLI.
    parser.add_argument('--with-fiddle', action='store_true',
                        help='Run FIDDLE-only and FIDDLE+reducers alongside PCA/AE')
    parser.add_argument('--skip-direct', action='store_true',
                        help='Only evaluate FIDDLE branches')
    parser.add_argument('--fiddle-repo', default='FIDDLE',
                        help='Local cloned official FIDDLE GitHub repository')
    parser.add_argument('--fiddle-mode', choices=['run', 'reuse'], default='run',
                        help='Run official FIDDLE or reuse existing FIDDLE output')
    parser.add_argument('--fiddle-existing-root', default=None,
                        help='For reuse mode, directory containing dt_1p0, dt_2p0 etc')
    parser.add_argument('--fiddle-T', type=float, default=48.0,
                        help='Common observation horizon in HOURS; [0,T)')
    parser.add_argument('--fiddle-dt', nargs='+', type=float,
                        default=[1.0, 2.0, 4.0, 6.0])
    parser.add_argument('--fiddle-theta-1', type=float, default=0.001)
    parser.add_argument('--fiddle-theta-2', type=float, default=0.001)
    parser.add_argument('--fiddle-theta-freq', type=float, default=1.0)
    parser.add_argument('--fiddle-stats', nargs='+', default=['min', 'max', 'mean'])
    parser.add_argument('--fiddle-static', nargs='*',
                        default=['Age', 'Gender', 'Unit1', 'Unit2', 'HospAdmTime'])
    parser.add_argument('--fiddle-event-chunk-rows', type=int, default=2000)
    parser.add_argument('--fiddle-reducers', nargs='*',
                        choices=['pca', 'autoencoder'], default=['pca', 'autoencoder'])
    parser.add_argument('--max-fiddle-dense-mib', type=float, default=512,
                        help='Safety cap for dense FIDDLE features; skipped if exceeded')
    parser.add_argument('--receive-fiddle-archive', type=Path,
                        help='Receiver: unpack FIDDLE transfer ZIP and decode engineered features')
    parser.add_argument('--fiddle-receiver-dir', type=Path,
                        help='Destination directory for received FIDDLE data')
    parser.add_argument('--reconstruct-bundle', type=Path,
                        help='University-only mode: reconstruct a received NPZ payload')
    parser.add_argument('--reconstructed-output', type=Path,
                        help='Destination CSV for --reconstruct-bundle')
    parser.add_argument('--expected-sha256', help='Optional integrity check on received payload')
    args = parser.parse_args()
    if args.receive_fiddle_archive:
        path = args.receive_fiddle_archive
        if args.expected_sha256 and sha256_file(path) != args.expected_sha256.lower():
            parser.error('SHA-256 mismatch for received FIDDLE archive')
        target = args.fiddle_receiver_dir or path.with_name(path.stem + '_received')
        receive_fiddle_archive(path, target, args.max_fiddle_dense_mib)
        return
    if args.reconstruct_bundle:
        p = args.reconstruct_bundle
        if args.expected_sha256 and sha256_file(p) != args.expected_sha256.lower():
            parser.error('SHA-256 mismatch for received transfer payload')
        out = args.reconstructed_output or p.with_name(p.stem + '_reconstructed.csv')
        out.parent.mkdir(parents=True, exist_ok=True)
        df = reconstruct_bundle(p)
        df.to_csv(out, index=False)
        print(f'Reconstructed {len(df):,} rows and {df.shape[1]} columns -> {out}')
        return
    if not args.dataset:
        parser.error('Provide a CSV dataset, or use --reconstruct-bundle')
    if args.bandwidth_mbps <= 0 or args.ae_hidden <= 0 or args.ae_max_iter <= 0:
        parser.error('Bandwidth, AE hidden units, and AE maximum iterations must be positive')
    if any(k <= 0 for k in args.k):
        parser.error('Every --k must be positive')
    if args.with_fiddle:
        if args.fiddle_T <= 0 or args.max_fiddle_dense_mib <= 0:
            parser.error('FIDDLE T and maximum matrix memory must be positive')
        if args.fiddle_event_chunk_rows < 1 or any(dt <= 0 or dt > args.fiddle_T
                or abs(args.fiddle_T / dt - round(args.fiddle_T / dt)) > 1e-8
                for dt in args.fiddle_dt):
            parser.error('FIDDLE bin widths must be positive divisors of T')
        if args.fiddle_mode == 'reuse' and not args.fiddle_existing_root:
            parser.error('--fiddle-mode reuse requires --fiddle-existing-root')
        if args.fiddle_mode == 'run' and not (
            Path(args.fiddle_repo).expanduser().resolve() / 'FIDDLE' / 'run.py'
        ).is_file():
            parser.error('FIDDLE/run.py not found. Set --fiddle-repo to the cloned FIDDLE root.')
    run_experiment(args)


if __name__ == '__main__':
    main()

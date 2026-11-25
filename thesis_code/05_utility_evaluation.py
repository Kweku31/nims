#!/usr/bin/env python3
"""Phase 5: non-predictive clinical-data research-utility evaluation.

Reads Phase 4 outputs; DOES NOT train a classifier, PCA, or autoencoder.
Checks every received .npz bundle against its mandatory SHA-256 sidecar AND
Phase 4 manifest before opening. Reconstructs numerical features in memory.

Main metrics:
* Observed-value normalized reconstruction RMSE and observed-value R^2 proxy.
* Sampled-patient Euclidean pairwise-distance preservation (original vs
  reconstructed, standardized in the SAME original-feature space).
* Optional original-vs-latent distance correlation (descriptive only).
* Top-5/top-10 nearest-neighbour overlap, reconstructed and latent spaces.
* Per-feature reconstruction metrics and Phase 3 feature-retention audit.
* Inherits actual transfer-size and clinical-screen columns from Phase 4.

Example:
    python 06_utility_evaluation.py \
      --experiment output/phase4/raw_... sepsis_1000_raw.csv \
      --experiment output/phase4/selected_... output/phase3/FS_95_clinical_review/selected_dataset.csv \
      --full-reference sepsis_1000_raw.csv \
      --output-dir output/sepsis2019/phase5

No classification; no patient train/validation/test split.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from scipy.stats import pearsonr, spearmanr

INTERPRETABILITY = {
    "pca": "low-to-moderate: linear components; loadings can be inspected",
    "autoencoder": "low: nonlinear latent units lack original clinical units",
    "lossless": "high within the transferred column set; original variable names and values preserved",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verified_bundle(path: Path, expected_digest: str) -> dict[str, np.ndarray]:
    """Fail closed: check both sidecar and Phase 4 recorded digest."""
    sidecar = path.with_name(path.name + '.sha256')
    if not path.is_file() or not sidecar.is_file():
        raise FileNotFoundError(f'Both payload and authenticated checksum sidecar are required: {path}')
    lines = sidecar.read_text(encoding='utf-8').splitlines()
    if len(lines) != 1:
        raise ValueError(f'Invalid SHA-256 sidecar (expected one line): {sidecar}')
    match = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?(.+)', lines[0])
    if match is None or match.group(2) != path.name:
        raise ValueError(f'SHA-256 sidecar filename mismatch: {sidecar}')
    digest = sha256_file(path)
    if not hmac.compare_digest(digest, match.group(1).lower()):
        raise ValueError(f'Payload SHA-256 does not match sidecar: {path}')
    if not isinstance(expected_digest, str) or not hmac.compare_digest(digest, expected_digest.lower()):
        raise ValueError(f'Payload SHA-256 does not match Phase 4 comparison report: {path}')
    with np.load(path, allow_pickle=False) as obj:
        return {key: np.array(obj[key], copy=True) for key in obj.files}


def reconstruct(arrays: dict[str, np.ndarray]) -> tuple[pd.DataFrame, dict]:
    """Decode Phase 4 format_version=1 with the received decoder only."""
    manifest = json.loads(str(arrays['manifest_json'].item()))
    if manifest.get('format_version') != 1:
        raise ValueError('Unsupported Phase 4 payload format version')
    method, k = manifest['method'], int(manifest['k'])
    Z = np.asarray(arrays['Z'], dtype=np.float64)
    n, latent_k = Z.shape
    predictors = [str(c) for c in arrays['predictor_columns'].tolist()]
    passthrough = [str(c) for c in arrays['passthrough_columns'].tolist()]
    all_columns = [str(c) for c in arrays['all_columns'].tolist()]
    if (latent_k != k or n != int(manifest['n_rows'])
        or len(predictors) != int(manifest['n_predictors_encoded'])
        or len(set(all_columns)) != len(all_columns)):
        raise ValueError('Payload contains inconsistent dimensions or duplicate columns')
    mean = np.asarray(arrays['scaler_mean'], dtype=np.float64)
    scale = np.asarray(arrays['scaler_scale'], dtype=np.float64)
    medians = np.asarray(arrays['imputation_medians'], dtype=np.float64)
    if not (len(mean) == len(scale) == len(medians) == len(predictors)):
        raise ValueError('Invalid fitted-scaler or median dimensions')
    if method == 'pca':
        standardized = Z @ arrays['pca_components'] + arrays['pca_mean']
    elif method == 'autoencoder':
        standardized = Z
        for j in range(int(arrays['decoder_layers'].item())):
            standardized = standardized @ arrays[f'decoder_w_{j}'] + arrays[f'decoder_b_{j}']
            if j < int(arrays['decoder_layers'].item()) - 1:
                standardized = np.maximum(0, standardized)
    else:
        raise ValueError(f'Unexpected method in bundle: {method}')
    values = standardized * scale + mean
    if values.shape != (n, len(predictors)):
        raise ValueError('Incorrect reconstructed matrix dimensions')
    bits = np.unpackbits(arrays['observed_mask_packed'], bitorder='little')
    if len(bits) < values.size:
        raise ValueError('Packed missingness mask is too short')
    observed = bits[:values.size].reshape(values.shape).astype(bool)
    values[~observed] = np.nan
    fields = {col: values[:, j] for j, col in enumerate(predictors)}
    for j, col in enumerate(passthrough):
        fields[col] = arrays[f'passthrough_{j}']
    if set(fields) != set(all_columns):
        raise ValueError('Payload columns do not match full reconstructed table')
    return pd.DataFrame(fields, columns=all_columns), {
        'method': method, 'k': k, 'latent': Z,
        'predictors': predictors, 'passthrough': passthrough,
        'scaler_mean': mean, 'scaler_scale': scale,
        'imputation_medians': medians, 'observed': observed,
    }


def patient_sample_rows(df: pd.DataFrame, patient_column: str,
                        sample_size: int, seed: int) -> tuple[np.ndarray, list[str]]:
    """Choose one observation per sampled patient, no prediction split."""
    if patient_column not in df:
        raise ValueError(f'Patient identifier is not available: {patient_column}')
    groups = df.groupby(patient_column, sort=True, dropna=False).indices
    ids = sorted(groups, key=str)
    if len(ids) < 3:
        raise ValueError('At least three patients required for pairwise geometry assessment')
    rng = np.random.default_rng(seed)
    selected_indices = rng.choice(len(ids), size=min(sample_size, len(ids)), replace=False)
    selected_ids = [ids[int(i)] for i in selected_indices]
    selected_rows = [int(rng.choice(groups[pid])) for pid in selected_ids]
    return np.asarray(selected_rows, dtype=int), [str(pid) for pid in selected_ids]


def safe_corr(a: np.ndarray, b: np.ndarray, which: str) -> float | None:
    if len(a) < 3 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return None
    if which == 'pearson':
        val = pearsonr(a, b).statistic
    else:
        val = spearmanr(a, b).statistic
    return float(val) if np.isfinite(val) else None


def distance_metrics(X: np.ndarray, Y: np.ndarray,
                     Z: np.ndarray, sample_rows: np.ndarray) -> dict:
    """Distances evaluated on the SAME selected rows for both spaces."""
    original_dist = pdist(X[sample_rows], metric='euclidean')
    reconstructed_dist = pdist(Y[sample_rows], metric='euclidean')
    latent_dist = pdist(Z[sample_rows], metric='euclidean')
    return {
        'distance_sample_rows': len(sample_rows),
        'distance_pairs': len(original_dist),
        'distance_pearson_original_vs_reconstruction': safe_corr(original_dist, reconstructed_dist, 'pearson'),
        'distance_spearman_original_vs_reconstruction': safe_corr(original_dist, reconstructed_dist, 'spearman'),
        'distance_pearson_original_vs_latent_DESCRIPTIVE': safe_corr(original_dist, latent_dist, 'pearson'),
        'distance_spearman_original_vs_latent_DESCRIPTIVE': safe_corr(original_dist, latent_dist, 'spearman'),
    }



def nearest_neighbor_metrics(X: np.ndarray, Y: np.ndarray, Z: np.ndarray,
                             sample_rows: np.ndarray, sampled_patients: list[str],
                             label: str, method: str, model_k: int,
                             neighbor_ks: tuple[int, ...]) -> tuple[dict, list[dict]]:
    """Compare each sampled patient's top-K neighbours with the original top-K.

    The reference and reconstructed data use the SAME standardized original
    feature axes. The latent-space result is DESCRIPTIVE: its Euclidean
    geometry is not normalized to that of the clinical-feature space.

    Overlap(i, K) = |N_original(i, K) ∩ N_candidate(i, K)| / K.
    Return the mean over sampled patients, and auditable per-patient rows.
    Do not mix samples across datasets or invent unavailable K values.
    """
    n = len(sample_rows)
    if len(sampled_patients) != n:
        raise ValueError('Patient IDs and sampled rows have different lengths')
    matrices = {
        'original': X[sample_rows],
        'reconstruction': Y[sample_rows],
        'latent': Z[sample_rows],
    }
    ranks = {}
    sorted_distances = {}
    for name, mat in matrices.items():
        if mat.ndim != 2 or not np.all(np.isfinite(mat)):
            raise ValueError(f'Non-finite or malformed sampled {name} features')
        d = squareform(pdist(mat, metric='euclidean'))
        np.fill_diagonal(d, np.inf)  # exclude self-neighbour
        # Stable ranking resolves exact distance ties by sampled row order.
        order = np.argsort(d, axis=1, kind='stable')[:, :n-1]
        ranks[name] = order
        sorted_distances[name] = np.take_along_axis(d, order, axis=1)
    summary: dict = {}
    per_patient: list[dict] = []
    for kk in neighbor_ks:
        prefix = f'knn{kk}'
        if kk >= n:
            # K neighbours cannot be defined with fewer than K+1 sampled patients.
            summary[f'{prefix}_overlap_original_vs_reconstruction'] = None
            summary[f'{prefix}_overlap_original_vs_latent_DESCRIPTIVE'] = None
            summary[f'{prefix}_exact_match_pct_original_vs_reconstruction'] = None
            summary[f'{prefix}_tie_at_boundary_pct_original'] = None
            summary[f'{prefix}_tie_at_boundary_pct_reconstruction'] = None
            summary[f'{prefix}_tie_at_boundary_pct_latent'] = None
            continue
        overlap_counts = {'reconstruction': [], 'latent': []}
        tie = {}
        for name in ranks:
            distances = sorted_distances[name]
            # If K is the maximum possible neighbour count, boundary cannot tie
            # with the (K+1)-st neighbour.
            tie[name] = (np.isclose(distances[:, kk-1], distances[:, kk],
                                    atol=1e-12, rtol=1e-12)
                         if kk < n-1 else np.zeros(n, dtype=bool))
            summary[f'{prefix}_tie_at_boundary_pct_{name}'] = float(100 * np.mean(tie[name]))
        for i, (patient, source_row) in enumerate(zip(sampled_patients, sample_rows)):
            original_neighbors = ranks['original'][i, :kk]
            overlap_row = {
                'dataset': label, 'method': method, 'k': model_k,
                'neighbor_k': kk, 'patient_id': patient,
                'row_position': int(source_row), 'sampled_patient_count': n,
                'original_tie_at_boundary': bool(tie['original'][i]),
                'reconstructed_tie_at_boundary': bool(tie['reconstruction'][i]),
                'latent_tie_at_boundary': bool(tie['latent'][i]),
            }
            for candidate in ('reconstruction', 'latent'):
                count = int(np.intersect1d(
                    original_neighbors, ranks[candidate][i, :kk],
                    assume_unique=True).size)
                overlap_counts[candidate].append(count)
                overlap_row[f'overlap_count_original_vs_{candidate}'] = count
                overlap_row[f'overlap_fraction_original_vs_{candidate}'] = count / kk
            per_patient.append(overlap_row)
        reconstructed_counts = np.asarray(overlap_counts['reconstruction'])
        summary[f'{prefix}_overlap_original_vs_reconstruction'] = float(np.mean(reconstructed_counts) / kk)
        summary[f'{prefix}_overlap_original_vs_latent_DESCRIPTIVE'] = float(
            np.mean(overlap_counts['latent']) / kk)
        summary[f'{prefix}_exact_match_pct_original_vs_reconstruction'] = float(
            100 * np.mean(reconstructed_counts == kk))
    return summary, per_patient

def feature_metrics(source: pd.DataFrame, recovered: pd.DataFrame, predictors: list[str],
                    method: str, k: int, label: str) -> tuple[dict, list[dict]]:
    """Compute error only where the original clinical variable was observed."""
    rows: list[dict] = []
    weighted_sse = weighted_sst = 0.0
    weighted_original_sse = 0.0
    raw_sse = 0.0
    n_valid = 0
    n_normalized_valid = 0
    for col in predictors:
        a = source[col].to_numpy(dtype=np.float64)
        b = recovered[col].to_numpy(dtype=np.float64)
        valid = np.isfinite(a)
        if not np.array_equal(valid, np.isfinite(b)):
            raise ValueError(f'Missingness mask was not preserved: {col}')
        n_obs = int(valid.sum())
        if n_obs:
            diff = a[valid] - b[valid]
            mae = float(np.mean(np.abs(diff)))
            rmse = float(np.sqrt(np.mean(diff**2)))
            std = float(np.std(a[valid]))
            source_mean, recovered_mean = float(np.mean(a[valid])), float(np.mean(b[valid]))
            source_median, recovered_median = float(np.median(a[valid])), float(np.median(b[valid]))
            recovered_std = float(np.std(b[valid]))
            raw_sse += float(np.dot(diff, diff))
            n_valid += n_obs
            if std > 1e-12 and n_obs > 1:
                scaled = diff / std
                scaled_sse = float(np.dot(scaled, scaled))
                # Sum of squared standardized deviations: ~n_obs.
                scaled_sst = float(np.sum(((a[valid] - np.mean(a[valid])) / std)**2))
                weighted_sse += scaled_sse
                weighted_sst += scaled_sst
                n_normalized_valid += n_obs
                nrmse = float(rmse / std)
                observed_r2 = float(1.0 - np.sum(diff**2) / np.sum((a[valid] - a[valid].mean())**2))
            else:
                nrmse = observed_r2 = None
        else:
            mae = rmse = std = nrmse = observed_r2 = None
            source_mean = recovered_mean = source_median = recovered_median = recovered_std = None
        rows.append({
            'dataset': label, 'method': method, 'k': k, 'feature': col,
            'observed_count': n_obs, 'hourly_missingness_pct': 100*(1-n_obs/len(source)),
            'MAE_original_units': mae, 'RMSE_original_units': rmse,
            'observed_SD_original_units': std, 'NRMSE_by_observed_SD': nrmse,
            'R2_observed_feature': observed_r2,
            'original_mean': source_mean, 'reconstructed_mean': recovered_mean,
            'mean_shift_original_units': (recovered_mean - source_mean if n_obs else None),
            'mean_shift_in_observed_SD_units': (
                (recovered_mean-source_mean)/std if n_obs and std>1e-12 else None),
            'original_median': source_median, 'reconstructed_median': recovered_median,
            'median_shift_original_units': (recovered_median-source_median if n_obs else None),
            'reconstructed_SD': recovered_std,
            'SD_ratio_reconstructed_to_original': (recovered_std/std if n_obs and std>1e-12 else None),
        })
    return {
        'observed_numeric_cells': n_valid,
        'raw_SSE_observed_original_units': raw_sse,
        'RMSE_observed_original_units': float(np.sqrt(raw_sse/n_valid)) if n_valid else None,
        'normalized_RMSE_observed': float(np.sqrt(weighted_sse/n_normalized_valid)) if n_normalized_valid else None,
        'R2_retained_variation_observed_STANDARDIZED': float(1-weighted_sse/weighted_sst) if weighted_sst>0 else None,
        'observed_features_with_variation': sum(r['R2_observed_feature'] is not None for r in rows),
    }, rows


def compute_feature_retention(source: pd.DataFrame, reference: pd.DataFrame,
                              predictors: list[str], label: str,
                              patient_col: str, time_col: str) -> tuple[dict, list[dict]]:
    if source.shape[0] != reference.shape[0]:
        raise ValueError('Reference and selected dataset have different row counts')
    for col in [patient_col, time_col]:
        if col in source and col in reference:
            if not source[col].equals(reference[col]):
                raise ValueError(f'Row alignment with full reference failed: {col}')
    full_predictors = [c for c in reference.select_dtypes(include=[np.number]).columns
                       if c not in {patient_col, time_col, 'SepsisLabel', 'Gender', 'Unit1', 'Unit2'}]
    # A numerical column may be retained EXACTLY outside PCA/AE (e.g. Age,
    # HospAdmTime, ICULOS). Feature retention must reflect the transmitted
    # dataset's columns, not only the variables encoded by the model.
    retained = set(source.columns)
    audit = []
    original_observations = 0
    retained_observations = 0
    for c in full_predictors:
        mask = reference[c].notna().to_numpy()
        obs = int(mask.sum())
        original_observations += obs
        if c in retained:
            retained_observations += obs
        patient_coverage = (float(reference.groupby(patient_col)[c].count().gt(0).mean())
                            if patient_col in reference else None)
        audit.append({
            'dataset': label, 'feature': c, 'retained': c in retained,
            'observed_hourly_measurements_in_full_reference': obs,
            'missingness_pct_full_reference': 100*(1-obs/len(reference)),
            'patient_coverage_pct_full_reference': 100*patient_coverage if patient_coverage is not None else None,
            'note': 'Removed feature is NOT recoverable from the reduced dataset' if c not in retained else '',
        })
    return {
        'full_reference_numerical_features': len(full_predictors),
        'retained_reference_numerical_features': sum(c in retained for c in full_predictors),
        'clinical_predictor_retention_pct': (
            100*sum(c in retained for c in full_predictors)/len(full_predictors)
            if full_predictors else None),
        'original_observed_measurements': original_observations,
        'retained_original_observed_measurements': retained_observations,
        'original_observed_measurement_retention_pct': (
            100*retained_observations/original_observations if original_observations else None),
    }, audit


def experiment(run_dir: Path, source_path: Path, full_reference: pd.DataFrame | None,
               patient_col: str, time_col: str, sample_size: int, seed: int,
               neighbor_ks: tuple[int, ...]):
    run_dir, source_path = run_dir.resolve(), source_path.resolve()
    comparison_path = run_dir / 'phase4_comparison.csv'
    if not comparison_path.is_file():
        raise FileNotFoundError(f'Phase 4 summary not found: {comparison_path}')
    report = pd.read_csv(comparison_path)
    meta = json.loads((run_dir / 'phase4_metadata.json').read_text(encoding='utf-8'))
    if not source_path.is_file():
        raise FileNotFoundError(f'Original dataset for this Phase 4 run not found: {source_path}')
    actual_source_sha = sha256_file(source_path)
    if not hmac.compare_digest(actual_source_sha, meta['source_sha256']):
        raise ValueError(f'Source SHA-256 does not match Phase 4 dataset: {source_path}')
    source = pd.read_csv(source_path, low_memory=False)
    if len(source) != int(meta['rows']):
        raise ValueError('Phase 4 source row count differs from metadata')
    label = source_path.stem
    reference = full_reference if full_reference is not None else source
    results, details, samples, neighbor_rows = [], [], [], []
    retention, audit = compute_feature_retention(
        source, reference, list(meta['encoded_predictors']), label, patient_col, time_col)
    sampling_rows, sampled_patients = patient_sample_rows(source, patient_col, sample_size, seed)
    samples = [{'dataset':label, 'patient_id':pid, 'row_position':int(pos),
                'time':source.iloc[pos][time_col] if time_col in source else None}
               for pid, pos in zip(sampled_patients, sampling_rows)]
    for _, p4_row in report.iterrows():
        method, k = str(p4_row['method']), int(p4_row['k'])
        if method not in {'pca', 'autoencoder'}:
            continue
        bundle_path = run_dir / str(p4_row['payload_filename'])
        arrays = verified_bundle(bundle_path, str(p4_row['payload_sha256']))
        recovered, payload = reconstruct(arrays)
        if payload['method'] != method or payload['k'] != k:
            raise ValueError('Method/k mismatch between Phase 4 summary and payload')
        if list(source.columns) != list(recovered.columns) or len(source) != len(recovered):
            raise ValueError('Reconstructed clinical dataset has wrong shape/columns')
        if payload['predictors'] != list(meta['encoded_predictors']):
            raise ValueError('Model predictor names do not match Phase 4 metadata')
        for c in payload['passthrough']:
            if not source[c].equals(recovered[c]):
                raise ValueError(f'Structural/pass-through column changed: {c}')
        quality, features = feature_metrics(source, recovered, payload['predictors'], method, k, label)
        details.extend(features)
        a = source[payload['predictors']].to_numpy(dtype=np.float64)
        b = recovered[payload['predictors']].to_numpy(dtype=np.float64)
        medians, mean, std = payload['imputation_medians'], payload['scaler_mean'], payload['scaler_scale']
        a_scaled = (np.where(np.isfinite(a), a, medians) - mean) / std
        b_scaled = (np.where(np.isfinite(b), b, medians) - mean) / std
        distances = distance_metrics(a_scaled, b_scaled, payload['latent'], sampling_rows)
        neighbors, individual_neighbors = nearest_neighbor_metrics(
            a_scaled, b_scaled, payload['latent'], sampling_rows,
            sampled_patients, label, method, k, neighbor_ks)
        neighbor_rows.extend(individual_neighbors)
        results.append({
            'dataset':label, 'phase4_run_directory':str(run_dir), 'method':method,
            'method_class':'lossy dimensionality reduction', 'k':k,
            'receiver_checksum_verified':True,
            'transfer_bytes_including_sha256':int(p4_row['transmitted_total_bytes']),
            'smallest_lossless_transfer_bytes':int(p4_row['smallest_lossless_transfer_bytes']),
            'size_reduction_pct_vs_smallest_lossless': 100*(1-float(p4_row['transmitted_total_bytes'])/float(p4_row['smallest_lossless_transfer_bytes'])),
            'PCA_intrinsic_explained_variance_ratio_NOT_AE': (float(p4_row['pca_explained_variance_ratio'])
                if method=='pca' and pd.notna(p4_row.get('pca_explained_variance_ratio')) else None),
            'interpretability':INTERPRETABILITY[method],
            'quality_scope':'Reconstruction metrics apply only to encoded numeric columns; exact passthrough numeric columns are retained but excluded from error denominators; no prediction evaluated',
            'new_clinical_range_violations_Phase4': p4_row.get('clinical_screen_new_out_of_range'),
            'autoencoder_convergence_warning_Phase4': p4_row.get('autoencoder_convergence_warning'),
            **retention, **quality, **distances, **neighbors,
        })
    # Lossless rows are descriptive references: Phase 4 separately verified their round trip.
    lossless_path = run_dir / 'phase4_lossless_baselines.csv'
    if lossless_path.is_file():
        lossless = pd.read_csv(lossless_path)
        for _, ref in lossless.iterrows():
            if str(ref.get('status')) != 'verified' or ref.get('roundtrip_verified') not in [True, 'True', 'true']:
                continue
            payload = run_dir / str(ref['payload_filename'])
            # Mandatory integrity verification, also check Phase 4 digest.
            _ = verified_lossless_hash(payload, str(ref['sha256']))
            lossless_neighborhood = {}
            for kk in neighbor_ks:
                # A verified lossless round trip retains exactly the same
                # neighbours for the original numerical columns.
                lossless_neighborhood[f'knn{kk}_overlap_original_vs_reconstruction'] = (
                    1.0 if kk < len(sampling_rows) else None)
                lossless_neighborhood[f'knn{kk}_exact_match_pct_original_vs_reconstruction'] = (
                    100.0 if kk < len(sampling_rows) else None)
            results.append({
                'dataset':label, 'phase4_run_directory':str(run_dir),
                'method':f"lossless_{ref['method']}", 'method_class':'lossless packaging',
                'k':None, 'receiver_checksum_verified':True,
                'transfer_bytes_including_sha256':int(ref['transmitted_total_bytes']),
                'smallest_lossless_transfer_bytes':int(min(lossless.loc[lossless['status']=='verified','transmitted_total_bytes'])),
                'size_reduction_pct_vs_smallest_lossless': 100*(1-float(ref['transmitted_total_bytes'])/
                    float(min(lossless.loc[lossless['status']=='verified','transmitted_total_bytes']))),
                'interpretability':INTERPRETABILITY['lossless'],
                'quality_scope':'Lossless for columns present in this dataset; verification performed in Phase 4',
                'observed_numeric_cells':retention['retained_original_observed_measurements'],
                'raw_SSE_observed_original_units':0.0,
                'RMSE_observed_original_units':0.0,
                'normalized_RMSE_observed':0.0,
                'R2_retained_variation_observed_STANDARDIZED':1.0,
                'distance_pearson_original_vs_reconstruction':1.0,
                'distance_spearman_original_vs_reconstruction':1.0,
                **retention, **lossless_neighborhood,
            })
    return results, details, audit, samples, neighbor_rows


def verified_lossless_hash(path: Path, expected: str) -> str:
    sidecar = path.with_name(path.name+'.sha256')
    if not path.exists() or not sidecar.exists():
        raise FileNotFoundError(f'Lossless payload/sidecar missing: {path}')
    lines = sidecar.read_text(encoding='utf-8').splitlines()
    if len(lines) != 1:
        raise ValueError(f'Invalid lossless checksum sidecar: {sidecar}')
    m = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?(.+)', lines[0])
    if m is None or m.group(2) != path.name:
        raise ValueError('Invalid lossless checksum filename entry')
    digest = sha256_file(path)
    if not (hmac.compare_digest(digest, m.group(1).lower()) and hmac.compare_digest(digest, expected.lower())):
        raise ValueError(f'Checksum mismatch for lossless payload: {path}')
    return digest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--experiment', nargs=2, action='append', metavar=('PHASE4_OUTPUT_DIR','INPUT_CSV'),
                    required=True, help='Repeat this flag for each Phase 4 dataset/run pair')
    ap.add_argument('--full-reference', type=Path, default=None,
                    help='Optional unfiltered CSV for reporting columns/measurements removed in Phase 3')
    ap.add_argument('--patient-id-column', default='patient_id')
    ap.add_argument('--time-column', default='time')
    ap.add_argument('--distance-samples', type=int, default=200,
                    help='Maximum different patients sampled (one observation each)')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--neighbor-k', nargs='+', type=int, default=[5, 10], metavar='K',
                    help='Top-K nearest neighbours to audit (default: 5 10)')
    ap.add_argument('--output-dir', type=Path, default=Path('output/sepsis2019/phase5'))
    args = ap.parse_args()
    if args.distance_samples < 3:
        ap.error('--distance-samples must be >= 3')
    if any(k < 1 for k in args.neighbor_k):
        ap.error('--neighbor-k values must be positive integers')
    neighbor_ks = tuple(sorted(set(args.neighbor_k)))
    full_reference = pd.read_csv(args.full_reference, low_memory=False) if args.full_reference else None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')
    target = args.output_dir / f'phase5_{stamp}'
    target.mkdir(parents=True, exist_ok=False)
    aggregate, feature_rows, retention_rows, sampled_rows, neighbor_rows = [], [], [], [], []
    for run, source in args.experiment:
        print(f'Evaluating: {run}  |  Source: {source}', flush=True)
        summary, per_feature, audit, samples, individual_neighbors = experiment(
            Path(run), Path(source), full_reference, args.patient_id_column,
            args.time_column, args.distance_samples, args.seed, neighbor_ks)
        aggregate.extend(summary)
        feature_rows.extend(per_feature)
        retention_rows.extend(audit)
        sampled_rows.extend(samples)
        neighbor_rows.extend(individual_neighbors)
        print(f'  Evaluated {len(summary)} method/packaging rows; {len(per_feature)} feature metrics')
    pd.DataFrame(aggregate).to_csv(target/'phase5_utility_summary.csv', index=False)
    pd.DataFrame(feature_rows).to_csv(target/'phase5_per_feature_utility.csv', index=False)
    pd.DataFrame(retention_rows).to_csv(target/'phase5_feature_retention.csv', index=False)
    pd.DataFrame(sampled_rows).to_csv(target/'phase5_sampled_patient_rows.csv', index=False)
    pd.DataFrame(neighbor_rows).to_csv(target/'phase5_nearest_neighbor_overlap.csv', index=False)
    metadata = {
        'phase':'Phase 5 - non-predictive research utility evaluation',
        'experiments':[{'phase4_run': str(x), 'input_csv':str(y)} for x,y in args.experiment],
        'full_reference':str(args.full_reference) if args.full_reference else None,
        'sampled_patients_max':args.distance_samples, 'seed':args.seed,
        'nearest_neighbor_k_values':list(neighbor_ks),
        'checksum':'mandatory sidecar AND Phase 4 metadata SHA-256; fails closed',
        'reconstruction':'Phase 4 decoder loaded from each verified payload; no retraining',
        'observed_value_R2':'1 - standardized observed-value SSE / standardized observed-value SST; may be negative',
        'PCA_intrinsic_EVR':'Phase 4 PCA model attribute, not equivalent to autoencoder explained variance',
        'distance':'Euclidean pairwise distances; imputed/scaled original and reconstructed features; one row per sampled patient',
        'latent_distance':'Descriptive only; latent coordinate scales differ between PCA and autoencoder',
        'nearest_neighbor_overlap':(
            'Mean across sampled patients of intersection size of original and candidate top-K '
            'Euclidean neighbour sets divided by K; compares original vs reconstructed (same '
            'original-feature scaling), and original vs latent (descriptive only). Excludes self.'),
        'nearest_neighbor_ties':(
            'Stable ranking breaks exact-distance ties by sampled row index. Report percentage '
            'of patients tied at the K-th boundary; large tie rates weaken interpretation.'),
        'nearest_neighbor_insufficient_sample':(
            'When sampled patient count <= K, top-K is undefined and the result is null.'),
        'nearest_neighbor_sampling_limit':(
            'One randomly sampled hourly record per patient, not a full trajectory or validated patient similarity task.'),
        'clinical_validity':'Uses Phase 4 flagged range violations; does not assert clinical acceptability',
        'no_predictive_model':True, 'no_patient_train_validation_test_split':True,
        'limitation':'Different feature sets give different error denominators; use Phase 3 retention audit and common-feature comparisons',
    }
    (target/'phase5_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('\nPhase 5 complete:',target.resolve())
    print('  - phase5_utility_summary.csv')
    print('  - phase5_per_feature_utility.csv')
    print('  - phase5_feature_retention.csv')
    print('  - phase5_sampled_patient_rows.csv')
    print('  - phase5_nearest_neighbor_overlap.csv')
    print('  - phase5_metadata.json')


if __name__=='__main__':
    main()

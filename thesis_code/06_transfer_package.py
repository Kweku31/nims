#!/usr/bin/env python3
"""Phase 6: verifiable hospital-to-university transfer packages.

Reuses *existing* Phase 4 payloads: lossless CSV gzip/zstd or Parquet,
PCA and nonlinear AE NPZ (including latent Z, decoder, masks and pass-through).
No representation model is trained here and no Project 4 ingestion is built.

Commands:
  build    Construct a provenance-rich, checksummed, timestamped tar package.
  verify   Validate the tar/checksum or an unpacked package directory.
  unpack   Verify first, safely extract, and optionally recover a usable NPZ.
  send     SCP archive + SHA256 sidecar, verify remotely, repeat timed trials.

Optional NPZ codec comparison: native DEFLATE-NPZ vs gzip/zstd *on the
same ZIP_STORED (uncompressed) NPZ member data*. Not gzip-on-deflate.

Requirements: Python 3.10+, numpy, pandas, scipy, scikit-learn;
optional: pyarrow (for Parquet), zstandard or zstd executable (for zstd); SSH/SCP for send.
"""
from __future__ import annotations

from thesis_unified.thesis_pipeline import ssh_transport

import argparse
import gzip
import hashlib
import hmac
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd
import scipy
import sklearn

SCHEMA_VERSION = '1.0.0'
CHUNK = 1024 * 1024
SHA_PATTERN = re.compile(r'[a-f0-9]{64}')
LOSSLESS_FILENAMES = {
    'gzip': 'source_csv_gzip6.csv.gz',
    'zstd': 'source_csv_zstd3.csv.zst',
    'parquet': 'source_parquet_zstd.parquet',
}


@dataclass
class TransformationStep:
    step_name: str
    method: str
    parameters: dict[str, Any] = field(default_factory=dict)
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TransformationLog:
    steps: list[TransformationStep] = field(default_factory=list)

    def add(self, step_name: str, method: str, **parameters: Any) -> None:
        self.steps.append(TransformationStep(step_name, method, parameters))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f_UTC')


def compute_checksum(file_path: Path) -> str:
    h = hashlib.sha256()
    with Path(file_path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def checksum_stream(stream) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(CHUNK), b''):
        h.update(chunk)
    return h.hexdigest()


def write_sidecar(path: Path) -> Path:
    digest = compute_checksum(path)
    sidecar = path.with_name(path.name + '.sha256')
    sidecar.write_text(f'{digest}  {path.name}\n', encoding='utf-8')
    return sidecar


def parse_sidecar_contents(contents: bytes, filename: str, expected_hash: str) -> None:
    try:
        lines = contents.decode('utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError('Invalid checksum sidecar encoding') from exc
    if len(lines) != 1:
        raise ValueError(f'Sidecar must have one line for {filename}')
    pattern = re.fullmatch(r'([0-9A-Fa-f]{64})[ \t]+\*?(.+)', lines[0])
    if not pattern or pattern.group(2) != filename:
        raise ValueError(f'Malformed checksum sidecar for {filename}')
    if not hmac.compare_digest(pattern.group(1).lower(), expected_hash):
        raise ValueError(f'Checksum sidecar mismatch for {filename}')


def verify_existing_sidecar(path: Path) -> str:
    sidecar = path.with_name(path.name + '.sha256')
    if not sidecar.is_file():
        raise FileNotFoundError(f'Mandatory Phase 4 checksum missing: {sidecar}')
    digest = compute_checksum(path)
    parse_sidecar_contents(sidecar.read_bytes(), path.name, digest)
    return digest


def get_dependency_versions() -> dict[str, str]:
    versions = {
        'python': platform.python_version(),
        'platform': platform.platform(),
        'numpy': np.__version__,
        'pandas': pd.__version__,
        'scipy': scipy.__version__,
        'scikit-learn': sklearn.__version__,
    }
    for module, package in [('pyarrow', 'pyarrow'), ('zstandard', 'zstandard')]:
        try:
            from importlib.metadata import version
            versions[module] = version(package)
        except Exception:
            versions[module] = 'not installed'
    return versions


def valid_relative_file(path: str) -> PurePosixPath:
    p = PurePosixPath(path)
    if (not path or path.startswith('/') or '\\' in path or not p.parts or
            any(segment in ('.', '..') for segment in p.parts) or
            any(ord(c) < 32 for c in path)):
        raise ValueError(f'Unsafe package path: {path!r}')
    return p


def safe_filename(name: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name) or name in ('.', '..'):
        raise ValueError('Package name must contain only letters, digits, _, - or .')
    return name


def load_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError(f'JSON object expected: {path}')
    return result


def source_dictionary(source: Path, phase4_meta: dict, reference: Path | None,
                      clinical_dictionary: dict, method: str) -> list[dict]:
    # Inspect a bounded number of rows. Not a guarantee of final Parquet/CSV physical types.
    sample = pd.read_csv(source, nrows=10000, low_memory=False)
    columns = list(sample.columns)
    if columns != list(phase4_meta.get('original_columns', [])):
        raise ValueError('Source CSV columns/order do not match Phase 4 metadata')
    missing_columns = []
    if reference is not None:
        all_columns = list(pd.read_csv(reference, nrows=0).columns)
        missing_columns = [c for c in all_columns if c not in columns]
    exact = set(phase4_meta.get('preserved_exactly', []))
    encoded = set(phase4_meta.get('encoded_predictors', []))
    out = []
    for column in columns:
        extra = clinical_dictionary.get(column, {})
        if not isinstance(extra, dict):
            raise ValueError(f'Clinical dictionary entry must be an object: {column}')
        out.append({
            'column': column,
            'dtype_inferred_from_first_10000_rows': str(sample[column].dtype),
            'role': ('passthrough_exact' if column in exact else
                     'encoded_numerical_predictor' if column in encoded else 'other'),
            'preservation': ('exact' if method in ('gzip', 'zstd', 'parquet') or column in exact
                             else 'lossy_if_encoded'),
            'source': column,
            'unit': extra.get('unit'),
            'description': extra.get('description'),
        })
    for column in missing_columns:
        extra = clinical_dictionary.get(column, {})
        out.append({'column': column, 'dtype_inferred_from_first_10000_rows': None,
                    'role': 'removed_before_phase4', 'preservation': 'not_transmitted',
                    'source': column, 'unit': extra.get('unit'),
                    'description': extra.get('description')})
    return out


def build_data_dictionary(original_columns: list[str], final_columns: list[str],
                          column_dtypes: dict[str, str],
                          column_sources: dict[str, Any] | None = None) -> list[dict]:
    """Compatibility helper from the original Phase 6 sample."""
    column_sources = column_sources or {}
    return [
        {'column': c, 'dtype': column_dtypes.get(c, 'unknown'),
         'derived': c not in original_columns,
         'source': column_sources.get(c, c if c in original_columns else 'unknown')}
        for c in final_columns
    ]


def npz_entry_hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path, 'r') as z:
        names = z.namelist()
        if len(names) != len(set(names)) or not names or any(not n.endswith('.npy') for n in names):
            raise ValueError('Invalid or duplicate NPZ entries')
        if any(valid_relative_file(n).parts != (n,) for n in names):
            raise ValueError('NPZ contains unsafe member names')
        return {name: checksum_stream(z.open(name)) for name in names}


def uncompressed_npz(source: Path, destination: Path) -> None:
    """Repackage the *same* .npy array bytes with ZIP_STORED (no DEFLATE)."""
    with zipfile.ZipFile(source, 'r') as src, zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as dst:
        names = src.namelist()
        if not names or len(names) != len(set(names)):
            raise ValueError('Invalid NPZ')
        for name in names:
            if not name.endswith('.npy') or len(valid_relative_file(name).parts) != 1:
                raise ValueError(f'Unexpected NPZ member: {name}')
            with src.open(name) as fin, dst.open(name, 'w', force_zip64=True) as fout:
                shutil.copyfileobj(fin, fout, CHUNK)
    if npz_entry_hashes(source) != npz_entry_hashes(destination):
        raise AssertionError('NPZ array bytes changed during ZIP_STORED serialization')


def compress_npz(source: Path, destination: Path, codec: str) -> dict:
    """source is Phase4 deflate-NPZ; custom codecs compress ZIP_STORED NPZ."""
    if codec == 'native':
        shutil.copyfile(source, destination)
        return {'codec': 'deflate_inside_npz', 'uncompressed_npz_bytes': None,
                'npz_member_hash_verified': True}
    with tempfile.TemporaryDirectory(prefix='phase6_npz_') as tmp:
        raw = Path(tmp) / 'uncompressed.npz'
        uncompressed_npz(source, raw)
        if codec == 'gzip':
            with raw.open('rb') as fin, destination.open('wb') as fout:
                with gzip.GzipFile(filename='', mode='wb', fileobj=fout, compresslevel=6, mtime=0) as gz:
                    shutil.copyfileobj(fin, gz, CHUNK)
        elif codec == 'zstd':
            try:
                import zstandard as zstd
            except ImportError:
                zstd_bin = shutil.which('zstd')
                if not zstd_bin:
                    raise RuntimeError('NPZ + Zstandard requires zstandard package or zstd executable')
                subprocess.run([zstd_bin, '-q', '-f', '-3', '-o', str(destination), str(raw)], check=True)
            else:
                with raw.open('rb') as fin, destination.open('wb') as fout:
                    zstd.ZstdCompressor(level=3).copy_stream(fin, fout)
        else:
            raise ValueError(f'Unknown NPZ codec: {codec}')
        # Check that decompressed output is a lossless copy of uncompressed NPZ.
        with tempfile.TemporaryDirectory(prefix='phase6_npz_check_') as checkdir:
            checked = Path(checkdir) / 'roundtrip.npz'
            decompress_npz(destination, checked, codec)
            if npz_entry_hashes(checked) != npz_entry_hashes(source):
                raise AssertionError('Compressed NPZ failed array-level round trip')
        return {'codec': codec, 'uncompressed_npz_bytes': raw.stat().st_size,
                'npz_member_hash_verified': True}


def decompress_npz(packed: Path, destination: Path, codec: str) -> None:
    if codec == 'native':
        shutil.copyfile(packed, destination)
    elif codec == 'gzip':
        with gzip.open(packed, 'rb') as fin, destination.open('wb') as fout:
            shutil.copyfileobj(fin, fout, CHUNK)
    elif codec == 'zstd':
        try:
            import zstandard as zstd
        except ImportError:
            zstd_bin = shutil.which('zstd')
            if not zstd_bin:
                raise RuntimeError('Zstandard requires zstandard package or zstd executable')
            subprocess.run([zstd_bin, '-q', '-f', '-d', '-o', str(destination), str(packed)], check=True)
        else:
            with packed.open('rb') as fin, destination.open('wb') as fout:
                zstd.ZstdDecompressor().copy_stream(fin, fout)
    else:
        raise ValueError(f'Unsupported codec {codec}')


def validate_lossless_roundtrip(payload: Path, method: str, source: Path, expected_source_hash: str) -> str:
    if method == 'parquet':
        try:
            from pandas.testing import assert_frame_equal
            original = pd.read_csv(source)
            recovered = pd.read_parquet(payload, engine='pyarrow')
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError('Parquet verification requires pyarrow') from exc
        assert_frame_equal(original.reset_index(drop=True), recovered.reset_index(drop=True),
                           check_dtype=False, check_exact=True, check_names=True)
        return 'DataFrame values, column order and missingness exactly equal'
    h = hashlib.sha256()
    if method == 'gzip':
        stream = gzip.open(payload, 'rb')
    elif method == 'zstd':
        try:
            import zstandard as zstd
        except ImportError:
            zstd_bin = shutil.which('zstd')
            if not zstd_bin:
                raise RuntimeError('Zstandard verification needs pip install zstandard or zstd executable')
            proc = subprocess.Popen([zstd_bin, '-q', '-d', '-c', str(payload)], stdout=subprocess.PIPE)
            assert proc.stdout is not None
            with proc.stdout:
                for chunk in iter(lambda: proc.stdout.read(CHUNK), b''):
                    h.update(chunk)
            if proc.wait() != 0:
                raise RuntimeError('zstd CLI decompression failed')
            stream = None
        else:
            stream = zstd.ZstdDecompressor().stream_reader(payload.open('rb'))
    else:
        raise ValueError(f'Unknown lossless method: {method}')
    if stream is not None:
        with stream:
            for chunk in iter(lambda: stream.read(CHUNK), b''):
                h.update(chunk)
    if not hmac.compare_digest(h.hexdigest(), expected_source_hash):
        raise ValueError(f'{method} output does not round-trip to the source CSV bytes')
    return 'Decompressed CSV byte-for-byte identical to source'


def package_file_entry(path: Path, root: Path, role: str) -> dict:
    return {'path': path.relative_to(root).as_posix(), 'role': role,
            'bytes': path.stat().st_size, 'sha256': compute_checksum(path)}


def step_log(phase4: dict, method: str, k: int | None, codec: str,
             phase3: dict | None, feature_selection_label: str | None,
             removed_columns: list[str] | None = None) -> list[dict]:
    log = TransformationLog()
    if phase3 is not None:
        summary = {key: phase3[key] for key in (
            'threshold', 'missingness_threshold', 'patient_coverage_threshold',
            'clinical_review', 'method', 'criteria', 'retained_features') if key in phase3}
        summary.update({key: phase3.get('parameters', {}).get(key) for key in (
            'missingness_threshold', 'correlation_threshold', 'protected_columns')
            if key in phase3.get('parameters', {})})
        log.add('feature_selection', feature_selection_label or 'Phase 3 (metadata attached)', **summary)
    elif feature_selection_label:
        log.add('feature_selection', feature_selection_label, evidence='label supplied by user; Phase 3 metadata not available',
                removed_columns=removed_columns or [])
    elif removed_columns:
        log.add('feature_selection', 'undocumented',
                evidence='input column set differs from supplied full reference; selection criteria unknown',
                removed_columns=removed_columns)
    if method in ('pca', 'autoencoder'):
        log.add('imputation_for_fitting', 'median', missingness_restored_after_decoding=True)
        log.add('scaling', 'standard_scaler', model_fitted_in_phase4=True)
        log.add('dimensionality_reduction', method, latent_dimension=k,
                decoder_and_missingness_included_in_npz=True,
                original_measurements_reconstructed_approximately=True)
        log.add('serialization', 'npz', npz_wrapper_codec=codec,
                codec_comparison_uses_same_uncompressed_npy_members=True)
    else:
        log.add('lossless_packaging', method, information_preserved=True,
                parquet_is_table_lossless_not_original_csv_byte_identical=(method=='parquet'))
    log.add('transfer_package', 'tar_sha256_manifest', schema_version=SCHEMA_VERSION)
    return [asdict(step) for step in log.steps]


def payload_method_config(method: str, k: int | None, codec: str, phase4_dir: Path) -> tuple[Path, str]:
    if method in ('pca', 'autoencoder'):
        if k is None or k < 1:
            raise ValueError('PCA and autoencoder require --k >= 1')
        src = phase4_dir / f'{method}_k{k}_transfer_payload.npz'
        ext = ('.npz' if codec == 'native' else '.npz.gz' if codec == 'gzip' else '.npz.zst')
        return src, f'{method}_k{k}_transfer_payload{ext}'
    if k is not None:
        raise ValueError('--k is for PCA and autoencoders only')
    if codec != 'native':
        raise ValueError('Lossless Phase 4 formats already define their own codec; use --codec native')
    return phase4_dir / LOSSLESS_FILENAMES[method], LOSSLESS_FILENAMES[method]


def build(args: argparse.Namespace) -> tuple[Path, dict]:
    tick = time.perf_counter()
    phase4_dir, source = args.phase4_run.resolve(), args.source_csv.resolve()
    if not phase4_dir.is_dir() or not source.is_file():
        raise FileNotFoundError('Phase 4 folder and exact source CSV must exist')
    phase4_meta = load_json(phase4_dir / 'phase4_metadata.json')
    source_hash = compute_checksum(source)
    expected_hash = phase4_meta.get('source_sha256', '')
    if not hmac.compare_digest(source_hash, expected_hash):
        raise ValueError('Source CSV SHA-256 does not match this Phase 4 experiment; refusing to package')
    phase4_payload, output_basename = payload_method_config(args.method, args.k, args.codec, phase4_dir)
    original_phase4_hash = verify_existing_sidecar(phase4_payload)

    source_dictionary_file = load_json(args.dictionary_json) if args.dictionary_json else {}
    phase3 = load_json(args.phase3_metadata) if args.phase3_metadata else None
    if phase3 is not None:
        documented_hash = phase3.get('selected_dataset', {}).get('sha256')
        if documented_hash and not hmac.compare_digest(documented_hash, source_hash):
            raise ValueError('Phase 3 metadata selected-dataset SHA256 differs from Phase 4 input CSV')
    reference = args.full_reference_csv.resolve() if args.full_reference_csv else None
    if reference and not reference.is_file():
        raise FileNotFoundError(reference)
    if reference and phase3 is not None:
        documented_full_hash = phase3.get('source_dataset', {}).get('sha256')
        if documented_full_hash and not hmac.compare_digest(compute_checksum(reference), documented_full_hash):
            raise ValueError('Full reference CSV does not match Phase 3 metadata')
    diction = source_dictionary(source, phase4_meta, reference, source_dictionary_file, args.method)
    removed_columns = [entry['column'] for entry in diction if entry['role'] == 'removed_before_phase4']
    if args.method in ('pca', 'autoencoder'):
        for j in range(args.k):
            diction.append({
                'column': f'latent_{j+1:02d}', 'dtype': 'float32', 'role': 'derived_component',
                'preservation': 'compressed_representation',
                'source_columns': phase4_meta['encoded_predictors'],
                'unit': None, 'description': f'{args.method} latent coordinate {j+1}',
            })

    raw_label = args.package_name or f'{source.stem}_{args.method}' + (
        f'_k{args.k}_{args.codec}' if args.k else '')
    package_id = safe_filename(raw_label[:70] + '_' + stamp())
    out_root = args.output_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    root = out_root / package_id
    root.mkdir()
    data_dir = root / 'data'
    data_dir.mkdir()
    payload_dst = data_dir / output_basename
    try:
        packaging = (compress_npz(phase4_payload, payload_dst, args.codec)
                     if args.method in ('pca', 'autoencoder') else None)
        if packaging is None:
            shutil.copyfile(phase4_payload, payload_dst)
        # Preserve an independent checksum for each transferred file.
        payload_sidecar = write_sidecar(payload_dst)
        if args.method in ('pca', 'autoencoder'):
            if args.codec == 'native' and compute_checksum(payload_dst) != original_phase4_hash:
                raise AssertionError('Native NPZ modified during packaging')
            # Confirm expected Phase 4 decoder metadata without loading pickles.
            with np.load(phase4_payload, allow_pickle=False) as npz:
                inner = json.loads(str(npz['manifest_json'].item()))
                if inner['method'] != args.method or int(inner['k']) != args.k:
                    raise ValueError('Requested method/k does not match the verified Phase 4 NPZ')
                if int(inner['n_rows']) != int(phase4_meta['rows']):
                    raise ValueError('Phase 4 NPZ row count does not match Phase 4 metadata')
        else:
            inner = None
            roundtrip_note = validate_lossless_roundtrip(
                payload_dst, args.method, source, source_hash)
        file_inventory = [package_file_entry(payload_dst, root, 'clinical_payload'),
                          package_file_entry(payload_sidecar, root, 'checksum_sidecar')]
        for entry in args.extra or []:
            if '=' not in entry:
                raise ValueError('--extra must have NAME=PATH format')
            name, origin = entry.split('=', 1)
            safe_filename(name)
            source_extra = Path(origin).resolve()
            if not source_extra.is_file():
                raise FileNotFoundError(source_extra)
            dst = data_dir / name
            if dst.exists() or name in ('manifest.json', 'manifest.json.sha256'):
                raise ValueError(f'Duplicate extra file name: {name}')
            shutil.copyfile(source_extra, dst)
            file_inventory.append(package_file_entry(dst, root, 'companion_file'))

        records_by_file = {entry['path']: entry for entry in file_inventory}
        if len(records_by_file) != len(file_inventory):
            raise ValueError('Duplicate package members')
        manifest = {
            'schema_version': SCHEMA_VERSION,
            'created_utc': now_utc(),
            'package_id': package_id,
            'producer': '06_transfer_package.py',
            'study_phase': 'Phase 6 - transfer packaging and verification',
            'intended_handoff': 'University / Project 4 ingestion interface; ingestion not implemented',
            'source': {
                'filename': source.name,
                'sha256': source_hash,
                'bytes': source.stat().st_size,
                'rows': int(phase4_meta.get('rows', -1)),
                'patients': int(phase4_meta.get('patients', -1)),
                'columns': list(phase4_meta['original_columns']),
                'note': 'Original source CSV is NOT automatically included in the package',
                'reference_filename': reference.name if reference else None,
                'reference_sha256': compute_checksum(reference) if reference else None,
            },
            'representation': {
                'method': args.method,
                'k': args.k,
                'lossy': args.method in ('pca', 'autoencoder'),
                'container': 'npz' if args.method in ('pca','autoencoder') else args.method,
                'compression': ('deflate_npz' if args.codec == 'native' and args.method in ('pca', 'autoencoder')
                                and phase4_meta.get('bundle_compression') == 'deflate'
                                else 'native_npz' if args.codec == 'native' and args.method in ('pca', 'autoencoder')
                                else args.codec if args.method in ('pca', 'autoencoder')
                                else 'parquet_zstd' if args.method=='parquet' else
                                'gzip6' if args.method == 'gzip' else 'zstd3'),
                'phase4_original_payload_sha256': original_phase4_hash,
                'original_npz_array_members_preserved': bool(packaging and packaging['npz_member_hash_verified']),
                'input_feature_set': [entry['column'] for entry in diction if entry['role'] != 'derived_component'],
                'encoded_predictors': list(phase4_meta.get('encoded_predictors', [])),
                'preserved_exactly': list(phase4_meta.get('preserved_exactly', [])),
                'decompression_to_npz_needed': args.codec != 'native' if args.method in ('pca','autoencoder') else False,
                'receiver_requirements': (
                    'Verify archive + manifest, unpack; decompress NPZ if needed; use Phase 4 decoder (no refitting).'
                    if args.method in ('pca','autoencoder') else
                    'Verify archive + manifest; read CSV or Parquet with matching decoder; no approximation.'),
                'roundtrip_check': 'NPZ member data unchanged' if inner else roundtrip_note,
                'npz_internal_manifest': inner,
                'uncompressed_npz_bytes': packaging['uncompressed_npz_bytes'] if packaging else None,
            },
            'data_file': f'data/{output_basename}',
            'files': file_inventory,
            'data_dictionary': diction,
            'transformation_log': step_log(
                phase4_meta, args.method, args.k, args.codec, phase3, args.feature_selection_label, removed_columns),
            'dependencies': get_dependency_versions(),
            'integrity': {
                'algorithm': 'SHA-256',
                'manifest_checksum_sidecar': 'manifest.json.sha256',
                'verification_required_before_processing': True,
                'note': 'Hash integrity detects corruption; validate sender identity via authenticated SSH or signed provenance.',
            },
        }
        manifest_path = root / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        manifest_sidecar = write_sidecar(manifest_path)
        verify_directory(root)
        tarpath = out_root / f'{package_id}.tar'
        # TAR is an envelope, not an extra compressor. Payload sizes are measured as sent.
        with tarfile.open(tarpath, 'w', format=tarfile.PAX_FORMAT) as tar:
            for file in sorted(root.rglob('*')):
                if file.is_file():
                    tar.add(file, arcname=f'{package_id}/{file.relative_to(root).as_posix()}', recursive=False)
        tar_sidecar = write_sidecar(tarpath)
        verify_archive(tarpath)
        report = {
            'package_id': package_id,
            'method': args.method,
            'k': args.k,
            'codec': args.codec,
            'source_csv_bytes': source.stat().st_size,
            'payload_bytes': payload_dst.stat().st_size,
            'payload_sha256_sidecar_bytes': payload_sidecar.stat().st_size,
            'manifest_bytes': manifest_path.stat().st_size,
            'manifest_sha256_sidecar_bytes': manifest_sidecar.stat().st_size,
            'archive_bytes': tarpath.stat().st_size,
            'archive_sha256_sidecar_bytes': tar_sidecar.stat().st_size,
            'total_transmitted_bytes': tarpath.stat().st_size + tar_sidecar.stat().st_size,
            'package_elapsed_seconds': time.perf_counter() - tick,
            'archive_path': str(tarpath),
            'archive_verified': True,
        }
        # Report is outside the archive to avoid recursive self-checksum relationships.
        (out_root / f'{package_id}.package_report.json').write_text(json.dumps(report, indent=2)+'\n')
        return tarpath, report
    except Exception:
        # Do not leave half-valid artifacts masquerading as completed.
        shutil.rmtree(root, ignore_errors=True)
        for artifact in (out_root / f'{package_id}.tar', out_root / f'{package_id}.tar.sha256',
                         out_root / f'{package_id}.package_report.json'):
            artifact.unlink(missing_ok=True)
        raise


def manifest_files(manifest: dict) -> dict[str, dict]:
    if manifest.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Unsupported Phase 6 manifest schema')
    entries = manifest.get('files')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Package inventory is missing')
    answer = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid package entry')
        name = entry['path']
        valid_relative_file(name)
        if not name.startswith('data/') or name in answer:
            raise ValueError('File inventory contains invalid or duplicate data path')
        if not SHA_PATTERN.fullmatch(str(entry.get('sha256', ''))):
            raise ValueError('Invalid inventory SHA256')
        if int(entry.get('bytes', -1)) < 0:
            raise ValueError('Invalid inventory bytes')
        answer[name] = entry
    if manifest.get('data_file') not in answer:
        raise ValueError('Data payload is not listed in the manifest')
    sidecar = manifest['data_file'] + '.sha256'
    if sidecar not in answer:
        raise ValueError('Mandatory data payload checksum sidecar missing from manifest')
    return answer


def verify_directory(root: Path) -> dict:
    root = Path(root).resolve()
    manifest_file = root / 'manifest.json'
    sidecar = root / 'manifest.json.sha256'
    if not manifest_file.is_file() or not sidecar.is_file():
        raise FileNotFoundError('Manifest or mandatory manifest checksum sidecar missing')
    parse_sidecar_contents(sidecar.read_bytes(), manifest_file.name, compute_checksum(manifest_file))
    manifest = load_json(manifest_file)
    files = manifest_files(manifest)
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual_files != set(files) | {'manifest.json', 'manifest.json.sha256'}:
        raise ValueError('Package directory contains missing or unlisted files')
    for path, entry in files.items():
        target = root.joinpath(*valid_relative_file(path).parts)
        if target.is_symlink() or not target.is_file():
            raise ValueError(f'Unsafe or missing file: {path}')
        if target.stat().st_size != entry['bytes'] or not hmac.compare_digest(
                compute_checksum(target), entry['sha256']):
            raise ValueError(f'SHA256 or size mismatch: {path}')
    data_file = manifest['data_file']
    data_path = root.joinpath(*valid_relative_file(data_file).parts)
    data_sidecar = root.joinpath(*valid_relative_file(data_file + '.sha256').parts)
    parse_sidecar_contents(data_sidecar.read_bytes(), data_path.name, files[data_file]['sha256'])
    return manifest


def verify_archive(archive: Path) -> dict:
    archive = Path(archive).resolve()
    verify_existing_sidecar(archive)
    with tarfile.open(archive, 'r:') as tf:
        members = tf.getmembers()
        if not members or any(not m.isfile() for m in members):
            raise ValueError('Archive must contain regular files only')
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate paths inside archive')
        for name in names:
            valid_relative_file(name)
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise ValueError('Archive must have exactly one top-level package folder')
        root = roots.pop()
        map_members = {name[len(root)+1:]: tf.getmember(name) for name in names
                       if name.startswith(root+'/')}
        if len(map_members) != len(members):
            raise ValueError('Invalid archive member path')
        if 'manifest.json' not in map_members or 'manifest.json.sha256' not in map_members:
            raise ValueError('Manifest or checksum missing from archive')
        manifest_bytes = tf.extractfile(map_members['manifest.json']).read()
        parse_sidecar_contents(
            tf.extractfile(map_members['manifest.json.sha256']).read(),
            'manifest.json', hashlib.sha256(manifest_bytes).hexdigest())
        manifest = json.loads(manifest_bytes)
        if manifest.get('package_id') != root:
            raise ValueError('Archive root directory differs from manifest ID')
        files = manifest_files(manifest)
        expected = set(files) | {'manifest.json', 'manifest.json.sha256'}
        if expected != set(map_members):
            raise ValueError('Unexpected/missing package archive members')
        for name, entry in files.items():
            member = map_members[name]
            if member.size != entry['bytes']:
                raise ValueError(f'Size mismatch inside archive: {name}')
            digest = checksum_stream(tf.extractfile(member))
            if not hmac.compare_digest(digest, entry['sha256']):
                raise ValueError(f'Corrupted archive member: {name}')
        sidecar_name = manifest['data_file'] + '.sha256'
        sidecar_contents = tf.extractfile(map_members[sidecar_name]).read()
        parse_sidecar_contents(sidecar_contents, PurePosixPath(manifest['data_file']).name,
                               files[manifest['data_file']]['sha256'])
        return manifest


def unpack(archive: Path, output_dir: Path, recover_npz: bool = False) -> tuple[Path, dict]:
    manifest = verify_archive(archive)  # fail CLOSED before any extraction
    root = output_dir.resolve() / manifest['package_id']
    if root.exists():
        raise FileExistsError(f'Destination exists; refusing to overwrite: {root}')
    with tarfile.open(archive, 'r:') as tf:
        root.mkdir(parents=True)
        try:
            for member in tf.getmembers():
                safe = valid_relative_file(member.name)
                destination = output_dir.resolve().joinpath(*safe.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src, destination.open('wb') as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
            verify_directory(root)
            if recover_npz and manifest['representation']['method'] in ('pca', 'autoencoder'):
                data = root.joinpath(*valid_relative_file(manifest['data_file']).parts)
                fmt = manifest['representation']['compression']
                codec = 'native' if fmt in ('deflate_npz', 'native_npz') else fmt
                target_dir = output_dir.resolve() / f"{manifest['package_id']}_recovered"
                if target_dir.exists():
                    raise FileExistsError(f'Recovery destination exists: {target_dir}')
                target_dir.mkdir(parents=True)
                target = target_dir / (data.name.split('.npz')[0] + '.npz')
                decompress_npz(data, target, codec)
                # Validate original member bytes when possible: native = original file hash;
                # gzip/zstd member bytes were checked against source during packaging.
                with np.load(target, allow_pickle=False) as arrays:
                    inner = json.loads(str(arrays['manifest_json'].item()))
                    if inner.get('method') != manifest['representation']['method'] or inner.get('k') != manifest['representation']['k']:
                        raise ValueError('Recovered NPZ internal method/k does not match package manifest')
                write_sidecar(target)
                # The Phase 4 receiver accepts this NPZ and new mandatory checksum.
                print(f'Recovered Phase 4 NPZ: {target}')
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
    return root, manifest


def valid_ssh_target(target: str) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+', target):
        raise ValueError('Expected --remote user@hostname (no ssh:// prefix)')
    if target.startswith('-'):
        raise ValueError('Unsafe SSH destination')


def send(args: argparse.Namespace) -> list[dict]:
    archive = args.archive.resolve()
    manifest = verify_archive(archive)
    valid_ssh_target(args.remote)
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', args.remote_dir) or '..' in PurePosixPath(args.remote_dir).parts:
        raise ValueError('Remote directory must be an absolute POSIX path without spaces/shell metacharacters')
    threshold = args.repeat_threshold_seconds
    ssh_transport.required_trials(0, args.trials, threshold)
    sidecar = archive.with_name(archive.name+'.sha256')
    ssh_transport.configure_args(args, (args.report_csv or archive).parent)
    primary_file = args.report_csv or archive.with_suffix('.transfer_trials.csv')
    records = []
    for index, method in enumerate(ssh_transport.methods(getattr(args, 'ssh_transport', None) or 'scp')):
        report_file = primary_file if index == 0 else primary_file.with_suffix('.rsync.csv')
        trials = []
        report_file.parent.mkdir(parents=True, exist_ok=True)
        # Replace a previous partial report; it is never reused as proof of a new delivery.
        pd.DataFrame(columns=['trial', 'remote_sha256_verified']).to_csv(report_file, index=False)
        required = args.trials
        first_seconds = None
        for trial in range(1, args.trials+1):
            result = ssh_transport.deliver([archive, sidecar], args.remote, args.ssh_port,
                                           args.remote_dir, method=method, operation=f'Phase 6 {manifest["package_id"]} trial {trial}')
            if first_seconds is None:
                first_seconds = ssh_transport.cutoff_seconds(result)
                required = ssh_transport.required_trials(first_seconds, args.trials, threshold)
            report = {'package_id': manifest['package_id'], 'trial': trial,
                      'transport_selection':getattr(args,'ssh_transport',None) or 'scp',
                      'remote': args.remote, 'requested_trials': required,
                      'maximum_trials': args.trials, 'repeat_threshold_seconds': threshold,
                      'first_transfer_seconds': first_seconds, 'trial_policy': ssh_transport.TRIAL_POLICY,
                      'transmitted_bytes': archive.stat().st_size + sidecar.stat().st_size,
                      **result}
            trials.append(report)
            temp = report_file.with_suffix('.csv.tmp')
            pd.DataFrame(trials).to_csv(temp, index=False)
            temp.replace(report_file)
            print(f'Trial {trial}: verified and published; {result["attempts"]} attempt(s)')
            if trial == required:
                break
        records.extend(trials)
    print('Transfer trial report:', report_file)
    return records


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='Build a verified timestamped package from Phase 4 files')
    b.add_argument('--phase4-run', type=Path, required=True, help='Phase 4 experiment directory')
    b.add_argument('--source-csv', type=Path, required=True, help='EXACT CSV used in this Phase 4 run')
    b.add_argument('--method', choices=['gzip','zstd','parquet','pca','autoencoder'], required=True)
    b.add_argument('--k', type=int, help='Latent dimension, required for PCA/AE')
    b.add_argument('--codec', choices=['native','gzip','zstd'], default='native',
                   help='PCA/AE only: native NPZ or gzip/zstd on uncompressed NPZ')
    b.add_argument('--output-dir', type=Path, required=True)
    b.add_argument('--package-name', help='Optional safe package name prefix')
    b.add_argument('--feature-selection-label', help='Human-confirmed Phase 3 name, e.g. FS-95-C')
    b.add_argument('--phase3-metadata', type=Path, help='Optional Phase 3 provenance JSON')
    b.add_argument('--full-reference-csv', type=Path, help='Optional complete original CSV, to identify removed columns')
    b.add_argument('--dictionary-json', type=Path, help='Optional {column: {unit, description}} JSON')
    b.add_argument('--extra', action='append', metavar='NAME=PATH',
                   help='Optional companion file to checksum and include; repeatable')
    v = sub.add_parser('verify', help='Fail-closed verify .tar + sidecar or extracted directory')
    v.add_argument('path', type=Path)
    u = sub.add_parser('unpack', help='Verify archive then safely unpack')
    u.add_argument('archive', type=Path)
    u.add_argument('--output-dir', type=Path, required=True)
    u.add_argument('--recover-npz', action='store_true',
                   help='Also restore .npz with a newly generated .npz.sha256 for Phase 4 receiver')
    s = sub.add_parser('send', help='SCP to SSH host and verify remote SHA-256; record real timings')
    s.add_argument('archive', type=Path)
    s.add_argument('--remote', required=True, help='user@hostname')
    s.add_argument('--ssh-port', type=int, default=22, help='SSH port (default: 22)')
    s.add_argument('--remote-dir', required=True, help='Absolute destination directory')
    s.add_argument('--trials', type=int, default=10, help='Maximum benchmark trials, default 10')
    s.add_argument('--repeat-threshold-seconds', type=float, default=10.0,
                   help='Continue trials only if first successful SCP <= threshold seconds, default 10')
    s.add_argument('--report-csv', type=Path)
    ssh_transport.add_arguments(s)
    return p


def main() -> None:
    args = parser().parse_args()
    if args.command == 'build':
        archive, report = build(args)
        print('PACKAGE CREATED:', archive)
        print(f"Validated transmitted bytes (archive + SHA256): {report['total_transmitted_bytes']:,}")
        print(f"Payload alone: {report['payload_bytes']:,} bytes; package seconds: {report['package_elapsed_seconds']:.4f}")
    elif args.command == 'verify':
        manifest = verify_directory(args.path) if args.path.is_dir() else verify_archive(args.path)
        print('VERIFIED:', manifest['package_id'], manifest['representation']['method'])
    elif args.command == 'unpack':
        root, manifest = unpack(args.archive, args.output_dir, args.recover_npz)
        print('VERIFIED AND UNPACKED:', root)
        print('Method:', manifest['representation']['method'])
    elif args.command == 'send':
        send(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, AssertionError, subprocess.CalledProcessError) as exc:
        sys.exit(f'ERROR: {exc}')

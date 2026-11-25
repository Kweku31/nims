#!/usr/bin/env python3
"""Execute verified Phase 6 recovery ON THE RECEIVING HOST.

Install the same thesis_pipeline/legacy source on the receiver. The receiver
must have required Python dependencies and access to the verified SCP directory.
Only explicit aggregate timings and hashes are returned to the sender; clinical
rows stay on the receiver. No model is fit on the receiver.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from thesis_pipeline.core import LEGACY

MARKER = 'THESIS_RECEIVER_RESULT_JSON='


def load_module(stem: str, name: str):
    script = LEGACY / stem
    if not script.is_file():
        raise FileNotFoundError(f'Receiver engine missing: {script}')
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def recover(archive: Path, output_dir: Path, expected_rows: int) -> dict:
    """Verify + unpack + reconstruct, persisting recovered data on the server."""
    if expected_rows < 1:
        raise ValueError('expected-rows must be positive')
    if not archive.is_file():
        raise FileNotFoundError(f'Server-side archive not found: {archive}')
    if output_dir.exists():
        raise FileExistsError(f'Refusing to overwrite receiver recovery: {output_dir}')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(mode=0o700)

    package = load_module('06_transfer_package.py', 'thesis_server_package')
    began = time.perf_counter()
    t0 = time.perf_counter()
    # Existing package logic checks tar SHA256, manifest, member hashes and
    # payload sidecars before unpacking anything.
    root, manifest = package.unpack(archive, output_dir, recover_npz=True)
    unpack_seconds = time.perf_counter() - t0
    method = manifest['representation']['method']
    k = manifest['representation'].get('k')

    # Module initialization is receiver setup, not the decoder's per-payload runtime.
    decoder = (load_module('04_dimensionality_reduction_updated.py', 'thesis_server_decoder')
               if method in ('pca', 'autoencoder') else None)
    recovered = output_dir / 'reconstructed.csv'
    output_already_written = False
    t0 = time.perf_counter()
    if method in ('pca', 'autoencoder'):
        matches = list(output_dir.rglob(f'{method}_k{k}_transfer_payload.npz'))
        matches = [p for p in matches if p.parent.name.endswith('_recovered')]
        if len(matches) != 1:
            raise RuntimeError(f'Expected one recovered NPZ; found {len(matches)}')
        decoder.verify_payload_checksum(matches[0])
        data = decoder.reconstruct_bundle(matches[0])
    else:
        payload = root / manifest['data_file']
        if method == 'gzip':
            # Stream the ORIGINAL bytes, not a pandas CSV reserialization.
            with gzip.open(payload, 'rb') as fin, recovered.open('wb') as fout:
                shutil.copyfileobj(fin, fout, 1024 * 1024)
            data = pd.read_csv(recovered, low_memory=False)
            output_already_written = True
        elif method == 'zstd':
            try:
                import zstandard as zstd
            except ImportError:
                zstd_executable = shutil.which('zstd')
                if not zstd_executable:
                    raise RuntimeError('zstandard module or zstd executable required on receiver')
                with recovered.open('wb') as out:
                    subprocess.run([zstd_executable,'-q','-d','-c',str(payload)], stdout=out, check=True)
                data = pd.read_csv(recovered, low_memory=False)
                output_already_written = True
            else:
                with payload.open('rb') as stream:
                    with zstd.ZstdDecompressor().stream_reader(stream) as reader:
                        with recovered.open('wb') as fout:
                            shutil.copyfileobj(reader, fout, 1024 * 1024)
                data = pd.read_csv(recovered, low_memory=False)
                output_already_written = True
        elif method == 'parquet':
            data = pd.read_parquet(payload)
        else:
            raise ValueError(f'Unsupported representation: {method}')
    reconstruction_seconds = time.perf_counter() - t0
    if len(data) != expected_rows:
        raise AssertionError(f'Server reconstructed {len(data)} rows; expected {expected_rows}')

    if output_already_written:
        persistence_seconds = 0.0  # Raw stream write included in decompression time.
        if digest(recovered) != manifest['source']['sha256']:
            raise RuntimeError('Lossless CSV bytes differ from the original dataset SHA-256')
    else:
        t0 = time.perf_counter()
        data.to_csv(recovered, index=False)
        persistence_seconds = time.perf_counter() - t0
    # Data values are NOT returned over SSH. Do not assume the CSV is byte-equal
    # to the input for PCA/AE (lossy) or for a Parquet-to-CSV conversion.
    result = {
        'receiver_execution_role': 'receiver_host',
        'receiver_recovery_passed': True,
        'receiver_package_sha256_verified': True,
        'package_id': manifest['package_id'],
        'method': method,
        'k': k,
        'reconstructed_rows': int(len(data)),
        'reconstructed_columns': int(len(data.columns)),
        'unpack_seconds_MEASURED_ON_SERVER': unpack_seconds,
        'reconstruct_or_decompress_seconds_MEASURED_ON_SERVER': reconstruction_seconds,
        'csv_write_seconds_MEASURED_ON_SERVER': persistence_seconds,
        'receiver_processing_seconds_MEASURED_ON_SERVER': time.perf_counter() - began,
        'reconstructed_csv_bytes': recovered.stat().st_size,
        'reconstructed_csv_sha256': digest(recovered),
        'reconstructed_csv_path': str(recovered),
    }
    (output_dir / 'receiver_report.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--expected-rows', type=int, required=True)
    args = parser.parse_args()
    result = recover(args.archive.resolve(), args.output_dir.resolve(), args.expected_rows)
    print(MARKER + json.dumps(result, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()

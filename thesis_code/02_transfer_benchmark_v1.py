"""
02_transfer_benchmark.py

Phase 2 - Baseline Transfer Benchmark

Thesis:
Efficient Dimensionality Reduction and Compression Strategies
for Large-Scale Clinical Data Transfer Between Hospitals and
University Data Centers.

Purpose
-------
Benchmark different representations of the ORIGINAL dataset
before dimensionality reduction or feature selection.

Representations
---------------
1. Original source
2. CSV
3. CSV + gzip
4. Parquet
5. CSV + Zstandard

Experimental stages
-------------------
A. Packaging benchmark
   - repeated locally
   - mean, median, sample SD

B. Transfer benchmark
   - simulated OR real SSH/SCP transfer
   - repeated using the SAME fixed artifact
   - mean, median, sample SD
   - throughput

C. Integrity verification
   - SHA-256 sender vs receiver
   - kept separate from transfer timing

Important
---------
Receiver-side ingestion is NOT included in the real transfer
benchmark unless a future experiment explicitly executes
ingestion on the receiving machine.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import shutil
import statistics
import subprocess
import sys
import time

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# Optional dependencies
# ============================================================

try:
    import pyarrow  # noqa: F401
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False


try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False


# ============================================================
# Data structures
# ============================================================

@dataclass
class Artifact:
    format_name: str
    path: Path
    available: bool = True
    note: str = ""

    @property
    def file_bytes(self) -> int:
        if not self.available:
            return 0

        if not self.path.exists():
            return 0

        return self.path.stat().st_size


@dataclass
class PackagingResult:
    artifact: Artifact
    times: list[float]


@dataclass
class TransferMeasurement:
    transfer_seconds: float
    throughput_mbps: float
    integrity_verified: bool | None
    verification_seconds: float | None


# ============================================================
# Statistical helpers
# ============================================================

def mean(values: list[float]) -> float:
    if not values:
        return float("nan")

    return statistics.mean(values)


def median(values: list[float]) -> float:
    if not values:
        return float("nan")

    return statistics.median(values)


def stdev(values: list[float]) -> float:
    """
    Sample standard deviation.

    For a single observation SD is defined here as zero because
    there is no run-to-run variation to estimate.
    """

    if len(values) < 2:
        return 0.0

    return statistics.stdev(values)


# ============================================================
# General utilities
# ============================================================

def human_size(size_bytes: int) -> str:

    size = float(size_bytes)

    for unit in [
        "B",
        "KB",
        "MB",
        "GB",
        "TB"
    ]:

        if size < 1024:
            return f"{size:.2f} {unit}"

        size /= 1024

    return f"{size:.2f} PB"


def calculate_file_sha256(
    file_path: str | Path,
    chunk_size: int = 1024 * 1024
) -> str:

    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:

        while True:

            chunk = file.read(chunk_size)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


def calculate_throughput_mbps(
    payload_bytes: int,
    transfer_seconds: float
) -> float:

    if transfer_seconds <= 0:
        return float("nan")

    return (
        payload_bytes * 8
    ) / (
        transfer_seconds * 1_000_000
    )


def simulate_transmission_time(
    payload_bytes: int,
    bandwidth_mbps: float
) -> float:

    if bandwidth_mbps <= 0:
        raise ValueError(
            "Bandwidth must be greater than zero."
        )

    return (
        payload_bytes * 8
    ) / (
        bandwidth_mbps * 1_000_000
    )


# ============================================================
# Dataset loading
# ============================================================

def load_dataset(
    file_path: str | Path
) -> tuple[pd.DataFrame, float, int]:

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Dataset path is not a file: {path}"
        )

    input_bytes = path.stat().st_size

    suffixes = [
        suffix.lower()
        for suffix in path.suffixes
    ]

    print("\nReading dataset into memory once...")

    start = time.perf_counter()

    if suffixes[-2:] == [".csv", ".gz"]:

        df = pd.read_csv(
            path,
            low_memory=False
        )

    elif path.suffix.lower() == ".csv":

        df = pd.read_csv(
            path,
            low_memory=False
        )

    elif path.suffix.lower() == ".parquet":

        df = pd.read_parquet(path)

    elif path.suffix.lower() in [
        ".xlsx",
        ".xls"
    ]:

        df = pd.read_excel(path)

    else:

        raise ValueError(
            "Unsupported dataset format. "
            "Supported: .csv, .csv.gz, "
            ".parquet, .xlsx, .xls"
        )

    elapsed = time.perf_counter() - start

    return df, elapsed, input_bytes


# ============================================================
# Experiment directory
# ============================================================

def create_run_directory(
    dataset_path: Path,
    output_dir: str
) -> tuple[Path, Path, str]:

    if dataset_path.name.lower().endswith(
        ".csv.gz"
    ):

        dataset_name = (
            dataset_path.name[:-7]
        )

    else:

        dataset_name = dataset_path.stem

    now = datetime.now(timezone.utc)

    folder_timestamp = now.strftime(
        "%Y%m%d_%H%M%S"
    )

    timestamp_iso = now.isoformat()

    run_directory = (
        Path(output_dir)
        / f"{dataset_name}_{folder_timestamp}"
    )

    artifacts_directory = (
        run_directory
        / "artifacts"
    )

    artifacts_directory.mkdir(
        parents=True,
        exist_ok=False
    )

    return (
        run_directory,
        artifacts_directory,
        timestamp_iso
    )


# ============================================================
# Individual packaging operations
# ============================================================

def package_csv(
    df: pd.DataFrame,
    path: Path
) -> float:

    start = time.perf_counter()

    df.to_csv(
        path,
        index=False
    )

    return time.perf_counter() - start


def package_gzip(
    df: pd.DataFrame,
    path: Path,
    compresslevel: int
) -> float:

    start = time.perf_counter()

    with gzip.open(
        path,
        "wt",
        encoding="utf-8",
        compresslevel=compresslevel
    ) as file:

        df.to_csv(
            file,
            index=False
        )

    return time.perf_counter() - start


def package_parquet(
    df: pd.DataFrame,
    path: Path
) -> float:

    start = time.perf_counter()

    df.to_parquet(
        path,
        index=False
    )

    return time.perf_counter() - start


def package_zstd(
    df: pd.DataFrame,
    path: Path,
    level: int
) -> float:

    start = time.perf_counter()

    csv_bytes = (
        df.to_csv(index=False)
        .encode("utf-8")
    )

    compressor = zstd.ZstdCompressor(
        level=level
    )

    compressed = compressor.compress(
        csv_bytes
    )

    path.write_bytes(compressed)

    return time.perf_counter() - start


# ============================================================
# Packaging benchmark
# ============================================================

def benchmark_packaging(
    df: pd.DataFrame,
    source_path: Path,
    artifacts_directory: Path,
    runs: int,
    gzip_level: int,
    zstd_level: int
) -> list[PackagingResult]:

    print("\n" + "=" * 90)
    print("PACKAGING BENCHMARK")
    print("=" * 90)

    results: list[PackagingResult] = []

    # --------------------------------------------------------
    # Original source
    # --------------------------------------------------------

    original_path = (
        artifacts_directory
        / f"original_{source_path.name}"
    )

    # Copying is NOT considered packaging.
    # The source already exists in transferable form.
    shutil.copy2(
        source_path,
        original_path
    )

    original = Artifact(
        format_name="original_source",
        path=original_path,
        note=(
            "Original source artifact. "
            "No packaging transformation."
        )
    )

    results.append(
        PackagingResult(
            artifact=original,
            times=[0.0] * runs
        )
    )

    print(
        f"\noriginal_source: "
        f"{human_size(original.file_bytes)} "
        "(no packaging)"
    )

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    csv_path = (
        artifacts_directory
        / "dataset.csv"
    )

    csv_times = []

    print("\nCSV")

    for run in range(1, runs + 1):

        elapsed = package_csv(
            df,
            csv_path
        )

        csv_times.append(elapsed)

        print(
            f"  Run {run:02d}: "
            f"{elapsed:.6f} s"
        )

    results.append(
        PackagingResult(
            artifact=Artifact(
                format_name="csv",
                path=csv_path,
                note="Pandas CSV serialization."
            ),
            times=csv_times
        )
    )

    # --------------------------------------------------------
    # gzip
    # --------------------------------------------------------

    gzip_path = (
        artifacts_directory
        / "dataset.csv.gz"
    )

    gzip_times = []

    print("\nCSV + gzip")

    for run in range(1, runs + 1):

        elapsed = package_gzip(
            df,
            gzip_path,
            gzip_level
        )

        gzip_times.append(elapsed)

        print(
            f"  Run {run:02d}: "
            f"{elapsed:.6f} s"
        )

    results.append(
        PackagingResult(
            artifact=Artifact(
                format_name="csv_gzip",
                path=gzip_path,
                note=(
                    f"CSV + gzip level "
                    f"{gzip_level}."
                )
            ),
            times=gzip_times
        )
    )

    # --------------------------------------------------------
    # Parquet
    # --------------------------------------------------------

    parquet_path = (
        artifacts_directory
        / "dataset.parquet"
    )

    if HAS_PARQUET:

        parquet_times = []

        print("\nParquet")

        for run in range(
            1,
            runs + 1
        ):

            elapsed = package_parquet(
                df,
                parquet_path
            )

            parquet_times.append(
                elapsed
            )

            print(
                f"  Run {run:02d}: "
                f"{elapsed:.6f} s"
            )

        results.append(
            PackagingResult(
                artifact=Artifact(
                    format_name="parquet",
                    path=parquet_path,
                    note=(
                        "Parquet via "
                        "pandas/pyarrow."
                    )
                ),
                times=parquet_times
            )
        )

    else:

        results.append(
            PackagingResult(
                artifact=Artifact(
                    format_name="parquet",
                    path=parquet_path,
                    available=False,
                    note=(
                        "pyarrow is not "
                        "installed."
                    )
                ),
                times=[]
            )
        )

        print(
            "\nParquet: UNAVAILABLE "
            "(install pyarrow)"
        )

    # --------------------------------------------------------
    # Zstandard
    # --------------------------------------------------------

    zstd_path = (
        artifacts_directory
        / "dataset.csv.zst"
    )

    if HAS_ZSTD:

        zstd_times = []

        print("\nCSV + Zstandard")

        for run in range(
            1,
            runs + 1
        ):

            elapsed = package_zstd(
                df,
                zstd_path,
                zstd_level
            )

            zstd_times.append(
                elapsed
            )

            print(
                f"  Run {run:02d}: "
                f"{elapsed:.6f} s"
            )

        results.append(
            PackagingResult(
                artifact=Artifact(
                    format_name="csv_zstd",
                    path=zstd_path,
                    note=(
                        f"CSV + Zstandard "
                        f"level {zstd_level}."
                    )
                ),
                times=zstd_times
            )
        )

    else:

        results.append(
            PackagingResult(
                artifact=Artifact(
                    format_name="csv_zstd",
                    path=zstd_path,
                    available=False,
                    note=(
                        "zstandard is not "
                        "installed."
                    )
                ),
                times=[]
            )
        )

        print(
            "\nZstandard: UNAVAILABLE "
            "(install zstandard)"
        )

    return results


# ============================================================
# Remote SSH utilities
# ============================================================

def run_ssh_command(
    host: str,
    user: str,
    port: int,
    remote_command: str
) -> subprocess.CompletedProcess:

    command = [
        "ssh",
        "-p",
        str(port),
        f"{user}@{host}",
        remote_command,
    ]

    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )


def ensure_remote_directory(
    host: str,
    user: str,
    port: int,
    remote_dir: str
) -> None:

    # Quote only the directory argument.
    remote_command = (
        f"mkdir -p "
        f"{shell_quote(remote_dir)}"
    )

    run_ssh_command(
        host,
        user,
        port,
        remote_command
    )


def shell_quote(value: str) -> str:
    """
    Minimal POSIX shell quoting for a remote command.
    """

    return (
        "'"
        + value.replace(
            "'",
            "'\"'\"'"
        )
        + "'"
    )


def remove_remote_file(
    host: str,
    user: str,
    port: int,
    remote_path: str
) -> None:

    remote_command = (
        f"rm -f "
        f"{shell_quote(remote_path)}"
    )

    run_ssh_command(
        host,
        user,
        port,
        remote_command
    )


def get_remote_sha256(
    host: str,
    user: str,
    port: int,
    remote_path: str
) -> tuple[str, float]:

    start = time.perf_counter()

    remote_command = (
        f"sha256sum "
        f"{shell_quote(remote_path)}"
    )

    result = run_ssh_command(
        host,
        user,
        port,
        remote_command
    )

    verification_seconds = (
        time.perf_counter()
        - start
    )

    checksum = (
        result.stdout
        .strip()
        .split()[0]
    )

    return (
        checksum,
        verification_seconds
    )


# ============================================================
# Transfer implementations
# ============================================================

def simulated_transfer(
    artifact: Artifact,
    bandwidth_mbps: float
) -> TransferMeasurement:

    transfer_seconds = (
        simulate_transmission_time(
            artifact.file_bytes,
            bandwidth_mbps
        )
    )

    # The simulated model assumes exactly
    # the requested bandwidth.
    throughput = bandwidth_mbps

    return TransferMeasurement(
        transfer_seconds=transfer_seconds,
        throughput_mbps=throughput,
        integrity_verified=None,
        verification_seconds=None
    )


def real_transfer(
    artifact: Artifact,
    host: str,
    user: str,
    port: int,
    remote_dir: str
) -> TransferMeasurement:

    remote_path = (
        f"{remote_dir.rstrip('/')}/"
        f"{artifact.path.name}"
    )

    # Calculate sender checksum BEFORE transfer.
    # It is deliberately outside transfer timing.
    local_checksum = (
        calculate_file_sha256(
            artifact.path
        )
    )

    # Remove previous remote copy so each
    # trial transfers the complete artifact.
    remove_remote_file(
        host=host,
        user=user,
        port=port,
        remote_path=remote_path
    )

    destination = (
        f"{user}@{host}:"
        f"{remote_path}"
    )

    command = [
        "scp",
        "-P",
        str(port),
        str(artifact.path),
        destination,
    ]

    # --------------------------------------------------------
    # ONLY actual SCP execution is timed.
    # --------------------------------------------------------

    start = time.perf_counter()

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    transfer_seconds = (
        time.perf_counter()
        - start
    )

    throughput = (
        calculate_throughput_mbps(
            artifact.file_bytes,
            transfer_seconds
        )
    )

    # --------------------------------------------------------
    # Receiver integrity verification.
    # NOT included in transfer time.
    # --------------------------------------------------------

    (
        remote_checksum,
        verification_seconds
    ) = get_remote_sha256(
        host=host,
        user=user,
        port=port,
        remote_path=remote_path
    )

    integrity_verified = (
        local_checksum
        == remote_checksum
    )

    return TransferMeasurement(
        transfer_seconds=transfer_seconds,
        throughput_mbps=throughput,
        integrity_verified=integrity_verified,
        verification_seconds=verification_seconds
    )


# ============================================================
# Transfer benchmark
# ============================================================

def benchmark_transfer(
    artifact: Artifact,
    args: argparse.Namespace
) -> tuple[
    list[float],
    list[float],
    list[float],
    list[bool]
]:

    transfer_times = []
    throughputs = []
    verification_times = []
    integrity_results = []

    print(
        f"\nTransfer: "
        f"{artifact.format_name}"
    )

    print(
        f"Artifact size: "
        f"{human_size(artifact.file_bytes)}"
    )

    for run in range(
        1,
        args.transfer_runs + 1
    ):

        if args.transfer_mode == "simulated":

            measurement = (
                simulated_transfer(
                    artifact,
                    args.bandwidth_mbps
                )
            )

        else:

            measurement = real_transfer(
                artifact=artifact,
                host=args.host,
                user=args.user,
                port=args.port,
                remote_dir=args.remote_dir
            )

        transfer_times.append(
            measurement.transfer_seconds
        )

        throughputs.append(
            measurement.throughput_mbps
        )

        if (
            measurement.verification_seconds
            is not None
        ):

            verification_times.append(
                measurement.verification_seconds
            )

        if (
            measurement.integrity_verified
            is not None
        ):

            integrity_results.append(
                measurement.integrity_verified
            )

        print(
            f"  Run {run:02d}: "
            f"transfer="
            f"{measurement.transfer_seconds:.6f}s, "
            f"throughput="
            f"{measurement.throughput_mbps:.3f} Mbps",
            end=""
        )

        if (
            measurement.integrity_verified
            is not None
        ):

            status = (
                "PASS"
                if measurement.integrity_verified
                else "FAIL"
            )

            print(
                f", integrity={status}"
            )

        else:

            print()

    return (
        transfer_times,
        throughputs,
        verification_times,
        integrity_results
    )


# ============================================================
# Raw trial records
# ============================================================

def add_trial_rows(
    rows: list[dict],
    format_name: str,
    stage: str,
    values: list[float],
    unit: str
) -> None:

    for run_number, value in enumerate(
        values,
        start=1
    ):

        rows.append({
            "format":
                format_name,

            "stage":
                stage,

            "run":
                run_number,

            "value":
                value,

            "unit":
                unit,
        })


# ============================================================
# Summary construction
# ============================================================

def create_summary_row(
    packaging_result: PackagingResult,
    transfer_times: list[float],
    throughputs: list[float],
    verification_times: list[float],
    integrity_results: list[bool],
    source_bytes: int,
    transfer_mode: str
) -> dict:

    artifact = packaging_result.artifact

    ratio = (
        artifact.file_bytes
        / source_bytes
    )

    reduction = (
        1.0 - ratio
    ) * 100

    packaging_times = (
        packaging_result.times
    )

    return {

        "format":
            artifact.format_name,

        "file_bytes":
            artifact.file_bytes,

        "file_mb":
            artifact.file_bytes
            / (1024 ** 2),

        "size_ratio_vs_source":
            ratio,

        "size_reduction_pct":
            reduction,

        # Packaging
        "packaging_runs":
            len(packaging_times),

        "packaging_mean_seconds":
            mean(packaging_times),

        "packaging_median_seconds":
            median(packaging_times),

        "packaging_std_seconds":
            stdev(packaging_times),

        # Transfer
        "transfer_mode":
            transfer_mode,

        "transfer_runs":
            len(transfer_times),

        "transfer_mean_seconds":
            mean(transfer_times),

        "transfer_median_seconds":
            median(transfer_times),

        "transfer_std_seconds":
            stdev(transfer_times),

        # Throughput
        "throughput_mean_mbps":
            mean(throughputs),

        "throughput_median_mbps":
            median(throughputs),

        "throughput_std_mbps":
            stdev(throughputs),

        # Integrity verification
        "verification_mean_seconds":
            (
                mean(verification_times)
                if verification_times
                else float("nan")
            ),

        "verification_std_seconds":
            (
                stdev(verification_times)
                if verification_times
                else float("nan")
            ),

        "integrity_verified":
            (
                all(integrity_results)
                if integrity_results
                else None
            ),

        "note":
            artifact.note,
    }


# ============================================================
# Console results
# ============================================================

def print_summary(
    results: pd.DataFrame,
    args: argparse.Namespace
) -> None:

    print("\n" + "=" * 110)
    print("PHASE 2 SUMMARY")
    print("=" * 110)

    print(
        f"\nTransfer mode    : "
        f"{args.transfer_mode}"
    )

    print(
        f"Packaging runs   : "
        f"{args.packaging_runs}"
    )

    print(
        f"Transfer runs    : "
        f"{args.transfer_runs}"
    )

    if args.transfer_mode == "simulated":

        print(
            f"Simulated bandwidth: "
            f"{args.bandwidth_mbps:.2f} Mbps"
        )

    columns = [
        "format",
        "file_mb",
        "size_reduction_pct",
        "packaging_mean_seconds",
        "packaging_std_seconds",
        "transfer_mean_seconds",
        "transfer_std_seconds",
        "throughput_mean_mbps",
        "throughput_std_mbps",
        "integrity_verified",
    ]

    print()

    print(
        results[columns].to_string(
            index=False,
            float_format=lambda x: (
                f"{x:.6f}"
            )
        )
    )


# ============================================================
# Metadata
# ============================================================

def save_metadata(
    run_directory: Path,
    source_path: Path,
    source_sha256: str,
    source_bytes: int,
    df: pd.DataFrame,
    load_seconds: float,
    timestamp: str,
    args: argparse.Namespace
) -> None:

    metadata = {

        "experiment": {
            "phase":
                "Phase 2 - Baseline Transfer Benchmark",

            "timestamp_utc":
                timestamp,

            "script":
                "02_transfer_benchmark.py",
        },

        "dataset": {
            "filename":
                source_path.name,

            "absolute_path":
                str(source_path),

            "sha256":
                source_sha256,

            "rows":
                int(df.shape[0]),

            "columns":
                int(df.shape[1]),

            "input_file_bytes":
                source_bytes,

            "dataframe_memory_bytes":
                int(
                    df.memory_usage(
                        index=True,
                        deep=True
                    ).sum()
                ),
        },

        "experiment_parameters": {
            "packaging_runs":
                args.packaging_runs,

            "transfer_runs":
                args.transfer_runs,

            "transfer_mode":
                args.transfer_mode,

            "simulated_bandwidth_mbps":
                (
                    args.bandwidth_mbps
                    if args.transfer_mode
                    == "simulated"
                    else None
                ),

            "gzip_level":
                args.gzip_level,

            "zstd_level":
                args.zstd_level,
        },

        "remote_endpoint": {
            "host":
                (
                    args.host
                    if args.transfer_mode
                    == "ssh"
                    else None
                ),

            "user":
                (
                    args.user
                    if args.transfer_mode
                    == "ssh"
                    else None
                ),

            "port":
                (
                    args.port
                    if args.transfer_mode
                    == "ssh"
                    else None
                ),

            "remote_directory":
                (
                    args.remote_dir
                    if args.transfer_mode
                    == "ssh"
                    else None
                ),
        },

        "environment": {
            "python":
                platform.python_version(),

            "pandas":
                pd.__version__,

            "numpy":
                np.__version__,

            "operating_system":
                platform.system(),

            "os_release":
                platform.release(),

            "machine":
                platform.machine(),

            "pyarrow_available":
                HAS_PARQUET,

            "zstandard_available":
                HAS_ZSTD,
        },

        "timing": {
            "dataset_load_seconds":
                load_seconds,
        },

        "methodology": {
            "feature_selection":
                False,

            "dimensionality_reduction":
                False,

            "packaging_repeated":
                True,

            "fixed_artifact_used_for_transfer":
                True,

            "receiver_ingestion_measured":
                False,

            "integrity_algorithm":
                "SHA-256",

            "integrity_verification_excluded_from_transfer_time":
                True,

            "simulated_transfer_formula":
                (
                    "payload_bytes * 8 / "
                    "(bandwidth_mbps * 1,000,000)"
                ),
        },

        "command_line": {
            "argv":
                sys.argv,
        },
    }

    path = (
        run_directory
        / "transfer_metadata.json"
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            metadata,
            file,
            indent=2
        )


# ============================================================
# CLI
# ============================================================

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Phase 2 baseline clinical-data "
            "transfer benchmark."
        )
    )

    parser.add_argument(
        "dataset",
        help="Input clinical dataset."
    )

    parser.add_argument(
        "--transfer-mode",
        choices=[
            "simulated",
            "ssh"
        ],
        default="simulated",
        help=(
            "simulated or real SSH/SCP "
            "transfer."
        )
    )

    parser.add_argument(
        "--packaging-runs",
        type=int,
        default=10,
        help=(
            "Number of local packaging "
            "repetitions (default: 10)."
        )
    )

    parser.add_argument(
        "--transfer-runs",
        type=int,
        default=10,
        help=(
            "Number of transfer repetitions "
            "(default: 10)."
        )
    )

    parser.add_argument(
        "--bandwidth-mbps",
        type=float,
        default=100.0,
        help=(
            "Bandwidth for simulated transfer "
            "(default: 100 Mbps)."
        )
    )

    parser.add_argument(
        "--gzip-level",
        type=int,
        default=6,
        choices=range(1, 10),
        metavar="1-9",
        help="gzip compression level."
    )

    parser.add_argument(
        "--zstd-level",
        type=int,
        default=3,
        help="Zstandard compression level."
    )

    parser.add_argument(
        "--host",
        help="Remote SSH host."
    )

    parser.add_argument(
        "--user",
        help="Remote SSH username."
    )

    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="SSH port."
    )

    parser.add_argument(
        "--remote-dir",
        default="/tmp/thesis_transfer",
        help="Remote destination directory."
    )

    parser.add_argument(
        "--output-dir",
        default="output/transfer",
        help="Local output directory."
    )

    args = parser.parse_args()

    if args.packaging_runs < 1:

        parser.error(
            "--packaging-runs must be >= 1"
        )

    if args.transfer_runs < 1:

        parser.error(
            "--transfer-runs must be >= 1"
        )

    if (
        args.transfer_mode == "simulated"
        and args.bandwidth_mbps <= 0
    ):

        parser.error(
            "--bandwidth-mbps must be > 0"
        )

    if args.transfer_mode == "ssh":

        if not args.host:
            parser.error(
                "--host is required "
                "for SSH transfer."
            )

        if not args.user:
            parser.error(
                "--user is required "
                "for SSH transfer."
            )

    return args


# ============================================================
# Main experiment
# ============================================================

def main() -> None:

    args = parse_arguments()

    print("=" * 100)
    print(
        "PHASE 2 - BASELINE TRANSFER BENCHMARK"
    )
    print("=" * 100)

    source_path = Path(
        args.dataset
    ).resolve()

    # --------------------------------------------------------
    # Load once
    # --------------------------------------------------------

    (
        df,
        load_seconds,
        source_bytes
    ) = load_dataset(source_path)

    dataframe_memory = int(
        df.memory_usage(
            index=True,
            deep=True
        ).sum()
    )

    print("\nDataset:")
    print(
        f"  {source_path}"
    )

    print(
        f"Rows        : {len(df):,}"
    )

    print(
        f"Columns     : {len(df.columns):,}"
    )

    print(
        f"Source size : "
        f"{human_size(source_bytes)}"
    )

    print(
        f"DataFrame   : "
        f"{human_size(dataframe_memory)}"
    )

    print(
        f"Load time   : "
        f"{load_seconds:.6f} s"
    )

    # --------------------------------------------------------
    # Output directory
    # --------------------------------------------------------

    (
        run_directory,
        artifacts_directory,
        timestamp
    ) = create_run_directory(
        source_path,
        args.output_dir
    )

    # --------------------------------------------------------
    # Source provenance
    # --------------------------------------------------------

    print(
        "\nCalculating source SHA-256..."
    )

    source_sha256 = (
        calculate_file_sha256(
            source_path
        )
    )

    print(
        f"SHA-256: {source_sha256}"
    )

    # --------------------------------------------------------
    # Packaging experiment
    # --------------------------------------------------------

    packaging_results = (
        benchmark_packaging(
            df=df,
            source_path=source_path,
            artifacts_directory=(
                artifacts_directory
            ),
            runs=args.packaging_runs,
            gzip_level=args.gzip_level,
            zstd_level=args.zstd_level
        )
    )

    # --------------------------------------------------------
    # Prepare real receiver
    # --------------------------------------------------------

    if args.transfer_mode == "ssh":

        print(
            "\nChecking remote endpoint..."
        )

        ensure_remote_directory(
            host=args.host,
            user=args.user,
            port=args.port,
            remote_dir=args.remote_dir
        )

        print(
            "Remote endpoint ready."
        )

    # --------------------------------------------------------
    # Transfer experiment
    # --------------------------------------------------------

    print("\n" + "=" * 90)
    print("TRANSFER BENCHMARK")
    print("=" * 90)

    summary_rows = []
    trial_rows = []

    for packaging_result in (
        packaging_results
    ):

        artifact = (
            packaging_result.artifact
        )

        if not artifact.available:

            print(
                f"\nSkipping "
                f"{artifact.format_name}: "
                f"{artifact.note}"
            )

            continue

        (
            transfer_times,
            throughputs,
            verification_times,
            integrity_results
        ) = benchmark_transfer(
            artifact,
            args
        )

        # Raw packaging trials
        add_trial_rows(
            trial_rows,
            artifact.format_name,
            "packaging",
            packaging_result.times,
            "seconds"
        )

        # Raw transfer trials
        add_trial_rows(
            trial_rows,
            artifact.format_name,
            "transfer",
            transfer_times,
            "seconds"
        )

        # Raw throughput observations
        add_trial_rows(
            trial_rows,
            artifact.format_name,
            "throughput",
            throughputs,
            "Mbps"
        )

        # Raw verification timings
        if verification_times:

            add_trial_rows(
                trial_rows,
                artifact.format_name,
                "integrity_verification",
                verification_times,
                "seconds"
            )

        summary_rows.append(
            create_summary_row(
                packaging_result=(
                    packaging_result
                ),
                transfer_times=(
                    transfer_times
                ),
                throughputs=throughputs,
                verification_times=(
                    verification_times
                ),
                integrity_results=(
                    integrity_results
                ),
                source_bytes=source_bytes,
                transfer_mode=(
                    args.transfer_mode
                )
            )
        )

    # --------------------------------------------------------
    # Save results
    # --------------------------------------------------------

    results = pd.DataFrame(
        summary_rows
    )

    trials = pd.DataFrame(
        trial_rows
    )

    results_path = (
        run_directory
        / "transfer_benchmark.csv"
    )

    trials_path = (
        run_directory
        / "transfer_trials.csv"
    )

    results.to_csv(
        results_path,
        index=False
    )

    trials.to_csv(
        trials_path,
        index=False
    )

    save_metadata(
        run_directory=run_directory,
        source_path=source_path,
        source_sha256=source_sha256,
        source_bytes=source_bytes,
        df=df,
        load_seconds=load_seconds,
        timestamp=timestamp,
        args=args
    )

    # --------------------------------------------------------
    # Display
    # --------------------------------------------------------

    print_summary(
        results,
        args
    )

    print("\n" + "=" * 100)
    print("PHASE 2 COMPLETED")
    print("=" * 100)

    print("\nResults:")
    print(
        f"  Summary : {results_path.resolve()}"
    )

    print(
        f"  Trials  : {trials_path.resolve()}"
    )

    print(
        f"  Metadata: "
        f"{(run_directory / 'transfer_metadata.json').resolve()}"
    )

    print(
        f"  Artifacts: "
        f"{artifacts_directory.resolve()}"
    )


if __name__ == "__main__":
    main()
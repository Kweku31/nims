"""
01_fiddle_interface.py

Thin wrapper around the OFFICIAL FIDDLE pipeline (Tang et al., 2020).
Repository: https://github.com/MLD3/FIDDLE

This module does NOT reimplement FIDDLE -- it drives the real
`FIDDLE.run` CLI exactly as documented in the repo's README, and
provides a loader for FIDDLE's real output format. This keeps the
thesis's Phase 1 (Feature Engineering) faithful to the actual
published tool rather than a re-derivation of it.

Setup (one-time, outside this script):
    git clone https://github.com/MLD3/FIDDLE.git
    cd FIDDLE
    pip install -r requirements.txt

Expected raw input format (per FIDDLE's README), a CSV/pickle with
exactly 4 columns:
    ID, t, variable_name, variable_value
"""

from __future__ import annotations
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sparse
# from scipy import sparse


@dataclass
class FiddleArgs:
    """User-defined arguments, matching FIDDLE's documented CLI flags."""
    data_fname: str          # path to raw EHR event table (ID, t, variable_name, variable_value)
    population_fname: str    # path to a CSV listing the unique IDs to process
    output_dir: str          # where FIDDLE writes s.npz, X.npz, etc.
    T: float = 48.0          # observation window [0, T]
    dt: float = 1.0          # temporal bin width
    theta_1: float = 0.001   # pre-filter threshold
    theta_2: float = 0.001   # post-filter threshold
    theta_freq: float = 1.0  # "frequent variable" threshold
    stats_functions: tuple = ("min", "max", "mean")

def run_fiddle(args: FiddleArgs, fiddle_repo_path: str = "./FIDDLE") -> None:
    """
    Invoke the real FIDDLE CLI as a subprocess.

    All input/output paths are converted to absolute paths so that the
    subprocess working directory does not change where FIDDLE writes files.
    """
    fiddle_repo = Path(fiddle_repo_path).resolve()

    data_fname = Path(args.data_fname).resolve()
    population_fname = Path(args.population_fname).resolve()
    output_dir = Path(args.output_dir).resolve()

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "FIDDLE.run",
        f"--data_fname={data_fname}",
        f"--population_fname={population_fname}",
        f"--output_dir={output_dir}",
        f"--T={args.T}",
        f"--dt={args.dt}",
        f"--theta_1={args.theta_1}",
        f"--theta_2={args.theta_2}",
        f"--theta_freq={args.theta_freq}",
        "--stats_functions", *args.stats_functions,
    ]

    print("Running FIDDLE:", " ".join(map(str, cmd)))
    subprocess.run(cmd, cwd=fiddle_repo, check=True)


# def run_fiddle(args: FiddleArgs, fiddle_repo_path: str = "./FIDDLE") -> None:
#     """
#     Invoke the real FIDDLE CLI as a subprocess, exactly matching the
#     usage documented at github.com/MLD3/FIDDLE:

#         python -m FIDDLE.run \
#             --data_fname=... --population_fname=... --output_dir=... \
#             --T=24 --dt=1.0 \
#             --theta_1=0.001 --theta_2=0.001 --theta_freq=1 \
#             --stats_functions 'min' 'max' 'mean'

#     Run this once per institution (e.g., once for MIMIC-III, once for
#     eICU), pointing `output_dir` at a separate folder each time -- do
#     NOT merge the raw institution tables before this step.
#     """
#     cmd = [
#         sys.executable, "-m", "FIDDLE.run",
#         f"--data_fname={args.data_fname}",
#         f"--population_fname={args.population_fname}",
#         f"--output_dir={args.output_dir}",
#         f"--T={args.T}",
#         f"--dt={args.dt}",
#         f"--theta_1={args.theta_1}",
#         f"--theta_2={args.theta_2}",
#         f"--theta_freq={args.theta_freq}",
#         "--stats_functions", *args.stats_functions,
#     ]
#     print("Running FIDDLE:", " ".join(cmd))
#     subprocess.run(cmd, cwd=fiddle_repo_path, check=True)


# def load_fiddle_output(output_dir: str) -> dict:
#     """
#     Load FIDDLE's real output artifacts from `output_dir`:
#         s.npz                  -- sparse (N, d) time-invariant features
#         X.npz                  -- sparse (N, L, D) time-dependent features
#         s.feature_names.json   -- names of the d static features
#         X.feature_names.json   -- names of the D time-series features

#     Returns dense numpy arrays plus their feature-name lists, ready
#     for the alignment step (02_feature_alignment.py).
#     """
#     out = Path(output_dir)

#     s = sparse.load_npz(out / "S.npz").todense()
#     s = np.asarray(s)

#     # X is saved as a 3D sparse tensor by FIDDLE; reshape (N, L*D) on
#     # load, then reshape back to (N, L, D) using stored dimensions.
#     X_flat = sparse.load_npz(out / "X.npz")
#     with open(out / "X.feature_names.json") as f:
#         X_feature_names = json.load(f)
#     D = len(X_feature_names)
#     N = X_flat.shape[0]
#     L = X_flat.shape[1] // D
#     X = np.asarray(X_flat.todense()).reshape(N, L, D)

#     with open(out / "s.feature_names.json") as f:
#         s_feature_names = json.load(f)

#     return {
#         "s": s,                             # (N, d)
#         "X": X,                             # (N, L, D)
#         "s_feature_names": s_feature_names,  # length d
#         "X_feature_names": X_feature_names,  # length D
#     }

def load_fiddle_output(output_dir: str) -> dict:
    """
    Load FIDDLE's output artifacts from `output_dir`.

    FIDDLE stores:
        S.npz -- 2D sparse array: (N, d)
        X.npz -- 3D sparse array: (N, L, D)
        s.feature_names.json -- static feature names
        X.feature_names.json -- time-dependent feature names

    Returns dense NumPy arrays plus their feature-name lists.
    """
    out = Path(output_dir)

    # ---------------------------------------------------------
    # Static / time-invariant features
    # ---------------------------------------------------------
    S = sparse.load_npz(out / "S.npz")
    s = np.asarray(S.todense())

    with open(out / "S.feature_names.json") as f:
        s_feature_names = json.load(f)

    # ---------------------------------------------------------
    # Dynamic / time-dependent features
    # ---------------------------------------------------------
    X_sparse = sparse.load_npz(out / "X.npz")

    with open(out / "X.feature_names.json") as f:
        X_feature_names = json.load(f)

    # FIDDLE already stores X as (N, L, D)
    X = np.asarray(X_sparse.todense())

    if X.ndim != 3:
        raise ValueError(
            f"Expected FIDDLE X to be 3-dimensional, got shape {X.shape}"
        )

    if X.shape[2] != len(X_feature_names):
        raise ValueError(
            f"X has {X.shape[2]} features, but "
            f"{len(X_feature_names)} feature names were found."
        )

    return {
        "s": s,
        "X": X,
        "s_feature_names": s_feature_names,
        "X_feature_names": X_feature_names,
    }


# if __name__ == "__main__":
#     # Example invocation for ONE institution. Run this file twice with
#     # different args (once per institution) to produce two separate
#     # FIDDLE outputs, e.g.:
#     #   python 01_fiddle_interface.py mimic
#     #   python 01_fiddle_interface.py eicu
#     institution = sys.argv[1] if len(sys.argv) > 1 else "mimic"

#     args = FiddleArgs(
#         data_fname=f"./input/{institution}_data.csv",
#         population_fname=f"./input/{institution}_population.csv",
#         output_dir=f"./output/{institution}/",
#         T=48.0, dt=1.0,
#         theta_1=0.001, theta_2=0.001, theta_freq=1.0,
#         stats_functions=("min", "max", "mean"),
#     )
#     run_fiddle(args)
#     data = load_fiddle_output(args.output_dir)
#     print(f"[{institution}] s: {data['s'].shape}, X: {data['X'].shape}")

if __name__ == "__main__":
    # Example invocation for ONE institution.
    institution = sys.argv[1] if len(sys.argv) > 1 else "mimic"

    project_dir = Path(__file__).resolve().parent

    args = FiddleArgs(
        data_fname=str(
            project_dir / "input" / f"{institution}_data.csv"
        ),
        population_fname=str(
            project_dir / "input" / f"{institution}_population.csv"
        ),
        output_dir=str(
            project_dir / "output" / institution
        ),
        T=48.0,
        dt=1.0,
        theta_1=0.001,
        theta_2=0.001,
        theta_freq=1.0,
        stats_functions=("min", "max", "mean"),
    )

    run_fiddle(args)

    data = load_fiddle_output(args.output_dir)

    print(
        f"[{institution}] "
        f"s: {data['s'].shape}, "
        f"X: {data['X'].shape}"
    )
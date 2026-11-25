#!/usr/bin/env python3
"""Rank transfer representations with TOPSIS.

Default candidates are the three transformed formats used in the Phase 2
comparison: CSV+gzip, Parquet, and CSV+Zstandard. The original source is kept
as the baseline, and re-serialized CSV is omitted by default because the
source dataset is already CSV.

Criteria (in this order):
  1. size_reduction_pct       benefit: higher is better
  2. packaging_mean_seconds   cost: lower is better
  3. transfer_mean_seconds    cost: lower is better

Weights are supplied in that order and are normalized to sum to one.
Requires pandas and numpy.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

CRITERIA = [
    "size_reduction_pct",
    "packaging_mean_seconds",
    "transfer_mean_seconds",
]
DIRECTIONS = {
    "size_reduction_pct": "benefit",
    "packaging_mean_seconds": "cost",
    "transfer_mean_seconds": "cost",
}
DEFAULT_FORMATS = ["csv_gzip", "parquet", "csv_zstd"]


def calculate_topsis(
    decision: pd.DataFrame,
    weights: list[float] | np.ndarray,
) -> dict[str, pd.DataFrame]:
    """Calculate TOPSIS scores and return intermediate matrices and ranking."""
    if 'transfer_mode' in decision:
        verified = decision.get('integrity_verified', pd.Series(False, index=decision.index)).eq(True)
        decision = decision[decision['transfer_mode'].eq('simulated') |
                            (decision['transfer_mode'].eq('ssh') & verified)].copy()
        if decision['transfer_mode'].nunique() > 1:
            raise ValueError('Rank SSH and simulated Phase 2 observations separately.')
    if decision.empty:
        raise ValueError("The decision matrix has no alternatives.")
    values = decision[CRITERIA].astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("The selected alternatives must have finite criterion values.")
    if (values[CRITERIA[1:]] < 0).any().any():
        raise ValueError("Packaging and transfer times must be non-negative.")
    if (values['size_reduction_pct'] > 100).any():
        raise ValueError("Size reduction cannot exceed 100 percent; negative values denote expansion.")

    weights_array = np.asarray(weights, dtype=float)
    if len(weights_array) != len(CRITERIA):
        raise ValueError(f"Provide exactly {len(CRITERIA)} weights in this order: {CRITERIA}")
    if not np.isfinite(weights_array).all() or (weights_array < 0).any():
        raise ValueError("Weights must be finite, non-negative numbers.")
    if weights_array.sum() <= 0:
        raise ValueError("At least one weight must be greater than zero.")
    weights_array = weights_array / weights_array.sum()

    # Step 1: decision matrix is the selected data in its original units.
    x = decision.set_index("format")[CRITERIA].astype(float)

    # Step 2: vector normalization, performed column by column.
    scaled = x / x.abs().max().replace(0, 1)
    denominators = np.sqrt((scaled ** 2).sum(axis=0))
    r = scaled / denominators.where(denominators != 0, 1)

    # Step 3: apply normalized criterion weights.
    weight_series = pd.Series(weights_array, index=CRITERIA)
    v = r.mul(weight_series, axis="columns")

    # Step 4: ideal best/worst: benefit=max for best; cost=min for best.
    ideal_best = pd.Series(index=CRITERIA, dtype=float)
    ideal_worst = pd.Series(index=CRITERIA, dtype=float)
    for criterion in CRITERIA:
        if DIRECTIONS[criterion] == "benefit":
            ideal_best[criterion] = v[criterion].max()
            ideal_worst[criterion] = v[criterion].min()
        else:
            ideal_best[criterion] = v[criterion].min()
            ideal_worst[criterion] = v[criterion].max()

    # Step 5: Euclidean distances and relative closeness to the ideal solution.
    distance_best = np.sqrt(((v - ideal_best) ** 2).sum(axis=1))
    distance_worst = np.sqrt(((v - ideal_worst) ** 2).sum(axis=1))
    denominator = distance_best + distance_worst
    closeness = np.divide(
        distance_worst,
        denominator,
        out=np.zeros_like(distance_worst, dtype=float),
        where=denominator.to_numpy() != 0,
    )

    ranking = x.copy()
    ranking["distance_to_ideal_best"] = distance_best
    ranking["distance_to_ideal_worst"] = distance_worst
    ranking["topsis_score"] = closeness
    ranking["rank"] = ranking["topsis_score"].rank(method="min", ascending=False).astype(int)
    ranking = ranking.sort_values(["rank", "format"]).reset_index()

    weights_table = pd.DataFrame({
        "criterion": CRITERIA,
        "direction": [DIRECTIONS[c] for c in CRITERIA],
        "weight": weights_array,
    })
    ideals = pd.DataFrame({"ideal_best": ideal_best, "ideal_worst": ideal_worst})

    return {
        "decision_matrix": x.reset_index(),
        "normalized_matrix": r.reset_index(),
        "weighted_normalized_matrix": v.reset_index(),
        "weights": weights_table,
        "ideal_points": ideals,
        "ranking": ranking,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate a TOPSIS ranking from Phase 2 transfer_benchmark.csv."
    )
    parser.add_argument("input_csv", help="Path to transfer_benchmark.csv")
    parser.add_argument(
        "--formats", nargs="+", default=DEFAULT_FORMATS,
        help=("Format values to compare. Default: csv_gzip parquet csv_zstd. "
              "Available names are taken from the input CSV's 'format' column."),
    )
    parser.add_argument(
        "--weights", nargs=3, type=float, default=[1 / 3, 1 / 3, 1 / 3],
        metavar=("REDUCTION", "PACKAGING", "TRANSFER"),
        help=("Weights in criterion order: size reduction, packaging time, "
              "transfer time. Values are normalized automatically. Default: equal weights."),
    )
    parser.add_argument(
        "--output-dir", default="output/topsis",
        help="Directory for TOPSIS outputs (default: output/topsis).",
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.is_file():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        source = pd.read_csv(input_path)
        required = {"format", *CRITERIA}
        missing = required.difference(source.columns)
        if missing:
            raise ValueError(f"Input CSV is missing required columns: {sorted(missing)}")

        missing_formats = [name for name in args.formats if name not in set(source["format"])]
        if missing_formats:
            available = source["format"].astype(str).tolist()
            raise ValueError(
                f"Unknown format(s): {missing_formats}. Available formats: {available}"
            )

        selected = source[source["format"].isin(args.formats)].copy()
        # Preserve the user's requested order rather than the source-file order.
        selected["_order"] = selected["format"].map({name: i for i, name in enumerate(args.formats)})
        selected = selected.sort_values("_order").drop(columns="_order")
        decision = selected.copy()
        results = calculate_topsis(decision, args.weights)

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            frame.to_csv(output_dir / f"topsis_{name}.csv", index=False)

        normalized_weights = np.asarray(args.weights, dtype=float)
        normalized_weights /= normalized_weights.sum()
        print("TOPSIS criterion setup:")
        print("  size_reduction_pct       (benefit, maximize)")
        print("  packaging_mean_seconds   (cost, minimize)")
        print("  transfer_mean_seconds    (cost, minimize)")
        print("Normalized weights:", ", ".join(f"{w:.4f}" for w in normalized_weights))
        print("\nRanking:")
        print(results["ranking"].to_string(index=False, formatters={
            "size_reduction_pct": "{:.3f}".format,
            "packaging_mean_seconds": "{:.6f}".format,
            "transfer_mean_seconds": "{:.6f}".format,
            "distance_to_ideal_best": "{:.6f}".format,
            "distance_to_ideal_worst": "{:.6f}".format,
            "topsis_score": "{:.6f}".format,
        }))
        print(f"\nSaved TOPSIS matrices and ranking to: {output_dir.resolve()}")
        print("Note: TOPSIS ranking depends on the chosen alternatives and criterion weights.")
    except (ValueError, KeyError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

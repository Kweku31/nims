"""Publish aggregate teaching exhibits from the archived Chapter Four experiment."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
RUN = "66c57caa1bd63d2ea403"
INPUT = "ae673cd33e720ef07bb8391389d1a2f3ee6ca15419f9f6de99f7e93f2ac83852"
SCENARIOS = ("existing_payload", "fresh_data")
METHODS = ("pca", "autoencoder")
FORMATS = ("original_source", "csv", "csv_gzip", "parquet", "csv_zstd")


def build(folder):
    sources = {}

    def read(name):
        data = (folder / name).read_bytes()
        sources[name] = hashlib.sha256(data).hexdigest()
        return data.decode("utf-8")

    def rows(name):
        return list(csv.DictReader(read(name).splitlines()))

    manifest = json.loads(read("run_manifest.json"))
    paired = json.loads(read("transport_studies.json"))
    for document in (manifest, paired):
        if (document["run_id"], document["input_sha256"]) != (RUN, INPUT):
            raise ValueError("Select the archived thesis experiment and its matching paired studies.")

    overview = {(r["phase"], r["configuration"], r["metric"]): float(r["value"])
                for r in rows("03_phase_overview.csv")}
    profile = {key: overview["1", "source", key] for key in
               ("n_rows", "n_columns", "overall_cell_missingness_pct", "highly_correlated_pairs")}
    baseline = {fmt: {key: overview["2", fmt, key] for key in
                      ("file_bytes", "packaging_mean_seconds", "transfer_mean_seconds")} for fmt in FORMATS}
    retained = {name: int(value) for (phase, name, metric), value in overview.items()
                if phase == "3" and metric == "predictors_retained"}
    evidence = rows("01_integrated_evidence.csv")
    if not evidence or not all(r["network_mode"] == "ssh" and all(r[key] == "True" for key in
            ("empirical_ssh_eligible", "remote_sha256_verified", "receiver_recovery_passed")) for r in evidence):
        raise ValueError("This exhibit requires verified SSH and successful receiver recovery.")
    original = {(r["method"], int(float(r["k"])), r["delivery_scenario"]): r for r in evidence
                if r["dataset"] == "original" and r["method"] in METHODS and r["codec"] == "native"}
    models = {}
    for k in (2, 4, 8, 16):
        models[str(k)] = {}
        for method in METHODS:
            record = original[method, k, "fresh_data"]
            models[str(k)][method] = {
                "r2": float(record["R2_retained_variation_observed_STANDARDIZED"]),
                "overlap": float(record["knn5_overlap_original_vs_reconstruction"]),
                "flags": int(float(record["new_clinical_range_violations_Phase4"])),
                **{s: float(original[method, k, s]["effective_delivery_seconds"]) for s in SCENARIOS},
            }
    trials = rows("04_network_trials.csv")
    direct = rows("paired_baseline_trials.csv")
    archives = rows("paired_archives_trials.csv")
    if not all(r["remote_sha256_verified"] == "True" for r in trials + direct + archives):
        raise ValueError("A transfer lacks remote verification.")
    baseline_scores = {}
    for r in rows("paired_baseline_topsis.csv"):
        baseline_scores.setdefault(r["transport_method"], {})[r["format"]] = float(r["topsis_score"])
    pairs = {}
    for r in archives:
        if r["condition"] == "interrupted" and r["artifact"] == "ae16":
            block = pairs.setdefault(r["session"], {})
            method = r["transport_method"]
            if method in block or r["condition_observed"] != "True":
                raise ValueError("Invalid interrupted archive pair.")
            block[method] = float(r["delivery_wall_seconds"])
    if len(pairs) != 4 or any(set(b) != {"rsync", "scp"} for b in pairs.values()):
        raise ValueError("The reported interruption comparison requires four complete matched pairs.")
    delta = median(b["rsync"] - b["scp"] for b in pairs.values())
    winners = []
    for r in rows("02_decision_rankings.csv"):
        if r["rank"] == "1" and r["weight_profile"] == "equal":
            if r["decision_evidence_status"] != "empirical_ssh" or r["remote_sha256_verified"] != "True":
                raise ValueError("Unverified ranked result.")
            winners.append({key: r[key] for key in ("dataset", "scenario", "delivery_scenario", "method")} |
                           {"score": float(r["topsis_score"])})
    return dict(run=RUN, snapshot=folder.name, input_sha256=INPUT, sources=sources, profile=profile, baseline=baseline,
                retained=retained, coverage=manifest["config"]["patient_coverage_min"], models=models,
                packages=len({r["package_id"] for r in evidence}), comparisons=len(evidence),
                package_trials=len(trials), direct_trials=len(direct), archive_trials=len(archives),
                archive_pairs=len(pairs), archive_delta=delta, baseline_scores=baseline_scores, winners=winners)


def latex_values(data):
    model = data["models"]
    fresh = [r for r in data["winners"] if r["scenario"] == "loss_tolerant" and r["delivery_scenario"] == "fresh_data"]
    values = {"Rows": f'{int(data["profile"]["n_rows"]):,}', "Missing": f'{data["profile"]["overall_cell_missingness_pct"]:.2f}',
              "CsvMB": f'{data["baseline"]["original_source"]["file_bytes"]/1e6:.2f}',
              "ParquetMB": f'{data["baseline"]["parquet"]["file_bytes"]/1e6:.2f}',
              "Kept": data["retained"]["FS_80_missingness"], "Protected": data["retained"]["FS_80_clinical_review"],
              "Packages": data["packages"], "Transfers": data["package_trials"], "Direct": data["direct_trials"],
              "Archives": data["archive_trials"], "Pairs": data["archive_pairs"], "Delta": f'{data["archive_delta"]:.2f}',
              "ParquetWins": sum(r["method"] == "parquet" for r in fresh), "Groups": len(fresh)}
    for method, prefix in zip(METHODS, ("Pca", "Ae")):
        for key, suffix, k, places in (("r2", "RSq", 16, 3), ("overlap", "Overlap", 16, 3),
                                       ("existing_payload", "Existing", 2, 2), ("fresh_data", "Fresh", 2, 2)):
            values[prefix + suffix] = f"{model[str(k)][method][key]:.{places}f}"
    return "% Generated by build_thesis_reference.py\n" + "".join(
        "\\newcommand{\\study" + name + "}{" + str(value) + "}\n" for name, value in values.items())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    reference = build(args.snapshot)
    (ROOT / "src/thesis_reference.json").write_text(json.dumps(reference, indent=2, allow_nan=False) + "\n")
    (ROOT.parent / "thesis_slides/defence/results.tex").write_text(latex_values(reference))

"""Build the Chapter 4 cohort in sorted patient order with all hourly observations."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def consolidate(data_dir, output_file):
    expected_patients = 20_336
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = output_file.with_suffix('.csv.partial')
    # Find all patient PSV files
    files = sorted(data_dir.rglob("*.psv"))

    if len(files) != expected_patients:
        raise ValueError(
            f"Expected {expected_patients:,} patient files, "
            f"but found {len(files):,}"
        )

    # Validate unique patient identifiers
    patient_ids = [file.stem for file in files]

    if len(set(patient_ids)) != expected_patients:
        raise ValueError("Duplicate patient filenames detected")

    rows_written = 0
    expected_columns = None

    # Process all patients without loading everything into RAM
    for patient_number, file in enumerate(files, start=1):
        df = pd.read_csv(file, sep="|")

        if df.empty:
            raise ValueError(f"Empty patient file: {file}")

        if expected_columns is None:
            expected_columns = list(df.columns)
        elif list(df.columns) != expected_columns:
            raise ValueError(f"Inconsistent columns in: {file}")

        # Add identifiers and hourly observation index
        df.insert(0, "patient_id", file.stem)
        df.insert(1, "time", np.arange(len(df)))

        # Append patient records to a single CSV
        df.to_csv(
            temp_file,
            mode="w" if patient_number == 1 else "a",
            header=(patient_number == 1),
            index=False
        )

        rows_written += len(df)

        if patient_number % 1000 == 0 or patient_number == expected_patients:
            print(
                f"Processed {patient_number:,}/"
                f"{expected_patients:,} patients"
            )

    # Replace final output only after successful completion
    temp_file.replace(output_file)

    print("\nDATASET PREPARATION COMPLETE")
    print("Patients:", expected_patients)
    print("Observations:", rows_written)
    print("Columns:", len(expected_columns) + 2)
    print("File size (bytes):", output_file.stat().st_size)
    print("Saved:", output_file.resolve())



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--set-a', type=Path, default=Path('input/sepsis2019/setA'))
    parser.add_argument('--output', type=Path, default=Path('output/sepsis2019/sepsis_20336_raw.csv'))
    args = parser.parse_args()
    consolidate(args.set_a, args.output)

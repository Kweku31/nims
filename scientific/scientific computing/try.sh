#!/bin/bash

# Define arrays for nprocs and N_values
nprocs=(1 2 4 6)
N_values=(100 200 300)  # Example values, replace with your actual N values

# Output file
output_file="output.txt"

# Clear the file if it already exists
> "$output_file"

# Write the header to the file
echo -e "# X\tY_1\tY_2\tY_3\tY_4" >> "$output_file"

# Loop over nprocs (X values)
for x in "${nprocs[@]}"; do
    # Initialize an array to store Y values for this X
    y_values=()

    # Loop over N_values and nprocs to generate Y values
    for n in "${N_values[@]}"; do
        for p in "${nprocs[@]}"; do
            # Run the MPI program and capture the output
            y=$(mpirun --oversubscribe -np "$p" ./scatter.x "$n")
            y_values+=("$y")  # Add Y to the array
        done
    done

    # Write X and Y values to the file in a tab-separated format
    echo -e "$x\t${y_values[0]}\t${y_values[1]}\t${y_values[2]}\t${y_values[3]}" >> "$output_file"
done

echo "Data generated and saved to $output_file"
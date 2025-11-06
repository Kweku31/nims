#! /usr/bin/bash

# array of N values for running output
# N_values=("10" "20" "30" "40")
# N_values=("256" "512")
N_values=("256" "512" "1024" "2048")
# N_values=("88" "96" "80")
# N_values=("32")
nprocs=("1" "2" "3" "4" "5" "6" "7" "8")
# nprocs=("4")

#compile C source files
mpicc -fopenmp sum_hybrid.c -o sum_hybrid.x

# Output file
output_file="hybrid.txt"

# Clear the file if it already exists
> "$output_file"

# run output
echo -e "# X\tY_1\tY_2\tY_3\tY_4" >> "$output_file"
for x in ${nprocs[@]};do
    # Initialize an array to store Y values
    y_values=()

    for n in ${N_values[@]};
    do
        # for p in ${nprocs[@]};
        # do
            y=$(mpirun --oversubscribe -np $x sum_hybrid.x $n) 
            y_values+=("$y")  # Add Y to the array
        # done
    done
    echo -e "$x\t${y_values[0]}\t${y_values[1]}\t${y_values[2]}\t${y_values[3]}" >> "$output_file"
done


# #plot using gnuplot
# gnuplot -persist <<-EOF
#     set terminal png size 800,600
#     set title "Speedup vs Number of Processes"
#     set xlabel "Number of processes"
#     set ylabel "Time (sec)"
#     set key left
#     set grid
#     set output "./speedup_graph.png"
#     plot "./output.txt" u 1:2 title "Speedup for 256" lw 2 lt 1 lc rgb "red" w lp, \
#          "./output.txt" u 1:3 title "Speedup for 512" lw 2 lt 2 lc rgb "blue" w lp, \
#          "./output.txt" u 1:4 title "Speedup for 1024" lw 2 lt 3 lc rgb "green" w lp, \
#          "./output.txt" u 1:5 title "Speedup for 2048" lw 2 lt 4 lc rgb "purple" w lp
# EOF

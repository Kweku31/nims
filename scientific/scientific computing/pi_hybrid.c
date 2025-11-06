#include <stdio.h>
#include <omp.h>
#include <stdlib.h>
#include <mpi.h>

// Function definition
double f(double x) {
    return 4.0 / (1 + x * x);
}

// Fixed Trapezoidal Rule Function
double trapezoidal_rule(double lowerlimit, double upperlimit, int num_of_steps) {
    double step_size = (upperlimit - lowerlimit) / (double)num_of_steps;
    double sum = 0.5 * (f(lowerlimit) + f(upperlimit));  

    int nthreads;
    double *psum = NULL;  // Pointer for thread-local partial sums

    #pragma omp parallel
    {
        int id = omp_get_thread_num();
        int total_threads = omp_get_num_threads();

        // Allocate psum once inside the parallel region
        #pragma omp single
        {
            nthreads = total_threads;
            psum = (double*) calloc(nthreads, sizeof(double));
        }

        // Ensure all threads see the allocated `psum`
        #pragma omp barrier  

        // Initialize thread-local sum
        psum[id] = 0.0;

        // Work distribution
        for (int i = id + 1; i < num_of_steps; i += nthreads) {
            double x = lowerlimit + i * step_size;
            psum[id] += f(x);
        }

        // Synchronization before summation
        #pragma omp barrier  

        // Only one thread adds up partial sums
        #pragma omp single
        {
            for (int i = 0; i < nthreads; i++) {
                sum += psum[i];  // Each thread's partial sum is added
            }
            free(psum);  // Free allocated memory
        }
    }

    return sum * step_size;
}

int main(int argc, char *argv[]) {
    int rank, size;
    double start_time, end_time;

    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    double a = 0.0, b = 1.0;
    int n = 1000000000;  // 10^9

    // Divide the work among MPI processes
    int local_steps = n / size;
    double local_a = a + rank * (b - a) / size;
    double local_b = local_a + (b - a) / size;

    start_time = MPI_Wtime();

    // Each process computes its portion of the integral using OpenMP
    double local_result = trapezoidal_rule(local_a, local_b, local_steps);

    // Reduce the local results to get the global result
    double global_result;
    MPI_Reduce(&local_result, &global_result, 1, MPI_DOUBLE, MPI_SUM, 0, MPI_COMM_WORLD);

    end_time = MPI_Wtime();

    if (rank == 0) {
        printf("Approximate integral: %.10f\n", global_result);
        printf("Execution time: %.5f seconds\n", end_time - start_time);
    }

    MPI_Finalize();
    return 0;
}
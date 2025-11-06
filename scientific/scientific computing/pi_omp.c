#include <stdio.h>
#include <omp.h>
#include <stdlib.h>

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

int main() {
    double a = 0.0, b = 1.0;
    int n = 10000000000;  // 10^10

    double start_time = omp_get_wtime();
    double result = trapezoidal_rule(a, b, n);
    double end_time = omp_get_wtime();

    printf("Approximate integral: %.10f\n", result);
    printf("Execution time: %.5f seconds\n", end_time - start_time);

    return 0;
}

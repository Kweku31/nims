#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <omp.h>

#define N 100           // Grid size
#define MAX_ITER 10000  // Maximum iterations
#define TOL 1e-6        // Convergence tolerance
#define NUM_THREADS 4   // OpenMP threads

// Right-hand side function f(x,y)
double f(double x, double y) {
    return sin(M_PI * x) * cos(M_PI * y);
}

void poisson_solver() {
    double h = 1.0 / (N - 1);
    double u[N][N], u_new[N][N];
    int i, j, iter;
    double error, max_error;

    // Initialize u with zero
    #pragma omp parallel for collapse(2)
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++)
            u[i][j] = 0.0;

    // Jacobi iteration
    for (iter = 0; iter < MAX_ITER; iter++) {
        max_error = 0.0;

        #pragma omp parallel private(i, j) shared(u, u_new)
        {
            double local_max = 0.0;

            #pragma omp for collapse(2)
            for (i = 1; i < N - 1; i++) {
                for (j = 1; j < N - 1; j++) {
                    u_new[i][j] = 0.25 * (u[i+1][j] + u[i-1][j] + 
                                          u[i][j+1] + u[i][j-1] - 
                                          h * h * f(i * h, j * h));

                    // Track maximum error locally
                    local_max = fmax(local_max, fabs(u_new[i][j] - u[i][j]));
                }
            }

            // Update global max error using reduction
            #pragma omp critical
            max_error = fmax(max_error, local_max);
        }

        // Copy new values to u
        #pragma omp parallel for collapse(2)
        for (i = 1; i < N - 1; i++)
            for (j = 1; j < N - 1; j++)
                u[i][j] = u_new[i][j];

        // Check convergence
        if (max_error < TOL) {
            printf("Converged in %d iterations\n", iter);
            break;
        }
    }

    printf("Final solution at center u(N/2, N/2) = %lf\n", u[N/2][N/2]);
}

int main() {
    omp_set_num_threads(NUM_THREADS);
    poisson_solver();
    return 0;
}

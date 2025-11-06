#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

// Function to perform local matrix multiplication
void matrix_multiply(double **A, double **B, double **C, int block_size) {
    #pragma omp parallel for collapse(2)
    for (int i = 0; i < block_size; i++) {
        for (int j = 0; j < block_size; j++) {
            C[i][j] = 0.0;
            for (int k = 0; k < block_size; k++) {
                C[i][j] = A[i][k] * B[k][j];
            }
        }
    }
}

// Function to perform a circular left shift on a row of matrix A
void shift_left(double **A, int block_size, int row, int shift) {
    double temp[block_size];
    #pragma omp parallel for
    for (int j = 0; j < block_size; j++) {
        temp[j] = A[row][(j + shift) % block_size]; // Circular shift left
    }
    #pragma omp parallel for
    for (int j = 0; j < block_size; j++) {
        A[row][j] = temp[j];
    }
}

// Function to perform a circular up shift on a column of matrix B
void shift_up(double **B, int block_size, int col, int shift) {
    double temp[block_size];
    #pragma omp parallel for
    for (int i = 0; i < block_size; i++) {
        temp[i] = B[(i + shift) % block_size][col]; // Circular shift up
    }
    #pragma omp parallel for
    for (int i = 0; i < block_size; i++) {
        B[i][col] = temp[i];
    }
}

// Function to perform Cannon's Algorithm
void cannon_algorithm(double **A, double **B, double **C, int n, int P) {
    int block_size = n / P;

    // Initial alignment
    for (int i = 0; i < P; i++) {
        for (int j = 0; j < P; j++) {
            shift_left(A, block_size, j, i); // Shift A left by j
            shift_up(B, block_size, j, j);   // Shift B up by i
        }
    }

    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            printf("%.2f \t", A[i][j]);
        }
           printf("\n");
     }

    // Perform multiplication with shifts
    for (int k = 0; k < P; k++) {
        // Local multiplication
        matrix_multiply(A, B, C, block_size);

        // Shift A left by 1 and B up by 1
        for (int i = 0; i < P; i++) {
            shift_left(A, block_size, i, 1);
            shift_up(B, block_size, i, 1);
        }
    }
}

int main() {
    int n, P;
    printf("Enter the size of the matrices (n x n): ");
    scanf("%d", &n);
    printf("Enter the number of processors (P x P): ");
    scanf("%d", &P);

    if (n % P != 0) {
        printf("Error: n must be divisible by P.\n");
        return 1;
    }

    int block_size = n / P;

    // Allocate memory for matrices
    double **A = malloc(n * sizeof(double *));
    double **B = malloc(n * sizeof(double *));
    double **C = malloc(n * sizeof(double *));
    for (int i = 0; i < n; i++) {
        A[i] = malloc(n * sizeof(double));
        B[i] = malloc(n * sizeof(double));
        C[i] = malloc(n * sizeof(double));
    }

    // Input matrix A
    printf("Enter matrix A:\n");
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            // scanf("%lf", &A[i][j]);
            A[i][j] = i * n + j + 1;  // Example initialization
        }
    }

    // Initialize matrix B as identity matrix
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            B[i][j] = (i == j) ? 1.0 : 0.0;
        }
    }

    // Initialize C to zero
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            C[i][j] = 0.0;
        }
    }

    // Perform Cannon's Algorithm
    cannon_algorithm(A, B, C, n, P);

    // Print the result
    printf("Resultant matrix C:\n");
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            printf("%.2f ", C[i][j]);
        }
        printf("\n");
    }

    // Free memory
    for (int i = 0; i < n; i++) {
        free(A[i]);
        free(B[i]);
        free(C[i]);
    }
    free(A);
    free(B);
    free(C);

    return 0;
}
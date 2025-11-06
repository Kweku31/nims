#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#define N 4 // Size of the global matrix (N x N)
#define BLOCK_SIZE 2 // Size of each block (BLOCK_SIZE x BLOCK_SIZE)

// Function to print a matrix
void print_matrix(double *matrix, int rows, int cols) {
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            printf("%.2f ", matrix[i * cols + j]);
        }
        printf("\n");
    }
}

int main(int argc, char *argv[]) {
    int rank, size, n, b, i, j, k;
    double *A_local, *B_local, *C_local;
    double *A_global = NULL, *B_global = NULL, *C_global = NULL;
    MPI_Comm row_comm, col_comm;
    int p, coords[2];  // p = sqrt(size), coords = (i,j)
    int rank, procs;
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &procs);

    // Check if the number of processes is a perfect square
    int grid_size = sqrt(procs);
    if (grid_size * grid_size != procs) {
        if (rank == 0) {
            fprintf(stderr, "Error: Number of processes must be a perfect square.\n");
        }
        MPI_Finalize();
        return 1;
    }

   b = n / p;  // Block size

    // Allocate local (flattened b x b = b*b)
    A_local = malloc(b * b * sizeof(double));
    B_local = malloc(b * b * sizeof(double));
    C_local = calloc(b * b, sizeof(double));  // Zero

    // Global on rank 0
    if (rank == 0) {
        A_global = malloc(n * n * sizeof(double));
        B_global = malloc(n * n * sizeof(double));
        C_global = malloc(n * n * sizeof(double));
        for (i = 0; i < n; i++) {
            for (j = 0; j < n; j++) {
                A_global[i * n + j] = (double)(i * n + j + 1);
                B_global[i * n + j] = (double)((i + j) % 10);
            }
        }
    }

    // Scatter A (row-wise)
    int *sendcounts = malloc(size * sizeof(int));
    int *displs = malloc(size * sizeof(int));
    if (rank == 0) {
        for (i = 0; i < size; i++) {
            sendcounts[i] = b * b;
            displs[i] = (i / p) * (n * b) + (i % p) * b;
        }
    }
    MPI_Scatterv(A_global, sendcounts, displs, MPI_DOUBLE, A_local, b * b, MPI_DOUBLE, 0, MPI_COMM_WORLD);

    // Scatter B (column-wise)
    if (rank == 0) {
        for (i = 0; i < size; i++) {
            sendcounts[i] = b * b;
            displs[i] = (i % p) * (n * b) + (i / p) * b;
        }
    }
    MPI_Scatterv(B_global, sendcounts, displs, MPI_DOUBLE, B_local, b * b, MPI_DOUBLE, 0, MPI_COMM_WORLD);

    free(sendcounts); free(displs);

}
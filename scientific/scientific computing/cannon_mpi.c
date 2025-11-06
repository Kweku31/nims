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

    // Create a 2D Cartesian grid
    int dims[2] = {grid_size, grid_size};
    int periods[2] = {1, 1}; // Periodic boundary conditions
    int reorder = 0;
    MPI_Comm cart_comm;
    MPI_Cart_create(MPI_COMM_WORLD, 2, dims, periods, reorder, &cart_comm);

    // Get coordinates in the grid
    int coords[2];
    MPI_Cart_coords(cart_comm, rank, 2, coords);
    int row = coords[0];
    int col = coords[1];

    // Initialize global matrices A and B (only at rank 0)
    double *A = NULL;
    double *B = NULL;
    if (rank == 0) {
        A = (double *)malloc(N * N * sizeof(double));
        B = (double *)malloc(N * N * sizeof(double));

        // Initialize A and B with dummy values
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                A[i * N + j] = i * N + j + 1;
                B[i * N + j] = (i == j) ? 1 : 0;
            }
        }

        printf("Matrix A:\n");
        print_matrix(A, N, N);
        printf("Matrix B:\n");
        print_matrix(B, N, N);
    }

    // Allocate memory for local blocks of A, B, and C
    double local_A[BLOCK_SIZE * BLOCK_SIZE];
    double local_B[BLOCK_SIZE * BLOCK_SIZE];
    double local_C[BLOCK_SIZE * BLOCK_SIZE] = {0.0};

    // Scatter blocks of A and B to all processes
    MPI_Datatype block_type;
    MPI_Type_vector(BLOCK_SIZE, BLOCK_SIZE, N, MPI_DOUBLE, &block_type);
    MPI_Type_commit(&block_type);

    if (rank == 0) {
        for (int i = 0; i < grid_size; i++) {
            for (int j = 0; j < grid_size; j++) {
                int dest_rank;
                MPI_Cart_rank(cart_comm, (int[]){i, j}, &dest_rank);
                MPI_Send(&A[i * N * BLOCK_SIZE + j * BLOCK_SIZE], 1, block_type, dest_rank, 0, MPI_COMM_WORLD);
                MPI_Send(&B[i * N * BLOCK_SIZE + j * BLOCK_SIZE], 1, block_type, dest_rank, 1, MPI_COMM_WORLD);
            }
        }
    }

    MPI_Recv(local_A, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    MPI_Recv(local_B, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE, 0, 1, MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    // Initial skewing of A and B
    MPI_Comm row_comm, col_comm;
    MPI_Comm_split(cart_comm, row, col, &row_comm); // Split by row
    MPI_Comm_split(cart_comm, col, row, &col_comm); // Split by column

    // Shift A left by row steps
    MPI_Sendrecv_replace(local_A, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE,
                         (col - row + grid_size) % grid_size, 0,
                         (col + row) % grid_size, 0, row_comm, MPI_STATUS_IGNORE);

    // Shift B up by col steps
    MPI_Sendrecv_replace(local_B, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE,
                         (row - col + grid_size) % grid_size, 0,
                         (row + col) % grid_size, 0, col_comm, MPI_STATUS_IGNORE);

    // Perform multiplication and shifting
    for (int step = 0; step < grid_size; step++) {
        // Multiply local blocks
        for (int i = 0; i < BLOCK_SIZE; i++) {
            for (int j = 0; j < BLOCK_SIZE; j++) {
                for (int k = 0; k < BLOCK_SIZE; k++) {
                    local_C[i * BLOCK_SIZE + j] += local_A[i * BLOCK_SIZE + k] * local_B[k * BLOCK_SIZE + j];
                }
            }
        }

        // Shift A left by 1
        MPI_Sendrecv_replace(local_A, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE,
                             (col - 1 + grid_size) % grid_size, 0,
                             (col + 1) % grid_size, 0, row_comm, MPI_STATUS_IGNORE);

        // Shift B up by 1
        MPI_Sendrecv_replace(local_B, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE,
                             (row - 1 + grid_size) % grid_size, 0,
                             (row + 1) % grid_size, 0, col_comm, MPI_STATUS_IGNORE);
    }

    // Gather the result matrix C at rank 0
    double *global_C = NULL;
    if (rank == 0) {
        global_C = (double *)malloc(N * N * sizeof(double));
    }

    MPI_Gather(local_C, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE,
               global_C, BLOCK_SIZE * BLOCK_SIZE, MPI_DOUBLE, 0, MPI_COMM_WORLD);

    // Print the result matrix at rank 0
    if (rank == 0) {
        printf("Result matrix C:\n");
        print_matrix(global_C, N, N);
        free(global_C);
        free(A);
        free(B);
    }

    // Free communicators
    MPI_Comm_free(&row_comm);
    MPI_Comm_free(&col_comm);
    MPI_Comm_free(&cart_comm);
    MPI_Type_free(&block_type);

    MPI_Finalize();
    return 0;
}
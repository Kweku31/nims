#include <stdio.h>
#include <stdlib.h>
#include <mpi.h>
#include <math.h>
#include <string.h>

int main(int argc, char *argv[]) {
    int rank, size;
    int N;              // full matrix size
    // int N = 4;              // full matrix size
    int q;                  // grid size (sqrt(size))
    int n;                  // local block size
    double start, end;

    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    if (argc != 2) {
        if (rank == 0)
            printf("Usage: mpirun -np <num_procs> ./matrix <matrix_size>\n");
        MPI_Finalize();
        return 0;
    }

    N = atoi(argv[1]);

    q = (int)sqrt(size);
    if (q * q != size) {
        if (rank == 0) printf("Number of processes must be a perfect square.\n");
        MPI_Finalize();
        return 0;
    }

    if (N % q != 0) {
        if (rank == 0) printf("Matrix size must be divisible by sqrt(p).\n");
        MPI_Finalize();
        return 0;
    }

    n = N / q; // local block size (each process gets n x n)

    // Allocate memory for local blocks
    double *A_local = malloc(n * n * sizeof(double));
    double *B_local = malloc(n * n * sizeof(double));
    double *C_local = calloc(n * n, sizeof(double));

    // Root process initializes full matrices
    double *A = NULL;
    double *B = NULL;
    double *C = NULL;

    if (rank == 0) {
        A = malloc(N * N * sizeof(double));
        B = malloc(N * N * sizeof(double));
        C = calloc(N * N, sizeof(double));

        // Initialize A and B
        printf("Matrix A:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                A[i * N + j] = rand() %10; 
                // A[i * N + j] = i + j + 1; 
                printf("%5.0f ", A[i * N + j]);
            }
            printf("\n");
        }

        printf("\nMatrix B:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                B[i * N + j] = (i == j) ? 1.0 : 0.0; // identity
                printf("%5.0f ", B[i * N + j]);
            }
            printf("\n");
        }
    }

    // Scatter sub-blocks of A and B 
    if (rank == 0) {
        for (int p = 0; p < size; p++) {
            int row = p / q, col = p % q;
            double *A_block = malloc(n * n * sizeof(double));
            double *B_block = malloc(n * n * sizeof(double));

            for (int i = 0; i < n; i++)
                for (int j = 0; j < n; j++) {
                    A_block[i * n + j] = A[(row * n + i) * N + (col * n + j)];
                    B_block[i * n + j] = B[(row * n + i) * N + (col * n + j)];
                }

            if (p == 0) {
                memcpy(A_local, A_block, n * n * sizeof(double));
                memcpy(B_local, B_block, n * n * sizeof(double));
            } else {
                MPI_Send(A_block, n * n, MPI_DOUBLE, p, 0, MPI_COMM_WORLD);
                MPI_Send(B_block, n * n, MPI_DOUBLE, p, 1, MPI_COMM_WORLD);
            }

            free(A_block);
            free(B_block);
        }
    } else {
        MPI_Recv(A_local, n * n, MPI_DOUBLE, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        MPI_Recv(B_local, n * n, MPI_DOUBLE, 0, 1, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    }

    // Compute rank’s grid coordinates
    int row = rank / q;
    int col = rank % q;

    // Find neighbor ranks for wrap-around
    int left  = row * q + (col - 1 + q) % q;
    int right = row * q + (col + 1) % q;
    int up    = ((row - 1 + q) % q) * q + col;
    int down  = ((row + 1) % q) * q + col;

    MPI_Barrier(MPI_COMM_WORLD);
    start = MPI_Wtime();

    // Initial alignment (shift A left by row, B up by col)
    for (int i = 0; i < row; i++)
        MPI_Sendrecv_replace(A_local, n * n, MPI_DOUBLE, left, 0, right, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    for (int i = 0; i < col; i++)
        MPI_Sendrecv_replace(B_local, n * n, MPI_DOUBLE, up, 0, down, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    // Main Cannon loop
    for (int step = 0; step < q; step++) {
        // Multiply local blocks
        for (int i = 0; i < n; i++)
            for (int j = 0; j < n; j++)
                for (int k = 0; k < n; k++)
                    C_local[i * n + j] += A_local[i * n + k] * B_local[k * n + j];

        // Shift A left, B up
        MPI_Sendrecv_replace(A_local, n * n, MPI_DOUBLE, left, 0, right, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        MPI_Sendrecv_replace(B_local, n * n, MPI_DOUBLE, up, 0, down, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    }

    MPI_Barrier(MPI_COMM_WORLD);
    end = MPI_Wtime();

    // Gather results back to root
    if (rank == 0) {
        for (int p = 0; p < size; p++) {
            int row = p / q, col = p % q;
            if (p == 0) {
                for (int i = 0; i < n; i++)
                    memcpy(&C[(row * n + i) * N + (col * n)], &C_local[i * n], n * sizeof(double));
            } else {
                double *C_block = malloc(n * n * sizeof(double));
                MPI_Recv(C_block, n * n, MPI_DOUBLE, p, 2, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
                for (int i = 0; i < n; i++)
                    memcpy(&C[(row * n + i) * N + (col * n)], &C_block[i * n], n * sizeof(double));
                free(C_block);
            }
        }
    } else {
        MPI_Send(C_local, n * n, MPI_DOUBLE, 0, 2, MPI_COMM_WORLD);
    }

    if (rank == 0) {
        printf("\nC = A x B (Cannon result):\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++)
                printf("%6.1f ", C[i * N + j]);
            printf("\n");
        }
        printf("\nCannon elapsed: %.6f s\n", end - start);
    }

    free(A_local); free(B_local); free(C_local);
    if (rank == 0) { free(A); free(B); free(C); }

    MPI_Finalize();
    return 0;
}

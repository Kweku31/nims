#include <stdio.h>
#include <stdlib.h>
#include <mpi.h>
#include <time.h>

int main(int argc, char *argv[]) {
    int rank, size, N;
    double start_time, end_time;

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

    if (N % size != 0) {
        if (rank == 0)
            printf("Matrix size must be divisible by number of processes!\n");
        MPI_Finalize();
        return 0;
    }

    int block_rows = N / size;  // number of rows handled by each process

    double *A = NULL;
    double *B = (double *)malloc(N * N * sizeof(double));
    double *C = NULL;

    double *A_local = (double *)malloc(block_rows * N * sizeof(double));
    double *C_local = (double *)calloc(block_rows * N, sizeof(double));

    // Initialize matrices only on rank 0
    if (rank == 0) {
        A = (double *)malloc(N * N * sizeof(double));
        C = (double *)malloc(N * N * sizeof(double));

        srand(time(NULL));
        printf("Matrix A:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                A[i * N + j] = rand() % 10;
                printf("%6.2f ", A[i * N + j]);
            }
            printf("\n");
        }

        printf("\nMatrix B:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                B[i * N + j] = rand() % 10;
                printf("%6.2f ", B[i * N + j]);
            }
            printf("\n");
        }
    }

    MPI_Barrier(MPI_COMM_WORLD);
    start_time = MPI_Wtime();

    // Scatter rows of A
    MPI_Scatter(A, block_rows * N, MPI_DOUBLE,
                A_local, block_rows * N, MPI_DOUBLE,
                0, MPI_COMM_WORLD);

    // Broadcast B to all processes
    MPI_Bcast(B, N * N, MPI_DOUBLE, 0, MPI_COMM_WORLD);

    // Local computation: each process computes its rows of C
    for (int i = 0; i < block_rows; i++) {
        for (int j = 0; j < N; j++) {
            double sum = 0.0;
            for (int k = 0; k < N; k++) {
                sum += A_local[i * N + k] * B[k * N + j];
            }
            C_local[i * N + j] = sum;
        }
    }

    // Gather all computed parts of C to root
    MPI_Gather(C_local, block_rows * N, MPI_DOUBLE,
               C, block_rows * N, MPI_DOUBLE,
               0, MPI_COMM_WORLD);

    MPI_Barrier(MPI_COMM_WORLD);
    end_time = MPI_Wtime();

    if (rank == 0) {
        printf("\nResultant Matrix C = A x B:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                printf("%8.2f ", C[i * N + j]);
            }
            printf("\n");
        }

        printf("\nExecution Time: %f seconds\n", end_time - start_time);
    }

    // Cleanup
    free(A_local);
    free(C_local);
    free(B);
    if (rank == 0) {
        free(A);
        free(C);
    }

    MPI_Finalize();
    return 0;
}

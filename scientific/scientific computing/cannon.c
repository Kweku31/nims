#include <stdio.h>
#include <omp.h>

#define N 2  // Matrix size (N x N)
#define P N  // Number of steps (typically sqrt(N) for square grids)

// // Function to multiply matrices A and B, storing the result in C
// void matrixMultiply(double A[N][N], double B[N][N], double C[N][N]) {
//     #pragma omp parallel for collapse(2)
//     for (int i = 0; i < N; i++) {
//         for (int j = 0; j < N; j++) {
//             double sum = 0.0;
//             for (int k = 0; k < N; k++) {
//                 // sum += A[i][k] * B[k][j];
//                 C[i][j] += A[i][k] * B[k][j];
//             }
//             // #pragma omp critical
//             // C[i][j] += sum;
//         }
//     }
// }

// Function to multiply matrices A and B, storing the result in C
void matrixMultiply(double A[N][N], double B[N][N], double C[N][N]) {
    #pragma omp parallel for collapse(2)
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            // for (int k = 0; k < N; k++) {
                // sum += A[i][k] * B[k][j];
                C[i][j] += A[i][j] * B[i][j];
            }
            // #pragma omp critical
            // C[i][j] += sum;
        // }
    }
}


// Function to shift row 'row' of matrix A left by 'shift' positions
void shiftLeft(double A[N][N], int row, int shift) {
    double temp[N];
    for (int j = 0; j < N; j++) {
        temp[j] = A[row][(j + shift) % N];
    }
    for (int j = 0; j < N; j++) {
        A[row][j] = temp[j];
    }
}

// Function to shift column 'col' of matrix B up by 'shift' positions
void shiftUp(double B[N][N], int col, int shift) {
    double temp[N];
    for (int i = 0; i < N; i++) {
        temp[i] = B[(i + shift) % N][col];
    }
    for (int i = 0; i < N; i++) {
        B[i][col] = temp[i];
    }
}

int main() {
    double A[N][N], B[N][N], C[N][N] = {0};

    // Initialize matrices A and B
    #pragma omp parallel for collapse(2)
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            A[i][j] = i * N + j + 1;  // Example initialization
            B[i][j] = (i == j) ? 1 : 0;  // Identity matrix
        }
    }

    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            printf("%.2f \t", A[i][j]);
        }
           printf("\n");
     }

     for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            printf("%.2f \t", B[i][j]);
        }
           printf("\n");
     }
     
    // Initial Alignment
    #pragma omp parallel for
    for (int i = 0; i < N; i++) {
        shiftLeft(A, i, i);  // Shift row i of A left by i positions
    }

        printf("\n First Step Matrix A:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                printf("%.2f \t", A[i][j]);
            }
            printf("\n");
        }

    #pragma omp parallel for
    for (int j = 0; j < N; j++) {
        shiftUp(B, j, j);  // Shift column j of B up by j positions
    }

    printf("\n First Step Matrix B:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                printf("%.2f \t", B[i][j]);
            }
            printf("\n");
        }

    // First multiplication after initial alignment
    matrixMultiply(A, B, C);

    printf("\n First Matrix C:\n");
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            printf("%.2f \t", C[i][j]);
        }
        printf("\n");
    }

    // Remaining steps
    for (int step = 1; step < P; step++) {
        // Shift A left by one in each row
        #pragma omp parallel for
        for (int i = 0; i < N; i++) {
            shiftLeft(A, i, 1);
        }

        printf("\n Step Matrix A:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                printf("%.2f \t", A[i][j]);
            }
            printf("\n");
        }

        // Shift B up by one in each column
        #pragma omp parallel for
        for (int j = 0; j < N; j++) {
            shiftUp(B, j, 1);
        }

        printf("\n Step Matrix B:\n");
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                printf("%.2f \t", B[i][j]);
            }
            printf("\n");
        }

        // Compute the next product
        matrixMultiply(A, B, C);

        printf("\n Matrix C:\n");
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            printf("%.2f \t", C[i][j]);
        }
        printf("\n");
    }
    }

    // Print result matrix C
    printf("\nFinal Matrix C:\n");
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            printf("%.2f \t", C[i][j]);
        }
        printf("\n");
    }

    return 0;
}

#include <stdio.h>
#include <stdlib.h>

#define N 4

int main()
{

    // declare data buffer: array, matrix, etc
    int m = N;
    int n = N;
    int i;
    double *matrix_A;

    size_t byte_dimension;
    int size = (m * n);

    // Compute byte_size
    byte_dimension = sizeof(double *) * size;
    printf("the byte_dimension is: %lu \n", byte_dimension);

    // Allocate storage on heap memory
    matrix_A = (double *)malloc(byte_dimension);
    printf("the location of matrix_A is: %p \n", matrix_A);

    // Populate Array
    for (i = 0; i <= m * n; ++i)
    {

        matrix_A[i] = (double)i;
        printf("the address of matrix_A[%d] is: %p \n", i, &matrix_A[i]);
    }

    // Print Array
    //  for( i = 0; i <= m * n; ++i ){

    //     printf( "%f \n", matrix_A[i]);

    // }

    // Free memory
    free(matrix_A);

    return 0;
}

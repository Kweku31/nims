#include<stdio.h>
#include<stdlib.h>
#include <time.h>

double random_double_in_range(double min, double max);

int main(int argc, char *argv[])
{
    int a, b, d, e, n, k;
    double tot = 0.0;
    int m = atoi(argv[1]); // Matrix size

    size_t byte_dimension;
    
    // printf("Please insert the number of dimension for the matrices(nxn): ");
    // scanf("%d", &m);

    if (m <= 1) {
        printf("The number of dimension must be greater than 1!\n");
        exit(EXIT_FAILURE);
    }

    int size = (m * m);

    double *first, *second, *mul, fmat[m][m], smat[m][m];

    srandom(time(NULL));

    double min = 0.0;
    double max = 100.0;

    byte_dimension = sizeof(double *) * size;
    
    mul = (double *)malloc(byte_dimension);
    first = (double *)malloc(byte_dimension);
    second = (double *)malloc(byte_dimension);


    printf("Your first matrix is:\n");
    for(a = 0; a < m*m; a++) {
            first[a] = random_double_in_range(min, max);
            printf("%.2f \n", first[a]);
    }

    // for(a = 0; a < m; a++) {
    //     for(b = 0; b < m; b++) {
    //         fmat[a][b] = random_double_in_range(min, max);
    //         printf("%.2f \t", fmat[a][b]);
    //     }
    //     printf("\n");
    // }

    // printf("\n");


    printf("Your second matrix is:\n");
    for(a = 0; a < m*m; a++) {
            second[a] = random_double_in_range(min, max);
            printf("%.2f \n", second[a]);
        // printf("\n");
    }

    for(a = 0; a < m; a++) {
        for(e = 0; e < m; e++) {
            tot = 0.0;
            for(k = 0 ; k < m; k++) {
                tot += first[a*m + k] * second[k*m + e];  
            }
            mul[a*m+e] = tot; 

        }
    }



    printf("The result of the matrix multiplication is:\n");
    for(a = 0; a < m*m; a++) {
        // for(e = 0; e < m; e++) {
            printf("%.2f \t", mul[a]);
        // }
        printf("\n");
    }

}

double random_double_in_range(double min, double max) {
    return min + (max - min) * (double)random() / (double)RAND_MAX;
}

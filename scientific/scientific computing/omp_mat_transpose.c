#include<stdio.h>
#include<stdlib.h>
#include <time.h>
#include <omp.h>


double random_double_in_range(double min, double max);

int main(int argc, char *argv[])
{
    int a, b, d, e,  k;
    double tot = 0.0;
    int m = atoi(argv[1]); // Matrix size
    int n = atoi(argv[2]); // Matrix size

    size_t byte_dimension;
    
    // printf("Please insert the number of dimension for the matrices(nxn): ");
    // scanf("%d", &m);

    if (m <= 1) {
        printf("The number of dimension must be greater than 1!\n");
        exit(EXIT_FAILURE);
    }

    int size = (m * n);

    double *first, *second, *mul, fmat[m][n], smat[m][m];

    srandom(time(NULL));

    double min = 0.0;
    double max = 100.0;

    byte_dimension = sizeof(double *) * size;
    
    mul = (double *)malloc(byte_dimension);
    first = (double *)malloc(byte_dimension);
    second = (double *)malloc(byte_dimension);


    printf("Your first matrix is:\n");
    for(a = 0; a < m*n; a++) {
            first[a] = random_double_in_range(min, max);
            printf("%.2f \n", first[a]);
    }

    for(a = 0; a < m; a++) {
        for(k = 0 ; k < n; k++) {
            // first[a*m + k] = first[a];
            printf("%.2f \t", first[a*n + k]);
        }
        printf("\n");
    }
    
//     for(a = 0; a < m*m; a++) {

//         printf("%.2f \n", first[a]);
// }

    // for(a = 0; a < m; a++) {
    //     for(b = 0; b < m; b++) {
    //         fmat[a][b] = random_double_in_range(min, max);
    //         printf("%.2f \t", fmat[a][b]);
    //     }
    //     printf("\n");
    // }

    // printf("\n");

    printf("Your transpose matrix is:\n");
    #pragma omp parallel for
    for(a = 0; a < m; a++) {
        #pragma omp parallel for
        for(k = 0 ; k < n; k++) {
            // second[a*n + k] = first[k*n + a];
            second[(k*m + a)%(size)] = first[a*n + k];
            // printf("%.2f \n", second[a]);
        }
        // printf("\n");
        // printf("%.2f \n", second[a]);
    }
    



    // for(a = 0; a < m; a++) {
    //     for(e = 0; e < m; e++) {
    //         tot = 0.0;
    //         for(k = 0 ; k < m; k++) {
    //             tot += first[a*m + k] * second[k*m + e];  
    //         }
    //         mul[a*m+e] = tot; 

    //     }
    // }

    

    // printf("The result of the matrix multiplication is:\n");
    for(a = 0; a < n; a++) {
        for(e = 0; e < m; e++) {
            printf("%.2f \t", second[a*m + e]);
        }
        printf("\n");
    }

}

double random_double_in_range(double min, double max) {
    return min + (max - min) * (double)random() / (double)RAND_MAX;
}

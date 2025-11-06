#include<stdio.h>
#include<stdlib.h>
#include <time.h>


int main(int argc, char *argv[])
{
    int a, b, d, e, n, k;
    double tot = 0.0;
    int m = atoi(argv[1]); // Matrix size

    if (m <= 1) {
        printf("The number of dimension must be greater than 1!\n");
        exit(EXIT_FAILURE);
    }

    int size = (m * m);

    double first[m][m], second[m][m], mul[m][m];

    // the first matrix m*m
    printf("Your first matrix is:\n");
    for(a = 0; a < m; a++) {
        for(b = 0; b < m; b++) {
            first[a][b] = rand() % 10;
            printf("%.2f \t", first[a][b]);
        }
        printf("\n");
    }


    // the second matrix m*m
    printf("Your second matrix is:\n");
    for(d = 0; d < m; d++) {
        for(e = 0; e < m; e++) {
            second[d][e] = rand() % 10;
            printf("%.2f \t", second[d][e]);
        }
        printf("\n");
    }

    // performing the matrix multiplication
    for(a = 0; a < m; a++) {
        for(e = 0; e < m; e++) {
            tot = 0.0;
            for(k = 0; k < m; k++) {
                tot += first[a][k] * second[k][e];  
            }
            mul[a][e] = tot;  
        }
    }


    // the print of the resulting matrix
    printf("The result of the matrix multiplication is:\n");
    for(a = 0; a < m; a++) {
        for(e = 0; e < m; e++) {
            printf("%.2f \t", mul[a][e]);
        }
        printf("\n");
    }

}


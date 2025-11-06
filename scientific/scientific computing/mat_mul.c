#include<stdio.h>
#include<stdlib.h>
#include <time.h>

double random_double_in_range(double min, double max);

int main()
{
    int a, b, d, e, m, n, k;
    double tot = 0.0;

    printf("Please insert the number of dimension for the matrices(nxn): ");
    scanf("%d", &m);

    if (m <= 1) {
        printf("The number of dimension must be greater than 1!\n");
        exit(EXIT_FAILURE);
    }

    double first[m][m], second[m][m], mul[m][m];

    srandom(time(NULL));

    double min = 0.0;
    double max = 100.0;

    printf("Your first matrix is:\n");
    for(a = 0; a < m; a++) {
        for(b = 0; b < m; b++) {
            first[a][b] = a * m + b + 1;
            printf("%.2f \t", first[a][b]);
        }
        printf("\n");
    }

    printf("Your second matrix is:\n");
    for(d = 0; d < m; d++) {
        for(e = 0; e < m; e++) {
            second[d][e] = (d == e) ? 1 : 0;
            printf("%.2f \t", second[d][e]);
        }
        printf("\n");
    }

    for(a = 0; a < m; a++) {
        for(e = 0; e < m; e++) {
            tot = 0.0;
            for(k = 0; k < m; k++) {
                tot += first[a][k] * second[k][e];  
            }
            mul[a][e] = tot;  
        }
    }

    printf("The result of the matrix multiplication is:\n");
    for(a = 0; a < m; a++) {
        for(e = 0; e < m; e++) {
            printf("%.2f \t", mul[a][e]);
        }
        printf("\n");
    }

}

double random_double_in_range(double min, double max) {
    return min + (max - min) * (double)random() / (double)RAND_MAX;
}

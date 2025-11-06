#include <stdio.h>

int main(){
    int i,j,k, c[4][1];

    int a[4][5] = {
        {1, 2, 3, 4, 5},
        {6, 7, 8, 9, 10},
        {11, 12, 13, 14, 15},
        {16, 17, 18, 19, 20},


    };

    int b[5][1] = {
        {1},
        {2},
        {3},
        {4},
        {5},

    };
   // looping through  matrix a and b
  for ( i = 0; i < 4; i++)
  {
      for ( j = 0; j < 1; j++)
      {
          c[i][j] = 0;
         for (k  = 0; k < 5; k++)
            {
                c[i][j] += a[i][k] * b[k][j];
            }
        }
    }
    
    printf("The product of the two matrices is = \n");
    for ( i = 0; i < 4; i++)
    {
        for ( j = 0; j < 1; j++)
        {
            printf("%d", c[i][j]);
        }
        printf("\n");
    }
    






}

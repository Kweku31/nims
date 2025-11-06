#include<stdio.h>

int main()
{
        int i,j,reverse=0,remainder=0,highest=0;
        // for(i=100;i>=100 && i<=999;i++)
        for(i=100; i<=999;i++)
        {
                // printf("\n New outer loop iteration: %d",i);

        // for(j=100;j>=100 && j<=999;j++)
        for(j=100; j<=999;j++)
        {
            int c=i*j;
            int p=i*j;
            while(c!=0){
                remainder = c%10;
                reverse = reverse*10 + remainder;
                c /=10;
                // printf("%d\n%d\n%d\n",c,reverse,remainder);
                if(p == reverse && reverse > highest){
                    highest = reverse;
                    // printf("%d\n%d\n",reverse,highest);
                }
                // printf("%d\n%d\n%d\n",c,reverse,remainder);

            } 
            reverse=0;
            // printf("\n i=%d, j=%d, c=%d\n",i,j,p);
        }

        }
        printf("%d\n",highest);
}




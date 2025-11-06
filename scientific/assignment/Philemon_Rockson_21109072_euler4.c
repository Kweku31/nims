#include<stdio.h>

int main()
{
        int i,j,reverse=0,remainder=0,greatest=0;
        for(i=100; i<=999;i++)
        {
        for(j=100; j<=999;j++)
        {
            int c=i*j;
            int p=i*j;
            while(c!=0){
                remainder = c%10;
                reverse = reverse*10 + remainder;
                c /=10;
                if(p == reverse && reverse > greatest){
                    greatest = reverse;
                }
            } 
            reverse=0;
        }

        }
        printf("The largest palindrome made from the product of two 3-digit numbers is %d\n",greatest);
}




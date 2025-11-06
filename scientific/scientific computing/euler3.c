#include <stdio.h>

int main()
{
    long int original=600851475143,n = original;
    int p=2;

    while (p*p<=n)
    {
        while (n%p==0)
        {
            n /=p;
            // printf("The factors are %d and %d\n",n,p);
        }
        if(n<p){
            n=p;
        // printf("The largest prime factor is %d\n",p);
        }
        p++;
    }
    printf("The largest prime factor %ld is %ld\n",original,n);



}

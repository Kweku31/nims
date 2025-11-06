#include <stdio.h>

int main()
{
    long int num=600851475143,n = num;
    int p=2;
    while (p*p<=n)
    {
        while (n%p==0)
        {
            n /=p;
        }
        if(n<p){
            n=p;
        }
        p++;
    }
    printf("The largest prime factor %ld is %ld\n",num,n);



}

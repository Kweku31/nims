#include <stdio.h>
#include <math.h>

long int lcm(long int a, int b);
int main()
{
 long int x=1;
 
   printf("%ld\n",lcm(232792560,20));

    for (int i = 2; i <= 20; i++)
    {

        
            x = lcm(x,i);

            printf("%ld\t%d\n",x,i);
            
            
    }


}

long int lcm(long int a, int b){
    long int x = a;
    int y=b,r;
    while ( y > 0){
        r = x % y;
        x = y;
        y = r;
        }
        long int lcm = (a*b)/x;
        return lcm;
}
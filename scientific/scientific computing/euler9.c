#include<stdio.h>
#include<math.h>


int main(){
    int a,b,c;

    for (a = 1; a < 500; a++)
    {
        for (b = a + 1; b < 1000; b++)
        {
            c = 1000 - a - b;
            if (pow(c,2)==pow(a,2)+pow(b,2) && a < b < c)
            {
               int product = a*b*c;
               printf("%d\t%d\t%d\n",a,b,c);
               printf("%d\n",product);
            }
             
        }
        
    }
     







}
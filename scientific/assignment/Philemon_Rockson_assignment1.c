#include <stdio.h>

int main()
{
 int x,sum=0;
 for(x=0;x<1000;x++)
{
 if(x%3==0 || x%5==0)
  {
    sum +=x;
  }
}
printf("The sum of multiples of 3 or 5 less than 1000 is %d\n",sum);


}

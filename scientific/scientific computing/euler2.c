#include <stdio.h>

int main()
{
 int x=1,y=2,sum=0;
 while(x<=4000000)
{
 if(x%2==0)
  {
    sum +=x;
  }
int z=x+y;
 x=y,y=z;
}
printf("The sum of the even numbered Fibonacci sequence is %d\n",sum);


}


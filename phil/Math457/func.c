#include<stdio.h>
int fact(int);
int main()
{
	int number=0;
	printf("\nEnter Number = ");
	scanf("%d",&number);
	printf("Answer = %d\n",fact(number));
}

int fact(int num)
{
	if(num ==0 || num ==1)
	{
		return 1;
	}
	else
	{
		return num*fact(num-1);
	}
}

#include<stdio.h>

int main()
{
	int i=10;
	while(i<29)
	{
		if(i%9==0)
		{
			printf("1st multiple of 9 btn 10&28 is %d",i);
			break;
		}
		i++;
	}
	printf("\nDone!\n");
}

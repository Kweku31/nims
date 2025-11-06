#include <stdio.h>

int main()
{

	int age=0;

	printf("How're old are you?\n");
	scanf("%d",&age);

	if (age>=60)
	{
		printf("\nYou must retire !\n");
	}

	else
	{
		printf( "\nYou have %d years to retirement\n" ,60-age);
	}


}

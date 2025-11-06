#include<stdio.h>
int main()
{
	int i = 200;
	int *j;
	int **k;

	j=&i;
	k=&j;

	printf("Address of i = %p\n",&i);
	printf("Address of i = %p\n",j);
	printf("Value of i = %d\n",i);
	printf("Value of i = %d\n",*(&i));
	printf("Value of i = %d\n",*j);
	printf("Value of i = %d\n",**k);

}


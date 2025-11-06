#include<stdio.h>

int main()
{
	int i = 200;	//integer variable
	int * j;	//integer pointer
	int ** k;	//pointer to an integer pointer

	j=&i;		//assign address of i to j
	k=&j;		//assign address of j to k

	printf("Addr. of i = %p\n",&i);
	printf("Addr. of i = %p\n",j);
	printf("Val. of i = %d\n",i);
	printf("Val. of i = %d\n",*(&i));
	printf("Val. of i = %d\n",*j);
	printf("Val. of i = %d\n",**k);

}

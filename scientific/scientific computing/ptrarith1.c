#include<stdio.h>

int main()
{
	int x=200;
	int y=400;
	int * ptrX;
	int * ptrY;
	
	ptrX=&x;
	ptrY=&y;

	printf("\nx + *ptrX = %d",x + *ptrX);
	printf("\ny - *ptrY = %d",y - *ptrY);
	printf("\n5 * *ptrX - *ptrY = %d",5* *ptrX - *ptrY);  
	printf("\n*ptrX * *ptrY = %d",*ptrX * *ptrY);
	printf("\n*ptrY / *ptrX = %d\n",*ptrX/ *ptrY);
}

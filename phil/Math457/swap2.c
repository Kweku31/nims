#include<stdio.h>
void  swap(int *,int *);
int main()
{
	int i=5;
	int j=10;
	printf("\n|n main :: Before swap: i =%d, j=%d",i,j);
	swap(&i,&j);
	printf("\n|n main :: After swap: i =%d, j=%d",i,j);
}

void swap(int *a,int *b)
{
	int tmp;
	printf("\n|n main :: Before swap: a =%d, b=%d",*a,*b);
	tmp=*a;
	*a=*b;
	*b=tmp;
	printf("\n|n main :: After swap: a =%d, b=%d",*a,*b);
	printf("\n");
}

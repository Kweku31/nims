#include<stdio.h>
void swap(int*,int*);
int main()
{
  int i=5;
  int j=10;
  printf("\nIn main :: Before swap: i = %d, j = %d",i,j);
  swap(&i,&j);
  printf("\nIn main :: After swap: i = %d, j = %d\n",i,j);
}

void swap(int * a, int * b)
{
  int tmp;
  printf("\nIn swap :: Before swap: a = %d, b = %d",*a,*b); 
  tmp=*a;
  *a=*b;
  *b=tmp;
  printf("\nIn swap :: After swap: a = %d, b = %d",*a,*b); 
}

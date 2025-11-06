#include<stdio.h>

int main()
{
	int marks[5]={30,20,70,25,55};
	int * ptr;
	int i=0;

	//assign base address of marks to ptr
	ptr=marks;

	for(i=0;i<5;i++)
	{
		// printf("@ %u: marks[%d] = %d\n",(ptr+i), i,*(ptr+i)); 
		printf("@ %p: marks[%d] = %d\n",(ptr+i), i,*(ptr+i)); 

	}
}

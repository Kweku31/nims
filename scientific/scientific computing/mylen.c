#include<stdio.h>

int mystrlen(char*);

int main()
{
	char string[20];
	puts("Enter String");
	gets(string);
	printf("\nLength of string = %d\n",mystrlen(string));

}


int mystrlen(char * ptr)
{
	int count=0;
	while(*ptr!='\0')
	{
		count++;
		ptr++;
	
	}
	return count;
}

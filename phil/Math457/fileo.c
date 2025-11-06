#include<stdio.h>
#include<stdlib.h>
int main()
{
	FILE * fPtr = NULL;
	fPtr=fopen("rock.txt","r");
	if(fPtr==NULL)
	{
		printf("\nFile could not be opened\n");
		exit(1);
	}
	
	printf("\nFile exists and has been opened for reading\n");
	fclose(fPtr);
	printf("File closed\n");
}

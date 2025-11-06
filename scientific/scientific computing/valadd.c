#include<stdio.h>

int main()
{
	float X = 302.45;
	//The usual way
	printf("Value of X = %f\n",X);
	//The use of the 'Value At Address' operator *
	printf("Value of X = %f\n", *(&X)  );
	

}

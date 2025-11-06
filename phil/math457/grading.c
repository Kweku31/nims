# include <stdio.h>

int main(){
	float marks=0;

	printf("Please input your marks\n");
	scanf("%f",&marks);

	if(marks>=70.0&&marks<=100.0)
	{
		printf("Your grade is A\n");
	}
	else if(marks>=50.0&&marks<=69.9)
	{
		printf("Your grade is B\n");
	}
	else if(marks>=40&&marks<=49.9)
	{
		printf("Your grade is C\n");
	}
	else if(marks>=0&&marks<=39.9)
	{
		printf("Your grade is F\n");
	} 
	else if(marks>100)
	{
		printf("Check your marks again!\n");
	}
	else if(marks<0)
	{
		printf("Your marks cannot be negative!\n");
	}	










}

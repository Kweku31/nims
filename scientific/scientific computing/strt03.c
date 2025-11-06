#include<stdio.h>
struct car
{
	char make[30];
	char model[30];
	int year;
};

int main()
{
	struct car car1={"Benz","C-Class",2000};
	struct car car2;
	car2=car1;//Assignment of struct
	printf("\nMake : %s",car2.make);
	printf("\nModel: %s",car2.model);
	printf("\nYear : %d",car2.year);
	printf("\nDone!\n");
}

#include<stdio.h>
struct registration
{
	struct ownerdetails //nested struct
	{
		char fullname[100];
		char address[100];
	}owner;
	char make[30];
	char number[10];
};

int main()
{
	struct registration reg;
	puts("Owner's Full Name:");
	gets(reg.owner.fullname);
	puts("Owner's Address:");
	gets(reg.owner.address);
	puts("Car's Make:");
	gets(reg.make);
	puts("Car's Number:");
	gets(reg.number);
	printf("\nDone!\n");
}

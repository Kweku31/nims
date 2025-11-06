#include<stdio.h>

struct registration
{
	char number[10];
	char date[10];
	
	struct ownerdetails
	{
		char fullname[50];
		char address[100];
		char contactno[10];
	}owner;

	struct vehicledetails
	{
		char make[20];
		char model[20];
		int year;
		float weight;
	}vehicle;

	//struct ownerdetails owner;
	//struct vehicledetails vehicle;

};



int main()
{
	struct registration reg;
	puts("Vehicle Registration Program");
	puts("Registration No.:");
	gets(reg.number);
	puts("Registration Date:");
	gets(reg.date);
	puts("Owner's Full Name:");
	gets(reg.owner.fullname);
	puts("Owner's Address:");
	gets(reg.owner.address);
	puts("Owner's Contact No.");
	gets(reg.owner.contactno);
	puts("Vehicle's Make:");
	gets(reg.vehicle.make);
	puts("Vehicle's Model:");
	gets(reg.vehicle.model);
	puts("Vehicle's Year:");
	scanf("%d",&reg.vehicle.year);
	puts("Vehicle's Weight:");
	scanf("%f",&reg.vehicle.weight);
	
	printf("\n%s registered an %s on %s with a weight of %.2f tons\n",reg.owner.fullname,reg.vehicle.model,reg.date,reg.vehicle.weight);







}

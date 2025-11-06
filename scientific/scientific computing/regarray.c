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
};



int main()
{
	struct registration reglist[5];
	int i=0;

	puts("Vehicle Registration Program");
	for(i=0;i<5;i++)
	{
		printf("%d - Registration No.:",i+1);
		fflush(stdin);
		gets(reglist[i].number);
		printf("%d - Registration Date:",i+1);
		gets(reglist[i].date);
		printf("%d - Owner's Full Name:",i+1);
		gets(reglist[i].owner.fullname);
		printf("%d - Owner's Address:",i+1);
		gets(reglist[i].owner.address);
		printf("%d - Owner's Contact No.",i+1);
		gets(reglist[i].owner.contactno);
		printf("%d - Vehicle's Make:",i+1);
		gets(reglist[i].vehicle.make);
		printf("%d - Vehicle's Model:",i+1);
		gets(reglist[i].vehicle.model);
		printf("%d - Vehicle's Year:",i+1);
		scanf("%d",&reglist[i].vehicle.year);
		printf("%d - Vehicle's Weight:",i+1);
		scanf("%f",&reglist[i].vehicle.weight);
		puts("Next Registration");
		fflush(stdin);
	}	
}

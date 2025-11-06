#include<stdio.h>
struct registration
{
	char number[10];
	struct ownerdetails //nested struct
	{
		char fullname[100];
	}owner;
	struct vehicledetails //nested struct
	{
		char make[30];
	}vehicle;
};

int main()
{
	//declare pointer of type struct registration
	struct registration * rPtr;
	//declare a instance of struct registration
	struct registration reg;
	//assign base address of reg to rPtr;
	rPtr=&reg;
	//access fields with arrow operator
	printf("\nRegistration Number:");
	gets(rPtr->number);
	printf("\nOwner's Name:");
	gets(rPtr->owner.fullname);
	printf("\nVehicle's Make:");
	gets(rPtr->vehicle.make);
}

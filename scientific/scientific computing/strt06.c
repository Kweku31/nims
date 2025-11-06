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
	//declare an array of struct registration
	struct registration reglist[4];
	int i=0;
	for(i=0;i<4;i++)
	{
	  printf("\n%d: Owner's Full Name:",i+1);
	  gets(reglist[i].owner.fullname);
	  printf("\n%d: Owner's Address:",i+1);
	  gets(reglist[i].owner.address);
	  printf("\n%d: Car's Make:",i+1);
	  gets(reglist[i].make);
	  printf("\n%d: Car's Number:",i+1);
	  gets(reglist[i].number);
	  printf("\n");
	}
}

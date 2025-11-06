#include<stdio.h>

int main()
{
  char fname[20];
  char sname[20];
  char mname[20];

  printf("\nFirst Name ");
  scanf("%s",&fname[0]);
  printf("\nSurname ");
  scanf("%s",&sname[0]);
  printf("\nMiddle Name ");
  scanf("%s",&mname[0]);
  printf("\nWelcome %s %s %s\n",fname,mname,sname);

}

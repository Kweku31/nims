#include<stdio.h>

int main()
{
  char fullname[60];
  printf("\nFull Name: ");
  scanf("%[^\n]s",fullname);
  printf("\nWelcome %s\n",fullname);
}

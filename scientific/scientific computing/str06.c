#include<stdio.h>
#include<string.h>

int main()
{
  char source[5];
  char target[10];
  puts("Enter First Name");
  gets(target);
  puts("Enter Surname");
  gets(source);
  strcat(target,source);
  puts("Full Name is:");
  puts(target);
}

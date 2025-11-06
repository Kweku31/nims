#include<stdio.h>
#include<string.h>

int main()
{
  char source[20];
  char target[20];
  puts("Enter Name");
  gets(source);
  strcpy(target,source);
  puts("Below is what you entered");
  puts(target);
}

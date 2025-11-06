#include<stdio.h>
#include<string.h>

int main()
{
  char string1[10];
  char string2[10];
  puts("Enter String_1");
  gets(string1);
  puts("Enter String_2");
  gets(string2);
  if(strcmp(string1,string2)==0)
  {
  	puts("String are identical");
  }
  else
  {
  	puts("String are not identical");
  }
}

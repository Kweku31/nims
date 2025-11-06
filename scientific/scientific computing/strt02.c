#include<stdio.h>

int main()
{
  //Declaration and Instantiation
  struct book
  {
    char title[50];
    char author[50];
    int pages;
  }book1,book2; 
  
  //instantiation & initialization 
  struct book book3={"C for Dummies","Dan Gookins",390};

  puts("Book1: Enter Title");
  gets(book1.title);
  puts("Book2: Enter Title");
  gets(book2.title);
  printf("\n\nTitles \n%s \n%s \n%s\n",
  	book1.title,book2.title,book3.title);
}


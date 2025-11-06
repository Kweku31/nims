#include<stdio.h>
//define a struct
struct book
{
	char title[50];
	char author[50];
	int pages;
};

int main()
{
 //declare book struct instance
 struct book novel;
 //fill novel with data
 puts("Title of Book:");
 gets(novel.title);
 puts("Author of Book:");
 gets(novel.author);
 puts("Pages of Book:");
 scanf("%d",&novel.pages);
 printf("\n%s wrote a %d paged book called %s.\n",
 		novel.author,novel.pages,novel.title);
}


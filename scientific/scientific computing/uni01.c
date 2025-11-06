#include<stdio.h>
union types
{
	int i;
	float f;
	char c;
};

int main()
{
	union types tty;
	printf("memory size of tty = %d\n",sizeof(tty));
	tty.i=10;
	printf("tty holds the integer %d\n",tty.i);
	tty.f=3.142;
	printf("tty now holds the float %f\n",tty.f);
	tty.c='F';
	printf("tty now holds the char %c\n",tty.c);
}

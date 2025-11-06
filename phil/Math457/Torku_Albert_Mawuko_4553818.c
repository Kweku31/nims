#include<stdio.h>

int main()
{
	int x;
	float h,b,a,t,l,w,d,c;
	printf("Input 1 for area of triangle\n");
	printf("Input 2 for area of rectangle\n");
	printf("Input 3 for area of circle\n");
	printf("Input 4 to exit\n");
	printf("Please input your choice:\n");
	scanf("%d",&x);

	switch(x){
	case 1:
	printf("Input your height:\n");
	scanf("%f",&h);
	printf("Input your base:\n");
	scanf("%f",&b);
	a=h*b*0.5;
	printf("Area of Triangle=\n");
	printf("%f\n",a);
	break;


	case 2:
	printf("Input your length:\n");
	scanf("%f",&l);
	printf("Input your width:\n");
	scanf("%f",&w);
	c=l*w;
	printf("Area of Rectangle=\n");
	printf("%f\n",c);
	break;

	case 3:
	printf("Input your radius:\n");
	scanf("%f",&d);
	t = 3.142*d;
	printf("Area of Circle=\n");
	printf("%f\n",t);
	break;
	



}
}

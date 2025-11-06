#include<stdio.h>

int main()
{
	int x;
	float a,b,p,t;
	float l,w,r,d;
	printf("___Menu___\n");
	printf("Input 1 for area of triangle\n");
	printf("Input 2 for area of rectangle\n");
	printf("Input 3 for area of circle\n");
	printf("Input 4 to exit\n");
	printf("Please input your choice:\n");
	scanf("%d",&x);

	switch(x){
	case 1:
	printf("Input your height:\n");
	scanf("%f",&a);
	printf("Input your base:\n");
	scanf("%f",&b);
	p=a*b*0.5;
	printf("Area of Triangle=\n");
	printf("%f\n",p);
	break;


	case 2:
	printf("Input your length:\n");
	scanf("%f",&l);
	printf("Input your width:\n");
	scanf("%f",&w);
	r=l*w;
	printf("Area of Rectangle=\n");
	printf("%f\n",r);
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

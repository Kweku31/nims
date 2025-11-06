#include <stdio.h>
#include <math.h> 


int main()
{
    int value,t=0,p=1;
    float a,b,h,c,l,w,q=0;
    double r=0.0;

    printf("Please welcome to your area calculator, select any of the options to calculate your area:\n1. Area of triangle\n2. Area of rectangle\n3. Area of circle\n4. Integer Multiplication \n5. Exit\n");
    scanf("%d",&value);

    switch(value)
    {
        case 1:
        printf("Please enter your value for the base:\n");
        scanf("%f",&b);
        printf("Please enter your value for the height:\n");
        scanf("%f",&h);
        a = 0.5*b*h;
        printf("The area of the triangle is %f\n",a);
        break;
        case 2:
        printf("Please enter your value for the length:\n");
        scanf("%f",&l);
        printf("Please enter your value for the width:\n");
        scanf("%f",&w);
        q = l*w;
        printf("The area of the rectangle is %f\n",q);
        break;
        case 3:
        printf("Please enter your value for the radius:\n");
        scanf("%lf",&r);
        double z = 3.142*r*r;
        printf("The area of the circle is %lf\n",z);
        break;
        case 4:
        printf("Please enter your integer:\n");
        scanf("%d",&t);
        char str[100];
        sprintf(str,"%d",t);
        // printf("%d",str[0]);
        for(int i=0;str[i]!='\0';i++)
        {
            int j = str[i] - '0';
            // printf("%d",j);
            p *= j;
        }
        printf("The product of the integer is %d\n",p);
        break;
        case 5:
        printf("See ya!!\n");
        break;
        default:
        break;
    }



}
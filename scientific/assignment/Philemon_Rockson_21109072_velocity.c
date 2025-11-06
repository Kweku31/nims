#include <stdio.h>

int main()
{
    float u,v,a,t;
    printf("Enter initial velocity:\n");
    scanf("%f", &u);
    printf("Enter acceleration:\n");
    scanf("%f", &a);
    printf("Enter time taken:\n");
    scanf("%f", &t);

    v = u + (a * t);
    printf("The final velocity is %f.\n", v);
}
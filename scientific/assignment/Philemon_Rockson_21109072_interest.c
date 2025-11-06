#include <stdio.h>

int main()
{
    float s_I, p, r, t;
    printf("Enter Principal amount:\n");
    scanf("%f", &p);
    printf("Enter Rate:\n");
    scanf("%f", &r);
    printf("Enter time for the loan:\n");
    scanf("%f", &t);

    s_I = (p * r * t) / 100;
    printf("The Simple Interest is %.2f.\n", s_I);
}
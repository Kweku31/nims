#include <stdio.h>

int main() {
    float mark = 0;
    printf("Enter Mark\n");
    scanf("%f", &mark);
    printf("Your Grade = %s\n", mark >= 70.0 ? "A" : mark >= 50.0 ? "B" : mark > 40.0 ? "C" : "F");
   int y=0;
	y=10%3;
printf("%d\n",y);

}

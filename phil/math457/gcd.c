#include<stdio.h>
int main(){
int x,y,a,b;
int r;
	printf("Input your first integer\n");
	scanf("%d",&a);
	if (a < 0){
        printf("Your integer should be positive\n");
        return 0;
        }
	printf("Input your second integer\n");
	scanf("%d",&b);
	if (b < 0){
        printf("Your integer should be positive\n"); 
	return 0;
        }

	x = a;
	y = b;
	while ( y > 0){
	r = x % y;
	x = y;
	y = r;
	}
	printf("The gcd is %d \n",x);





}

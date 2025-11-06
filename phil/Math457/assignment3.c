#include<stdio.h>

int main()
{
	int product=1;
	int x;
	printf("Input your number\n");
	scanf("%d",&x);
	
	if(x<0)
	{printf("Your integer must be positive!\n");
	}
	else{
		
	while(x>0)
		{
			product=product*(x%10);
			x=x/10;
		}
		printf("%d\n",product);
}
}


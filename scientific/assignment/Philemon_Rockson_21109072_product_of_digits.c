#include<stdio.h>

int main()
{
	int product=1;
	int q;
	printf("Input your number\n");
	scanf("%d",&q);
	
	if(q<0)
	{printf("Your integer must be positive!\n");
	}
	else{
		
	while(q>0)
		{
			product=product*(q%10);
			q=q/10;
		}
		printf("The product of the digits is %d\n",product);
}
}


#include<stdio.h>

int main()
{
	int a,b,m,n,d,e,r,c,tot=0,k;
	int first[10][10],second[10][10],mul[10][10];

	printf("Enter your first matrix\n");
	printf("Please insert the number of rows\n");
	scanf("%d",&m);
	printf("Please insert the number of columns\n");
	scanf("%d",&n);
	
	printf("Insert your matrix elements:\n");
		for(a=0;a<m;a++){
		for(b=0;b<n;b++){
		scanf("%d",&first[a][b]);
		}
		}
		printf("Your first matrix is:\n");
		for(a=0;a<m;a++){
                for(b=0;b<n;b++)

		printf("%d \t",first[a][b]);
                printf("\n");
		}



	printf("Enter your second matrix\n");
	printf("Please insert the number of rows\n");
        scanf("%d",&r);
        printf("Please insert the number of columns\n");
        scanf("%d",&c);

	if(n != r)
	printf("The matrices cannot multiply each other\n");
	else
	{
        printf("Insert your matrix elements:\n");
                for(d=0;d<r;d++)
                for(e=0;e<c;e++)
                scanf("%d",&second[d][e]);

		printf("Your second matrix is:\n");
                for(d=0;d<r;d++){
                for(e=0;e<c;e++)

                printf("%d \t",second[d][e]);
                printf("\n");
                }



		for(a=0;a<m;a++){
		for(e=0;e<c;e++){
		for(k=0;k<r;k++){
		tot = tot + first[a][k]*second[k][e];
		}
		mul[a][e] = tot;
		tot = 0;
		}
		}

		printf("The result of the matrix multiplication is:\n");
		for(a=0;a<m;a++){
		for(e=0;e<c;e++)
		printf("%d \t",mul[a][e]);
		printf("\n");
		}






       }
                


}

#include <stdio.h>
#include <stdlib.h>
int main(){

FILE * file1;
FILE * file2;
FILE * file3;
char first[50];char second[50];char third[50];char word[1000];
printf("Enter the name of the file to contain the first matrix: \n");
gets(first);
printf("Enter the name of the file to contain the second matrix: \n");
gets(second);
printf("Enter the name of the file to contain the result matrix: \n");
gets(third);

int i,j,k;
float matA[2][2];
float matB[2][2];
float mult[2][2];
float tmatA[2][2];
printf("\n");
//creating matrix A
for(i=0;i<2;i++){
	for(j=0;j<2;j++){
		printf("Enter the value of A[%d][%d]: ",i+1,j+1);
		scanf("%f",&matA[i][j]);
	}
}
printf("\n");

//creating transpose of matrix A
for(i=0;i<2;i++){
        for(j=0;j<2;j++){
            tmatA[j][i]=matA[i][j];
        }
}

//create the first file and write to it
file1 = fopen(first,"w+");
fprintf(file1,"%s\n","first matrix");
fprintf(file1,"\n");
for(i=0;i<2;i++){
                for(j=0;j<2;j++){
                        fprintf(file1,"%.3f\t",matA[i][j]);
                }
                fprintf(file1,"\n");
        }
fclose(file1);

printf("\n");
//read from the first file
file1 = fopen(first,"r");
while(fgets(word,1000,file1)!=NULL){
	printf("%s",word);
	}
fclose(file1);

printf("\n");
//printing the transpose of matrix A
printf("First matrix Transpose\n");
for(i=0;i<2;i++){
        for(j=0;j<2;j++){
                printf("%.3f\t",tmatA[i][j]);
        }
        printf("\n");
}
printf("\n");

//creating matrix B
printf("Enter the values for second matrix\n");
for(i=0;i<2;i++){
	for(j=0;j<2;j++){
		printf("Enter the value of B[%d][%d]: ",i+1,j+1);
		scanf("%f",&matB[i][j]);
	}
}
printf("\n");

//create second file and write to it
file2 = fopen(second,"w+");
fprintf(file2,"%s\n","second matrix");
fprintf(file2,"\n");
for(i=0;i<2;i++){
                for(j=0;j<2;j++){
                        fprintf(file2,"%.3f\t",matB[i][j]);
                }
                fprintf(file2,"\n");
        }

fclose(file2);

printf("\n");
//read from the second file
file2 = fopen(second,"r");
while(fgets(word,1000,file2)!=NULL){
	printf("%s",word);
	}
fclose(file2);

printf("\n");

//multiplying matrix and transpose
printf("first matrix transpose multiplied by second matrix\n");
for(i=0;i<2;i++){
        for(j=0;j<2;j++){
        	mult[i][j]=0;
        	for(k=0;k<2;k++){
                	mult[i][j] = mult[i][j] + (tmatA[i][k]*matB[k][j]);
                }
                printf("%3.f\t",mult[i][j]);
        }
        printf("\n");
}

printf("\n");

//create and write to third file
file3 = fopen(third,"w+");
fprintf(file3,"%s\n","result matrix");
fprintf(file3,"\n");
for(i=0;i<2;i++){
                for(j=0;j<2;j++){
                        fprintf(file3,"%.3f\t",mult[i][j]);
                }
                fprintf(file3,"\n");
        }

fclose(file3);




}

#include<stdio.h>
#include<stdlib.h>
int main(){
FILE *phil;
FILE *rock;
FILE *kweku;
int i,j,k,tmat[2][2],mult[2][2];
char first[100];char second[100];char third[100];
printf("Enter the name of the file to contain the first matrix: \n");
gets(first);
printf("Enter the name of the file to contain the second matrix: \n");
gets(second);
printf("Enter the name of the file to contain the result matrix: \n");
gets(third);
//
//writing the matrix into the file
//
phil = fopen(first,"w");
fprintf(phil,"%s\n","first matrix");
int matrix[2][2] = {
    {11,12},
    {13,14}
};
if (phil == NULL){
    printf("File can't be opened\n");
    exit(1);
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fprintf(phil,"%d ",matrix[i][j]);
    }
    fprintf(phil,"\n");
}
fclose(phil);
//
//reading the matrix from the file created
//
phil = fopen(first,"r");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fscanf(phil,"%d  ",&matrix[i][j]);
    }
    fscanf(phil,"\n");
}
printf("The First Matrix is:\n");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d  ",matrix[i][j]);
    }
    printf("\n");
}
//
//Doing the transpose of the matrix
//
printf("The Transpose of the First Matrix is:\n");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        tmat[j][i] = matrix[i][j];
    }
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d  ",tmat[i][j]);
    }
    printf("\n");
}
fclose(phil);
//
//
//
//Creating the Second Matrix
//
//writing the second matrix into the second file
//
rock = fopen(second,"w");
int matrixB[2][2] = {
    {15,16},
    {17,18}
};
if (rock == NULL){
    printf("File can't be opened\n");
    exit(1);
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fprintf(rock,"%d   ",matrixB[i][j]);
    }
    fprintf(rock,"\n");
}
fclose(rock);
//
//reading from the matrix
//
rock = fopen(second,"r");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fscanf(rock,"%d   ",&matrixB[i][j]);
    }
    fscanf(rock,"\n");
}
printf("The Second Matrix is:\n");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d   ",matrixB[i][j]);
    }
    printf("\n");
}
fclose(rock);
//
//
//
//Creating the third file and writing the Matrix Multiplication into it
//
//
//
printf("The Matrix Multiplication of the Transpose of the First Matrix and Second Matrix is:\n");
kweku = fopen(third,"w");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        mult[i][j] = 0;
        for (k=0;k<2;k++){
            mult[i][j] += tmat[i][k]*matrixB[k][j];
        }   
    }
}
if (kweku == NULL){
    printf("File can't be opened\n");
    exit(1);
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fprintf(kweku,"%d   ",mult[i][j]);
    }
    fprintf(kweku,"\n");
}
fclose(kweku);
kweku = fopen(third,"r");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d   ",mult[i][j]);
    }
    printf("\n");
}
fclose(kweku);

}

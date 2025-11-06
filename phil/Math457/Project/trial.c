#include<stdio.h>
#include<stdlib.h>
int main(){
FILE *fp;
FILE *sp;
FILE *tp;
int i,j,k,tmat[2][2],multi[2][2],matrix[2][2],matrixB[2][2];
//
// char first[50];char second[50];char third[50];char word[1000];
// printf("Enter the name of the file to contain the first matrix: \n");
// gets(first);
// printf("Enter the name of the file to contain the second matrix: \n");
// gets(second);
// printf("Enter the name of the file to contain the result matrix: \n");
// gets(third);
//
fp = fopen("fmat.txt","r");
// int matrix[2][2] = {
//     {1,2},
//     {3,4}
// };
if (fp == NULL){
    printf("File can't be opened\n");
    exit(1);
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fprintf(fp,"%d ",matrix[i][j]);
    }
    fprintf(fp,"\n");
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fscanf(fp,"%d  ",&matrix[i][j]);
    }
    fscanf(fp,"\n");
}
printf("The First Matrix is:\n");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d  ",matrix[i][j]);
    }
    printf("\n");
}
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
fclose(fp);
//
//
//
//Creating Second Matrix
//
//
//
sp = fopen("smat.txt","r");
// int matrixB[2][2] = {
//     {5,6},
//     {7,8}
// };
if (sp == NULL){
    printf("File can't be opened\n");
    exit(1);
}
// for (i = 0;i<2;i++){
//     for (j=0;j<2;j++){
//         fprintf(sp,"%d   ",matrixB[i][j]);
//     }
//     fprintf(sp,"\n");
//}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fscanf(sp,"%d   ",&matrixB[i][j]);
    }
    fscanf(sp,"\n");
}
printf("The Second Matrix is:\n");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d   ",matrixB[i][j]);
    }
    printf("\n");
}
fclose(sp);
//
//
//
//Creating third file and the Matrix Multiplllication
//
//
//
printf("The Matrix Multiplication of the Transpose of the First Matrix and Second Matrix is:\n");
tp = fopen("tmat.txt","r");
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        multi[i][j] = 0;
        for (k=0;k<2;k++){
            multi[i][j] += tmat[i][k]*matrixB[k][j];
        }   
    }
}
if (tp == NULL){
    printf("File can't be opened\n");
    exit(1);
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        fprintf(tp,"%d   ",multi[i][j]);
    }
    fprintf(tp,"\n");
}
for (i = 0;i<2;i++){
    for (j=0;j<2;j++){
        printf("%d   ",multi[i][j]);
    }
    printf("\n");
}
fclose(tp);

}

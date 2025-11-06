#include<stdio.h>
int main(){
FILE *phil;
char phi[100];
printf("Enter it\n");
scanf("%s",phi);
phil =fopen(phi,"w");
fprintf(phil,"%s\n","I love you");
if (phil==NULL){
printf("File can't be opened");
}
fclose(phil);
return 0;






}

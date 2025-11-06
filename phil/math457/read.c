#include<stdio.h>
int main(){
FILE *phil;
char phi[100];
//printf("Enter it\n");
//scanf("%s",phi);
phil =fopen("kweku","r");
//fprintf(phil,"%s\n","I love you");
while (fgets(phi,100,phil) != NULL){
printf("%s",phi);
}
//printf("\n");
if (phil==NULL){
printf("File can't be opened");
}
fclose(phil);
return 0;






}

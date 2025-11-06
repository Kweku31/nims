#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int prime(int num){
    if (num < 2){return 0;}
    for (int i = 2; i <=pow(num, 0.5) ; i++){
        if (num % i == 0){
            return 0;
        }
     }
   return 1;
}

int main(){

int count, ptr, num;

int* countPtr = &count;
int* primePtr = &ptr;

num = 2;
count = 0;
int counter = 0;
while (count < 10001){
    if (prime(num) == 1){
        *primePtr = num;
        ++*countPtr;
    }
    num++;
    counter++;
}

printf("The 10001st prime number is: %d\n", *primePtr);
printf("The number of iterations done is: %d\n", counter);
}

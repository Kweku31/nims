#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int isPrime(int num){
    if (num < 2){return 0;}
    for (int i = 2; i <=pow(num, 0.5) ; i++){
        if (num % i == 0){
            return 0;
        }
     }
   return 1;
}

int main(){

int count, prime, num;

int* countPtr = &count;
int* primePtr = &prime;

num = 2;
count = 0;
int counter = 0;
while (count < 10001){
    if (isPrime(num) == 1){
        *primePtr = num;
        ++*countPtr;
    }
    num++;
}

printf("The 10001st prime number is: %d\n", *primePtr);
}

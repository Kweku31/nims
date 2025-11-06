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
    num = 2;
    count = 0;
    int sum =0;
    // int counter = 0;
    while (num < 2000000){
        if (isPrime(num) == 1){
            sum += num;
        }
        num++;
    }

    printf("The sum of all the primes below two million is: %d\n", sum);


}
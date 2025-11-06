#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <sys/time.h>


int Prime(int num){
    if (num < 2){return 0;}
    for (int i = 2; i <=pow(num, 0.5) ; i++){
        if (num % i == 0){
            return 0;
        }
     }
   return 1;
}

int main(){

    struct timeval start, end;
    double elapsed_time;

    gettimeofday(&start, NULL);  // Start time

    int num = 2;
    int sum =0;
    while (num < 2000000){
        if (Prime(num) == 1){
            sum += num;
        }
        num++;
    }

    printf("The sum of all the primes below two million is: %d\n", sum);

    gettimeofday(&end, NULL);  // End time

    elapsed_time = (end.tv_sec - start.tv_sec) + (end.tv_usec - start.tv_usec) / 1e6;
    printf("Execution time: %f seconds\n", elapsed_time);
}
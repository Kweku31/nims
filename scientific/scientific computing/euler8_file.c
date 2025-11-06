#include <stdio.h>
#include <sys/time.h>


int main() {
    FILE *file1 = fopen("example.txt", "r");
    char digits[1000];
    struct timeval start, end;
    double elapsed_time;

    gettimeofday(&start, NULL);  // Start time

    int len = 13;
    long int product = 0, tempp = 1;

    if (file1 == NULL) {
        printf("Error opening file!\n");
        return 1;
    }

    while (fgets(digits, 1001, file1) != NULL) {  // Read each line
        // printf("%s\n", digits); // Print the line
    }
    
    for (int i = 0; i < 1000 - len; i++)
 {
    for (int j = 0; j < len; j++)
    {
        tempp *= digits[i+j] - '0';
        
    }
        if(tempp > product){
            product = tempp;
        }
        tempp = 1;
 }
    printf("%ld\n",product);
    gettimeofday(&end, NULL);  // End time

    elapsed_time = (end.tv_sec - start.tv_sec) + (end.tv_usec - start.tv_usec) / 1e6;
    printf("Execution time: %f seconds\n", elapsed_time); 

    fclose(file1);
    return 0;
}

#include <stdio.h>
#include <omp.h>

int main() {
    int partial_sum = 0;
    int total_sum = 0;

    #pragma omp parallel
    {
        int thread_id = omp_get_thread_num();
        int local_sum = 0;

        // Each thread computes its local sum
        for (int i = 0; i < 10; i++) {
            local_sum += thread_id + i;
        }

        // Print local sum
        printf("Thread %d: local_sum = %d\n", thread_id, local_sum);

        // Synchronize threads before updating the total sum
        #pragma omp barrier

        // One thread updates the total sum
        #pragma omp single
        {
            total_sum = local_sum;
            printf("Thread %d: Updated total_sum = %d\n", thread_id, total_sum);
        }
    }

    printf("Final total_sum = %d\n", total_sum);
    return 0;
}
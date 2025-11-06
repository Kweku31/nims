#include <stdio.h>
#include <stdlib.h>


__global__ void add(int *a, int *b, int *c) {
    c[blockIdx.x] = a[blockIdx.x] + b[blockIdx.x];
}


#define N 4
int main(void) {
    int *a, *b, *c;       // host copies of a, b, c
    int *d_a, *d_b, *d_c; // device copies of a, b, c
    int size = N * sizeof(int);

    // Alloc space for device copies of a, b, c
    cudaMalloc((void **)&d_a, size);
    cudaMalloc((void **)&d_b, size);
    cudaMalloc((void **)&d_c, size);

    // Alloc space for host copies of a, b, c and setup input values
    printf("The vector A:\n");
    a = (int *)malloc(size); 
    for (int i = 0; i < N; i++) {
        a[i] = rand() % 10; 
        printf("The vector A[%d] = %d\n", i, a[i]); 
    }
    // a = (int *)malloc(size); random_ints(a, N);
    // b = (int *)malloc(size); random_ints(b, N);
    printf("The vector B:\n");
    b = (int *)malloc(size); 
    for (int i = 0; i < N; i++) {
        b[i] = rand() % 10; 
        printf("The vector B[%d] = %d\n", i, b[i]); 
    }
    c = (int *)malloc(size);
    
    // Copy inputs to device
    cudaMemcpy(d_a, a, size, cudaMemcpyHostToDevice);
    cudaMemcpy(d_b, b, size, cudaMemcpyHostToDevice);

    // Launch add() kernel on GPU with N blocks
    add<<<N,1>>>(d_a, d_b, d_c);

    // Copy result back to host
    cudaMemcpy(c, d_c, size, cudaMemcpyDeviceToHost);

    //print
    printf("Hello There on Host, the result of your vector add is!\n");
    for (int i = 0; i < N; i++) {
        printf("The vector C[%d] = %d\n", i, c[i]); 
    }
    // printf("Sum is %d\n",*c);

    // Cleanup
    free(a); free(b); free(c);
    cudaFree(d_a); cudaFree(d_b); cudaFree(d_c);

    return 0;

}
    
    
    
    
    
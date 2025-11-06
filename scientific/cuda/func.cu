#include <stdio.h>


__global__ void add(int *a, int *b, int *c){
    *c = *a + *b;
}

int main(void) {
    int a, b, c;    //Host variables
    int *d_a, *d_b, *d_c;   //Device variables or pointers to be used by GPU
    int size = sizeof(int);

    cudaMalloc((void **) &d_a, size);
    cudaMalloc((void **) &d_b, size);
    cudaMalloc((void **) &d_c, size);

    a = 2;
    b = 7;

    cudaMemcpy(d_a, &a, size, cudaMemcpyHostToDevice);
    cudaMemcpy(d_b, &b, size, cudaMemcpyHostToDevice);


    add <<<1,1>>> (d_a, d_b, d_c);

    cudaMemcpy(&c, d_c, size, cudaMemcpyDeviceToHost);


    printf("Hello There on Host!\n");
    printf("Sum is %d\n",c);

    cudaFree(d_a);
    cudaFree(d_b);
    cudaFree(d_c);

    return 0;
}
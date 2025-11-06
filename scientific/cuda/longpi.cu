#include <stdio.h>
#include <curand_kernel.h>

__global__ void pi_kernel(unsigned long long *count, int points_per_thread, unsigned long long seed) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;

    // Initialize cuRAND random generator
    curandState state;
    curand_init(seed, idx, 0, &state);

    unsigned long long local_count = 0;
    for (int i = 0; i < points_per_thread; i++) {
        float x = curand_uniform(&state);
        float y = curand_uniform(&state);
        if (x * x + y * y <= 1.0f)
            local_count++;
    }

    atomicAdd(count, local_count);
}

int main() {
    const int threadsPerBlock = 256;
    const int numBlocks = 512; // Increase for longer runs
    const int points_per_thread = 100000000; // 1e6 per thread

    unsigned long long *d_count, h_count = 0;
    cudaMalloc((void **)&d_count, sizeof(unsigned long long));
    cudaMemset(d_count, 0, sizeof(unsigned long long));

    printf("Running Monte Carlo Pi estimation on GPU...\n");
    pi_kernel<<<numBlocks, threadsPerBlock>>>(d_count, points_per_thread, time(NULL));
    cudaDeviceSynchronize();

    cudaMemcpy(&h_count, d_count, sizeof(unsigned long long), cudaMemcpyDeviceToHost);
    cudaFree(d_count);

    unsigned long long total_points = (unsigned long long)threadsPerBlock * numBlocks * points_per_thread;
    double pi = 4.0 * (double)h_count / (double)total_points;

    printf("Estimated Pi = %.8f\n", pi);
    return 0;
}


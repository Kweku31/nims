#include<stdio.h>
#include<stdlib.h>
#include <time.h>
#include <omp.h>

double f(double x);
double trapezoidal_rule(double lowerlimit, double upperlimit, int num_of_steps);

int main()
{
    double lowerlimit = 0.0, upperlimit = 1;
    long long int num_of_steps = 1e10;
    clock_t start, end; // Timing variables
    double exec_time;

    start = clock();
    double result = trapezoidal_rule(lowerlimit, upperlimit, num_of_steps);
    end = clock();
    exec_time = (double) (end - start)/CLOCKS_PER_SEC; //calculate execution time
    printf("Approximate integral using Trapezoidal Rule: %f\n", result);
    printf("Execution time = %lf\n",exec_time);



}

//Function for f(x)
double f(double x) {
    return 4.0 / (1 + x * x);
}

//Function for trapezoidal
double trapezoidal_rule(double lowerlimit, double upperlimit, int num_of_steps) {
    double step_size = (upperlimit - lowerlimit) / (double)num_of_steps;  
    double sum = 0.5 * (f(lowerlimit) + f(upperlimit));  
    int nthreads;
    double *psum;

    #pragma omp parallel
    {
        int id,nthreads,i;
        
        id = omp_get_thread_num();
        // if (id == 0 ) 
        nthreads = omp_get_num_threads();
        
        #pragma omp single
        psum = (double*) calloc(nthreads, sizeof(double));

        #pragma omp barrier
        psum[id] = 0.0;
        for (i = id + 1; i < num_of_steps; i+=nthreads) {
            double x = lowerlimit + i * step_size;
            psum[id] += f(x);
        }

        #pragma omp critical
        sum += psum[id];

        #pragma omp single
        free(psum);     
    }  
    return sum * step_size;

}



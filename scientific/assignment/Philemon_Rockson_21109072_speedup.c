/*
Author: Philemon Rockson
Date: 7th March, 2025
Description: Writing a C script to distribute uneven payload to several processes using MPI_Scatterv and performing a sum on the payload at each process and
using MPI_Gather to collect the local sum and perform a total sum of the various local sum received 
and broadcast the total sum back to the various process.
The algorithm is being timed using the clock and to be used to plot a speedup graph*/
#include<stdio.h>
#include<stdlib.h>
#include<mpi.h>
#include <time.h>

int main (int argc, char* argv[] ){

    clock_t start, end; // Timing variables
   int N = atof(argv[1])*1e6/sizeof(int*); // Array size
   
   double exec_times; // Execution times for various sizes

   //define the variables to be used
   int rank, i, nprocs, num,recvcount;
   //define the pointers to be used
   int *rcv_buff,*send_buffer,*sendcount,*displs;
   long int *total;
   //define the sum variables
   long int local_sum = 0,Totalsum = 0;
   int local_len = 0;

    //Initialise MPI environment
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);

    
    if (rank == 0) {
        send_buffer = (int*)malloc(N * sizeof(int)); // Allocate memory only on the root process
        for (int i = 0; i < N; i++) {
            send_buffer[i] = i; 
        }
    }

    sendcount = (int*)malloc(N * sizeof(int));  //Allocate memory for sendcount
    displs = (int*)malloc(N * sizeof(int));  //Allocate memory for displs



    /*Sendcount and recvcount*/
    for (i = 0; i < nprocs; i++)
    {
        int lowerbound = (i*N)/nprocs ; 
        int upperbound = (N*(1+i))/nprocs - 1;
        sendcount[i] = upperbound - lowerbound + 1;
        displs[i] = lowerbound;

       
    }

    recvcount = sendcount[rank];
    // printf("%d\n",recvcount);
   
    rcv_buff = (int*)malloc(recvcount * sizeof(int));

    MPI_Scatterv(send_buffer, sendcount, displs, MPI_INT, rcv_buff, recvcount, MPI_INT, 0, MPI_COMM_WORLD);

    start = clock();

   
//    printf("Process %d received: ", rank);
//    for (i = 0; i < recvcount; i++) {
    //    printf("%d ",rcv_buff[i]);
//    }
//    printf("\n");

   for (int i = 0; i < recvcount; i++) {
    local_sum += rcv_buff[i];
    }
    // printf("Process %d computed local sum: %ld\n", rank, local_sum);

    if (rank == 0) {
        total = (long int*)malloc(N * sizeof(int));
    }

    MPI_Gather(&local_sum, 1, MPI_LONG, total, 1, MPI_LONG, 0, MPI_COMM_WORLD);

    if (rank == 0) {
        for (int i = 0; i < nprocs; i++) {
            Totalsum += total[i];
        }
        // printf("Root process has total sum: %ld\n", Totalsum);

    }

    end = clock();
    exec_times = (double) (end - start)/CLOCKS_PER_SEC; //calculate execution time
    // printf("Execution time = %lf for rank %d\n\n",exec_times,rank);
    // printf("%lf\t\n",exec_times);

    double max_exec_time;
    MPI_Reduce(&exec_times, &max_exec_time, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);
    if (rank == 0) {
        // printf("Maximum execution time across all ranks: %lf seconds\n", max_exec_time);
        printf("%lf\n", max_exec_time);
    }

    // Broadcast data to other ranks
    MPI_Bcast(&Totalsum,1, MPI_LONG,0,MPI_COMM_WORLD);

    // printf("ProcID %d has the value %ld now\n", rank, Totalsum);


   free(total);
   free(rcv_buff);
   free(sendcount);
   free(displs);
   if (rank == 0) {
       free(send_buffer);
   }
        MPI_Finalize();
    
    return 0;
}



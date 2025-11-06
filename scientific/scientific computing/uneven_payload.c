 #include<stdio.h>
 #include<stdlib.h>
 #include<mpi.h>
 #define N 8
 
 int main (int argc, char* argv[] ){
 
 
    int rank, nprocs, i, num,recvcount;
    int *rcv_buff,*send_buffer,*sendcount,*displs;
    int local_sum = 0,Totalsum = 0;
    int vec[N],local_len = 0;
 
     MPI_Status status;
 
     MPI_Init(&argc, &argv);
     MPI_Comm_rank(MPI_COMM_WORLD, &rank);
     MPI_Comm_size(MPI_COMM_WORLD, &nprocs);
 
    //  /*Populate Vector*/
    //  for (i=0; i<N;i++){
    //      vec[i] = i;
    //  }
     
     if (rank == 0) {
         send_buffer = (int*)malloc(N * sizeof(int)); // Allocate memory only on the root process
         for (int i = 0; i < N; i++) {
             send_buffer[i] = i; 
         }
     }

     sendcount = (int*)malloc(N * sizeof(int));
     displs = (int*)malloc(N * sizeof(int));
 
     /*Domain Decomposition*/
    //  local_len = N/nprocs ;
      
     
 
     printf("\n");

 
     /*Sendcount and recvcount*/
     for (i = 0; i < nprocs; i++)
     {
         int lowerbound = (rank*N)/nprocs ; 
         int upperbound = (N*(1+rank))/nprocs - 1;
         sendcount[i] = upperbound - lowerbound + 1;
         displs[i] = lowerbound;
        //  printf("Send count for rank %d is :%d\n",rank,sendcount[i]);
        //  printf("Displs for rank %d is :%d\n",rank,displs[i]);

        
     }

     recvcount = sendcount[rank];
     printf("%d\n",recvcount);
    
     rcv_buff = (int*)malloc(recvcount * sizeof(int));

     MPI_Scatterv(send_buffer, sendcount, displs, MPI_INT, rcv_buff, recvcount, MPI_INT, 0, MPI_COMM_WORLD);

    
    printf("Process %d received: ", rank);
    for (i = 0; i < recvcount; i++) {
        printf("%d ",rcv_buff[i]);
    }
    printf("\n");

    // for (i=lowerbound; i<=upperbound;i++){
    //    // printf("rank= %d, element=%d \n",rank, vec[i]);
    //    local_sum += vec[i];
   
    // }
    // for (int i = 0; i < nprocs; i++) {
    //     // printf("rcv_buff %d",rcv_buff[i]);
    // }

    // // int* global_sums = NULL;
    // //  // Make an else
    //  if(rank == 0){ 
    //     //  Totalsum = local_sum;
    //     //  global_sums = (int*)malloc(N * sizeof(int));

    //     //  printf("rank= %d, first Local Sum= %d\n",rank, local_sum);
 
    //      for (i=1; i <=nprocs-1; i++){
    //      //printf("ProcID %d sent the value %d, to procID %d \n", rank, rank, next);
    //      MPI_Recv(&rcv_buff,1, MPI_INT,i,0,MPI_COMM_WORLD, &status);

     
    //     Totalsum +=rcv_buff[i];
    //      }
    //  }
         
    
    //  printf(" Before Bcast: ProcID %d has the value %d now\n", rank, local_sum);

    //  printf(" Before Bcast: ProcID %d has the value %d now\n", rank, Totalsum);
     /* ranks printing total sum they have */
 
     // Broadcast data to other ranks
    //  MPI_Bcast(&Totalsum,1, MPI_INT,0,MPI_COMM_WORLD);
 
    //  printf("ProcID %d has the value %d now\n", rank, Totalsum);
 
    free(rcv_buff);
    free(sendcount);
    free(displs);
    if (rank == 0) {
        free(send_buffer);
    }
         MPI_Finalize();
     
     return 0;
 }
 
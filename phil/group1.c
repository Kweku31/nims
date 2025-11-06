#include <stdio.h>
#include <stdlib.h>
#include <mpi.h>

int main( int argc, char *argv[]){


	MPI_Status status;
	int mod, local_sum=0,N=8,nprocs,lower_bound,upper_bound,i,rank,load,new_N, *vec1, *vec2,send_buff,total_sum;

	MPI_Init (&argc, &argv);

	MPI_Comm_rank(MPI_COMM_WORLD, &rank);
	MPI_Comm_size(MPI_COMM_WORLD, &nprocs);

	if(nprocs > N){
		printf("You are assigning more than the needed processors for the work. Please change the number of processors used.\n");
	}
	
	else if( N % nprocs == 0){

		load = N/nprocs;
		lower_bound = load * rank;
		upper_bound = (load * rank) + (load - 1);
		vec1 = (int *)malloc(N*sizeof(int));

		for(i=0;i<=N;i++){
			vec1[i] = i;
		}

		for(i=lower_bound;i<=upper_bound;i++){
               	        local_sum += vec1[i];
                }

		if(rank !=0){
			send_buff = local_sum;
			printf("rank %d has a sum of %d\n",rank,local_sum);
			MPI_Send(&send_buff,1,MPI_INT,0,0,MPI_COMM_WORLD);
			printf("rank %d is sending %d to rank 0\n",rank,local_sum);

		}

		if(rank==0){
			total_sum = local_sum;
			printf("rank %d has a sum of %d\n",rank,total_sum);

			for(i=1;i<=nprocs-1;i++){
				MPI_Recv(&send_buff,1,MPI_INT,i,0,MPI_COMM_WORLD,&status);
				printf("rank %d has received %d from rank %d\n",rank,send_buff,i);
				total_sum += send_buff;
			}

                	printf("rank %d has a total sum of %d now\n",rank,total_sum);

		}

		free(vec1);
	}

	else if( N % nprocs != 0){

		mod = N % nprocs;
		new_N = N - mod;
		load = new_N/nprocs;

		vec1 = (int *)malloc(N*sizeof(int));
		vec2 = (int *)malloc(mod*sizeof(int));

		for(i=0;i<N;i++){
			vec1[i]=i;
		}

		lower_bound = load * rank;
		upper_bound = (load * rank) + (load - 1);
		printf("rank %d is initially adding from index %d to index %d \n",rank,lower_bound,upper_bound);

		for(i=lower_bound;i<=upper_bound;i++){
			local_sum += vec1[i];
		}
	
		for(i=0;i<mod;i++){
			vec2[i] = vec1[i+new_N];
		}

		for(i=0;i<mod;i++){
			if(rank==i){
				local_sum += vec2[i];
				printf("rank %d is additionally adding up index %d \n",rank,i+new_N);
			}
		}

		if(rank!=0){
			send_buff = local_sum;
			MPI_Send(&send_buff,1,MPI_INT,0,0,MPI_COMM_WORLD);
			printf("rank %d has a sum of %d\n",rank,local_sum);
			printf("rank %d is sending %d to rank 0\n",rank,local_sum);
		}

		if(rank==0){
			total_sum = local_sum;
			printf("rank %d has a sum of %d\n",rank,local_sum);
			for(i=1;i<nprocs;i++){
				MPI_Recv(&send_buff,1,MPI_INT,i,0,MPI_COMM_WORLD,&status);
				printf("rank %d has received %d from rank %d\n",rank,send_buff,i);
				total_sum += send_buff;
			}
			printf("rank %d has %d now\n",rank,total_sum);
		}
		free(vec1);
		free(vec2);

	}


	MPI_Finalize();
	return 0;
}

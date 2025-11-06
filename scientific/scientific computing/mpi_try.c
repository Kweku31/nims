/*
 * Copyright (C) 2001-2013 The Abdus Salam, International Centre of Theoretical Physics (ICTP)
 * Copyright (C) 2022 The National Institute for Mathemical Sciecne(NIMS), KNUST
 *
 * This file is distributed under the terms of the GNU General Public License.
 * See http://www.gnu.org/copyleft/gpl.txt
 *
 * The code was developed for the hands-on session for teaching Parallel programming in Scientific Coputing
 * The example is inspired by it's development of the MPHC program Parallel programming Hands-On Session,
 * ...and by  "Introduction to High Performance Computing for Scientists and Engineers",
 * by Georg Hager and Gerhard Wellein
 *
 * Author: Elliot Menkah(NIMS, KNUST), Peter Amoako-Yerenkyi(NIMS, KNUST), Ivan Girotto(ICTP)
 * Last update: Sept-2022
 * Email: esmenkah@knust.edu.gh, elliotsmenkah@gmail.com
 */

 #include<stdlib.h>
 #include<stdio.h>
 #include <mpi.h>
 
 #define SIZE 1
 
 int main(int argc, char *argv[]){
 
   int rank, size;
   int i;
   int next,prev;
   
   MPI_Status  status;
   
   
   MPI_Init( &argc, &argv);
   
   MPI_Comm_rank(MPI_COMM_WORLD, &rank);
   MPI_Comm_size(MPI_COMM_WORLD, &size);
   
   int buff=0;
   next=(rank+1)%size;
   prev=(rank+size-1)%size;
 
   printf("I am %d\n", rank );
   
   if((rank)%2 == 1){
         MPI_Send(&rank, SIZE, MPI_INT,next,0, MPI_COMM_WORLD);
         MPI_Recv(&buff, SIZE, MPI_INT,prev,0, MPI_COMM_WORLD, &status);
        }
   else{
//    if (rank == 0){
        MPI_Recv(&buff, SIZE, MPI_INT,prev,0, MPI_COMM_WORLD, &status);
        MPI_Send(&rank, SIZE, MPI_INT,next,0, MPI_COMM_WORLD);

   }
   
   
     printf("I am rank %d  with %d\n", rank ,buff);
   
   
   MPI_Finalize();
   
   return 0;
 }
 
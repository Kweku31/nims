/*
 * Copyright (C) 2022 The National Institute for Mathemical Sciecne(NIMS), KNUST
 * Copyright (C) 2022 The Department of Chemistry, KNUST
 *
 * This file is distributed under the terms of the GNU General Public License.
 * See http://www.gnu.org/copyleft/gpl.txt
 *
 * The code was developed for the hands-on session for teaching Parallel programming in Scientific Coputing
 * The example is inspired by it's development of the MPHC program Parallel programming Hands-On Session,
 * ...and by  "Introduction to High Performance Computing for Scientists and Engineers",
 * by Georg Hager and Gerhard Wellein
 *
 * Author: Elliot Menkah(NIMS, KNUST), Peter Amoako-Yerenkyi(NIMS, KNUST),
 * Last update: July-2023
 * Email: esmenkah@knust.edu.gh, elliotsmenkah@gmail.com
 */
#include<stdlib.h>
#include<stdio.h>
#include<mpi.h>

int main(int argc, char *argv[]){

  int rank, size;
  
  MPI_Status  status;
  
  MPI_Init( &argc, &argv);
  
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &size);
  

  printf("Hello World, I am rank %d\n", rank );
  
  MPI_Finalize();
  
  return 0;
}

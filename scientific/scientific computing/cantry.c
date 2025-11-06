#include <stdio.h>      // Standard I/O functions
#include <stdlib.h>     // Memory allocation and standard library functions
#include <math.h>       // Mathematical functions (sqrt)
#include <mpi.h>        // Message Passing Interface for parallel computing

// Function to allocate a contiguous 2D matrix
// This creates a single block of memory for the entire matrix for efficient MPI communication
double** allocate_matrix(int rows, int cols) {
    // Allocate a single contiguous block for all matrix elements
    double *data = (double*)malloc(rows * cols * sizeof(double));
    // Allocate an array of pointers to each row
    double **matrix = (double**)malloc(rows * sizeof(double*));
    // Set each row pointer to the beginning of its row in the contiguous block
    for (int i = 0; i < rows; i++) {
        matrix[i] = &data[i * cols];  // Point to the start of each row
    }
    return matrix;  // Return the 2D matrix structure
}

// Function to free a contiguous 2D matrix
// Properly deallocates the memory in reverse order of allocation
void free_matrix(double** matrix) {
    if (matrix != NULL) {          // Check if matrix exists
        free(matrix[0]);           // Free the contiguous data block (all elements)
        free(matrix);              // Free the array of row pointers
    }
}

// Function to initialize matrix with random values
// Used for testing - in real applications, data would be loaded from files
void initialize_matrix(double** matrix, int rows, int cols, int seed) {
    srand(seed);  // Set random seed for reproducible results
    for (int i = 0; i < rows; i++) {           // Loop through each row
        for (int j = 0; j < cols; j++) {       // Loop through each column
            matrix[i][j] = (double)(rand() % 10); // Fill with random values 0-9
        }
    }
}

// Function to print a matrix with process information
// Helpful for debugging and verifying results
void print_matrix(double** matrix, int rows, int cols, char* name, int rank) {
    printf("[Process %d] %s:\n", rank, name);  // Print process ID and matrix name
    for (int i = 0; i < rows; i++) {           // Loop through each row
        for (int j = 0; j < cols; j++) {       // Loop through each column
            printf("%6.2f ", matrix[i][j]);    // Print each element with formatting
        }
        printf("\n");  // New line after each row
    }
    printf("\n");  // Extra new line after the entire matrix
}

// Function for matrix multiplication of two blocks
// Standard O(n³) matrix multiplication algorithm
void multiply_blocks(double** A, double** B, double** C, int block_size) {
    for (int i = 0; i < block_size; i++) {         // Loop through rows of result
        for (int j = 0; j < block_size; j++) {     // Loop through columns of result
            C[i][j] = 0.0;                         // Initialize result element to zero
            for (int k = 0; k < block_size; k++) { // Dot product of row i and column j
                C[i][j] += A[i][k] * B[k][j];      // Accumulate the product
            }
        }
    }
}

// Function to add two matrices (A = A + B)
// Used to accumulate partial results in Cannon's algorithm
void add_matrices(double** A, double** B, int block_size) {
    for (int i = 0; i < block_size; i++) {         // Loop through each row
        for (int j = 0; j < block_size; j++) {     // Loop through each column
            A[i][j] += B[i][j];                    // Add corresponding elements
        }
    }
}

// Main function - entry point of the program
int main(int argc, char *argv[]) {
    // MPI variables
    int rank;           // Unique ID for each process (0 to size-1)
    int size;           // Total number of processes
    int grid_size;      // Size of process grid (√p)
    int my_row, my_col; // Coordinates of this process in the grid
    MPI_Comm grid_comm; // Communicator for the process grid
    
    // Initialize MPI environment
    MPI_Init(&argc, &argv);
    // Get the rank (ID) of this process
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    // Get the total number of processes
    MPI_Comm_size(MPI_COMM_WORLD, &size);
    
    // Check if we have a perfect square number of processes
    // Cannon's algorithm requires a square grid of processes
    grid_size = (int)sqrt(size);  // Calculate grid size as square root of total processes
    if (grid_size * grid_size != size) {  // Verify it's a perfect square
        if (rank == 0) {  // Only root process prints error
            printf("Number of processes must be a perfect square! (Got %d, need square like 4, 9, 16...)\n", size);
        }
        MPI_Finalize();  // Clean up MPI environment
        return 1;        // Exit with error code
    }
    
    // Matrix dimensions - using smaller size for testing
    int n = 4; // Total matrix size
    // Check if matrix size is divisible by grid size
    if (n % grid_size != 0) {
        if (rank == 0) {  // Only root process prints error
            printf("Matrix size %d must be divisible by grid size %d!\n", n, grid_size);
        }
        MPI_Finalize();  // Clean up MPI environment
        return 1;        // Exit with error code
    }
    
    // Calculate the size of each block assigned to a process
    int block_size = n / grid_size;
    
    // Root process prints configuration information
    if (rank == 0) {
        printf("Running Cannon's Algorithm:\n");
        printf("  Matrix size: %dx%d\n", n, n);
        printf("  Process grid: %dx%d\n", grid_size, grid_size);
        printf("  Block size: %dx%d\n", block_size, block_size);
    }
    
    // Create Cartesian topology for process grid
    // This organizes processes into a 2D grid with wraparound connections
    int dims[2] = {grid_size, grid_size};  // Grid dimensions (rows, columns)
    int periods[2] = {1, 1};               // Enable wraparound (torus topology)
    int reorder = 1;                       // Allow MPI to optimize process ordering
    // Create the grid communicator
    MPI_Cart_create(MPI_COMM_WORLD, 2, dims, periods, reorder, &grid_comm);
    
    // Get my coordinates in the grid
    int coords[2];  // Array to store coordinates
    // Get coordinates of this process in the Cartesian grid
    MPI_Cart_coords(grid_comm, rank, 2, coords);
    my_row = coords[0];  // Row coordinate of this process
    my_col = coords[1];  // Column coordinate of this process
    
    // Allocate memory for local blocks using contiguous memory
    // Each process stores its portion of matrices A, B, and C
    double **A_block = allocate_matrix(block_size, block_size);  // Local block of matrix A
    double **B_block = allocate_matrix(block_size, block_size);  // Local block of matrix B
    double **C_block = allocate_matrix(block_size, block_size);  // Local block of result matrix C
    double **temp_block = allocate_matrix(block_size, block_size); // Temporary storage for multiplication
    
    // Initialize matrices with random values for testing
    // In real applications, data would be distributed from files
    initialize_matrix(A_block, block_size, block_size, rank + 1);    // Initialize A with seed based on rank
    initialize_matrix(B_block, block_size, block_size, rank + 100);  // Initialize B with different seed
    
    // Initialize C_block to zeros (accumulator for results)
    for (int i = 0; i < block_size; i++) {         // Loop through each row
        for (int j = 0; j < block_size; j++) {     // Loop through each column
            C_block[i][j] = 0.0;                   // Set each element to zero
        }
    }
    
    // Print initial blocks for small matrices (debugging)
    if (n <= 6) {
        char nameA[50], nameB[50];  // Buffer for matrix names
        sprintf(nameA, "Process (%d,%d) A_block", my_row, my_col);  // Create name for A
        sprintf(nameB, "Process (%d,%d) B_block", my_row, my_col);  // Create name for B
        print_matrix(A_block, block_size, block_size, nameA, rank); // Print A block
        print_matrix(B_block, block_size, block_size, nameB, rank); // Print B block
    }
    
    // Synchronize all processes before starting algorithm
    MPI_Barrier(MPI_COMM_WORLD);
    
    // ==================== CANNON'S ALGORITHM ====================
    
    // Step 1: Initial Alignment (Skewing)
    // This phase aligns the blocks so that each process has the correct initial blocks
    int left_neighbor, right_neighbor, up_neighbor, down_neighbor;
    
    // Get neighbors for shifting in the torus topology
    // Find left and right neighbors for horizontal shifts (matrix A)
    MPI_Cart_shift(grid_comm, 1, -1, &right_neighbor, &left_neighbor);  // Left shift for A
    // Find up and down neighbors for vertical shifts (matrix B)  
    MPI_Cart_shift(grid_comm, 0, -1, &down_neighbor, &up_neighbor);     // Up shift for B
    
    // Initial skew: Shift A blocks left by my_row positions
    // This creates the diagonal alignment needed for Cannon's algorithm
    for (int shift_step = 0; shift_step < my_row; shift_step++) {
        // Send A_block to left neighbor and receive from right neighbor
        // This performs a circular shift in the row
        MPI_Sendrecv_replace(A_block[0], block_size * block_size, MPI_DOUBLE,
                           left_neighbor, 0, right_neighbor, 0, grid_comm, MPI_STATUS_IGNORE);
    }
    
    // Initial skew: Shift B blocks up by my_col positions
    // This creates the diagonal alignment needed for Cannon's algorithm
    for (int shift_step = 0; shift_step < my_col; shift_step++) {
        // Send B_block to up neighbor and receive from down neighbor
        // This performs a circular shift in the column
        MPI_Sendrecv_replace(B_block[0], block_size * block_size, MPI_DOUBLE,
                           up_neighbor, 0, down_neighbor, 0, grid_comm, MPI_STATUS_IGNORE);
    }
    
    // Step 2: Main Computation Loop
    // Each iteration performs local multiplication and shifts blocks
    for (int step = 0; step < grid_size; step++) {
        // Local matrix multiplication: C += A * B
        // Multiply current A and B blocks, store result in temp_block
        multiply_blocks(A_block, B_block, temp_block, block_size);
        // Add the multiplication result to the accumulated C_block
        add_matrices(C_block, temp_block, block_size);
        
        // Shift blocks for next iteration (except on the last step)
        if (step < grid_size - 1) {
            // Shift A left by 1 position for next iteration
            MPI_Sendrecv_replace(A_block[0], block_size * block_size, MPI_DOUBLE,
                               left_neighbor, 0, right_neighbor, 0, grid_comm, MPI_STATUS_IGNORE);
            
            // Shift B up by 1 position for next iteration
            MPI_Sendrecv_replace(B_block[0], block_size * block_size, MPI_DOUBLE,
                               up_neighbor, 0, down_neighbor, 0, grid_comm, MPI_STATUS_IGNORE);
        }
    }
    
    // ==================== RESULTS COLLECTION ====================
    // Gather all partial results at the root process for final output
    
    if (rank == 0) {  // Root process coordinates result collection
        // Allocate memory for the full result matrix
        double **full_C = allocate_matrix(n, n);
        
        // Copy local C_block from root process (process 0)
        for (int i = 0; i < block_size; i++) {         // Loop through rows of local block
            for (int j = 0; j < block_size; j++) {     // Loop through columns of local block
                full_C[i][j] = C_block[i][j];          // Copy element to full matrix
            }
        }
        
        // Receive blocks from all other processes
        for (int src = 1; src < size; src++) {  // Start from process 1 (process 0 is root)
            // Allocate buffer for receiving data
            double *recv_buffer = (double*)malloc(block_size * block_size * sizeof(double));
            // Receive C_block from source process
            MPI_Recv(recv_buffer, block_size * block_size, MPI_DOUBLE, src, 0, grid_comm, MPI_STATUS_IGNORE);
            
            // Get coordinates of the source process in the grid
            int src_coords[2];
            MPI_Cart_coords(grid_comm, src, 2, src_coords);
            int src_row = src_coords[0];  // Row coordinate of source
            int src_col = src_coords[1];  // Column coordinate of source
            
            // Place received block in correct position in full matrix
            for (int i = 0; i < block_size; i++) {         // Loop through block rows
                for (int j = 0; j < block_size; j++) {     // Loop through block columns
                    // Calculate global coordinates in full matrix
                    int global_i = src_row * block_size + i;   // Global row index
                    int global_j = src_col * block_size + j;   // Global column index
                    // Copy from receive buffer to full matrix
                    full_C[global_i][global_j] = recv_buffer[i * block_size + j];
                }
            }
            
            // Free the receive buffer
            free(recv_buffer);
        }
        
        // Print final result matrix
        print_matrix(full_C, n, n, "Final Result Matrix C", rank);
        
        // Free the full result matrix
        free_matrix(full_C);
        
    } else {  // Non-root processes send their results to root
        // Send local C_block to root process (process 0)
        MPI_Send(C_block[0], block_size * block_size, MPI_DOUBLE, 0, 0, grid_comm);
    }
    
    // Cleanup: Free all allocated memory
    free_matrix(A_block);       // Free local A block
    free_matrix(B_block);       // Free local B block
    free_matrix(C_block);       // Free local C block
    free_matrix(temp_block);    // Free temporary block
    
    // Free the grid communicator
    MPI_Comm_free(&grid_comm);
    // Finalize MPI environment
    MPI_Finalize();
    
    return 0;  // Successful program termination
}
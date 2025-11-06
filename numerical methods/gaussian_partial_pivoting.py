#---------------
#Author : Philemon Rockson
#Description: Guassian elimination for Ax = b
#---------------
import numpy as np


def partial_pivoting(A, b):
    """
    Solves Ax = y for x using gaussian elimination partial pivoting.
    A must be an full matrix.
    """
    A = A.astype(float) 
    b = b.astype(float) 
    n = A.shape[0]
    print("n",n)
    #print matrix A
    # print("Matrix U:\n", A)

    for i in range(n - 1):
        # find row with max element in column i
        max_row = np.argmax(np.abs(A[i:, i])) + i
        print("max:",max_row)
        if A[max_row, i] == 0:
            raise ValueError("Matrix is singular or nearly singular.")

        # Swap rows in A and b
        if max_row != i:
            A[[i, max_row]] = A[[max_row, i]]
            b[[i, max_row]] = b[[max_row, i]]

        # Start from the last row and go upward
        for j in range(i+1,n):
            fact = A[j,i]/A[i,i]
            for k in range(n):
                A[j,k] = A[j,k] - fact*A[i,k]
                b[j] = b[j] - fact*b[i]
        

    x = np.zeros(n)
    
    # Start from the last row and go upward
    for i in range(n-1, -1, -1):
        if A[i, i] == 0:
            raise ValueError("Matrix is singular (zero on diagonal).")
        x[i] = (b[i] - np.dot(A[i, i+1:n], x[i+1:])) / A[i, i]
        
    return x, A, b



# Example: Generate random upper triangular matrix and vector
# n = 4
# n = int(input("Enter the size of the matrix (n): "))

# B = np.random.randint(1,n+1,(n, n+1))
A = np.array([[2,1,-1],[4,3,-2],[1,2,3]], dtype=float)
print("The Matrix A before:\n", A)
b = np.array([[8],[19],[14]], dtype=float)
print("The Matrix b before:\n", b)
# y = np.random.randint(1, n, n)

# Solve Ux = y
x, A, b = partial_pivoting(A, b)

# Check result
print("Matrix A:\n", A)
print("\nVector b:\n", b)
print("\nSolution x:\n", x)
print("\nCheck (A x x):\n", np.dot(A, x))

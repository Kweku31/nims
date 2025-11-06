#---------------
#Author : Philemon Rockson
#Description: Guassian elimination for A
#---------------
import numpy as np


def gaussian_elimination(A):
    """
    Solves Ux = y for x using back substitution.
    U must be an upper triangular matrix.
    """
    A = A.astype(float)  
    n = A.shape[0]

    #print matrix A
    print("Matrix U:\n", A)

    # Start from the last row and go upward
    for i in range(0,n):
        for j in range(i+1,n):
            fact = A[j,i]/A[i,i]
            for k in range(n):
                A[j,k] = A[j,k] - fact*A[i,k]

            
            # A[j,i:] = A[j,i:] - fact*A[i,i:]
            np.set_printoptions(precision=2, suppress=False)

    
    return A



# Example: Generate random upper triangular matrix and vector
# n = 4
n = int(input("Enter the size of the matrix (n): "))

A = np.random.randint(1,n+1,(n, n))
# y = np.random.randint(1, n, n)

# Solve Ux = y
x = gaussian_elimination(A)

# Check result
# print("Matrix U:\n", A)
# print("\nVector y:\n", y)
print("\nSolution x:\n", x)
# print("\nCheck (U @ x):\n", np.dot(U, x))

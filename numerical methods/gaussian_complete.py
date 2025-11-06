#---------------
#Author : Philemon Rockson
#Description: Guassian elimination for Ax = b
#---------------
import numpy as np


def gaussian_elimination(B):
    """
    Solves Ax = y for x using back substitution.
    A must be an full matrix.
    """
    A = B.astype(float)  
    n = A.shape[0]
    print("n",n)
    #print matrix A
    # print("Matrix U:\n", A)

    b = A[:, -1]
    print("b =", b)

    # Start from the last row and go upward
    for i in range(0,n):
        for j in range(i+1,n):
            fact = A[j,i]/A[i,i]
            A[j,0:] = A[j,0:] - fact*A[i,0:]
            A[j,-1] = A[j,-1] - fact*A[i,-1]

            np.set_printoptions(precision=2, suppress=False)

    x = np.zeros(n)
    
    # Start from the last row and go upward
    for i in range(n-1, -1, -1):
        if A[i, i] == 0:
            raise ValueError("Matrix is singular (zero on diagonal).")
        x[i] = (A[i,-1] - np.dot(A[i, i+1:n], x[i+1:])) / A[i, i]
        
    return x, A



# Example: Generate random upper triangular matrix and vector
# n = 4
n = int(input("Enter the size of the matrix (n): "))

B = np.random.randint(1,n+1,(n, n+1))
# y = np.random.randint(1, n, n)

# Solve Ux = y
y, U = gaussian_elimination(B)

# Check result
print("Matrix U:\n", U)
# print("\nVector y:\n", y)
print("\nSolution x:\n", y)
# print("\nCheck (U @ x):\n", np.dot(U, x))

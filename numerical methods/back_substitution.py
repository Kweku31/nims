#---------------
#Author : Philemon Rockson
#Description: Backward subtitution for Ax = b
#---------------
import numpy as np

def back_substitution(U, y):
    """
    Solves Ux = y for x using back substitution.
    U must be an upper triangular matrix.
    """
    n = U.shape[0]
    x = np.zeros(n)
    
    # Start from the last row and go upward
    for i in range(n-1, -1, -1):
        if U[i, i] == 0:
            raise ValueError("Matrix is singular (zero on diagonal).")
        x[i] = (y[i] - np.dot(U[i, i+1:], x[i+1:])) / U[i, i]
    
    return x


# Example: Generate random upper triangular matrix and vector
# n = 4
n = int(input("Enter the size of the matrix (n): "))

A = np.random.randint(1,n+1,(n, n))
U = np.triu(A)  # Make it upper triangular
y = np.random.randint(1, n, n)

# Solve Ux = y
x = back_substitution(U, y)

# Check result
print("Upper Triangular Matrix U:\n", U)
print("\nVector y:\n", y)
print("\nSolution x:\n", x)
print("\nCheck (U.x):\n", np.dot(U, x))

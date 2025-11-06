#---------------
#Author : Philemon Rockson
#Description: Forward substitution for Ax = b
#---------------
import numpy as np

def forward_substitution(L, y):
    """
    Solves Lx = y for x using forward substitution.
    L must be an lower triangular matrix.
    """
    n = L.shape[0]
    x = np.zeros(n)
    
    # Start from the first row and go downward
    for i in range(n):
        if L[i, i] == 0:
            raise ValueError("Matrix is singular (zero on diagonal).")
        x[i] = (y[i] - np.dot(L[i, :i], x[:i])) / L[i, i]
    
    return x


# Example: Generate random lower triangular matrix and vector
# n = 4
n = int(input("Enter the size of the matrix (n): "))

A = np.random.randint(1,n+1,(n, n))
L = np.tril(A)  # Make it lower triangular
y = np.random.randint(1, n, n)

# Solve Lx = y
x = forward_substitution(L, y)

# Check result
print("Lower Triangular Matrix L:\n", L)
print("Matrix A:\n", A)
print("\nVector y:\n", y)
print("\nSolution x:\n", x)
print("\nCheck (L.x):\n", np.dot(L, x))

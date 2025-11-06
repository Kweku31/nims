import numpy as np
import matplotlib.pyplot as plt

# Define x values
x_vals = np.linspace(-1.92, 2.08, 1000)

# Factored form: (x - 2)^9
p_factored = (x_vals - 2)**9

# Expanded form: x^9 - 18x^8 + ... - 512
coeffs = [1, -18, 144, -672, 2016, -4032, 5376, -4608, 2304, -512]
p_expanded = np.polyval(coeffs, x_vals)

# Plot both
plt.figure(figsize=(10, 6))
plt.plot(x_vals, p_factored, label='Factored: (x - 2)^9', linestyle='--')
plt.plot(x_vals, p_expanded, label='Expanded polynomial', linestyle='-')
plt.legend()
plt.title('Comparison of Factored vs Expanded Forms')
plt.xlabel('x')
plt.ylabel('p(x)')
plt.grid(True)
plt.tight_layout()

# Save the plot instead of showing it (since you're in a terminal)
plt.savefig("polynomial_comparison.png")
print("Plot saved as 'polynomial_comparison.png'")

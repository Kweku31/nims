import numpy as np
import matplotlib.pyplot as plt

def custom_periodic(x, period=2):
    # x_mod = abs((x % period) - period/2)
    x_mod = x % period
    return np.piecewise(x_mod, 
        [(-1 < x_mod) & (x_mod <= 0), (0 < x_mod) & (x_mod <= 1)],  # Conditions
        [lambda x: x+1, lambda x:1 - x]  # Corresponding functions
    )


x = np.linspace(-3, 5, 1000)  # Range from -3 to 5
y = custom_periodic(x)

plt.figure(figsize=(8, 5))
plt.plot(x, y, 'b-', linewidth=2)
plt.xlabel('x')
plt.ylabel('f(x)')
plt.title('Piecewise Function Example')
plt.grid(True)
plt.show()

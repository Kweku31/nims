import numpy as np
import matplotlib.pyplot as plt
from scipy.integrate import solve_ivp

# ---------- PARAMETERS ----------
# Growth kinetics
mu1_max = 0.8    # h^-1, acidogens
Ks1     = 50.0   # mg/L
mu2_max = 0.6    # h^-1, methanogens
Ks2     = 30.0   # mg/L
Ki      = 200.0  # mg/L inhibition constant (Haldane)

# Yields
K1 = 1/40   # gX/gS
K2 = 1/120  # gX/gS
K3 = 1/270  # VFA produced per unit S1 consumed
K4 = 1/50  # CO2 per unit S1 consumed
K5 = 1/350  # CO2 per unit S2 consumed
K6 = 1/450  # CH4 per unit S2 consumed


# Reactor parameters
D = 0.1               # dilution rate (h^-1)
S1_in = 1000.0        # feed organic matter (mg/L)
S2_in = 0.0           # feed VFA (mg/L)

# ---------- KINETIC FUNCTIONS ----------
def mu1(S1):
    return mu1_max * S1 / (Ks1 + S1)

def mu2(S2):
    # Haldane inhibition
    return mu2_max * S2 / (Ks2 + S2 + (S2**2)/Ki)

# ---------- ODE SYSTEM ----------
def rhs(t, y):
    X1, X2, S1, S2 = y

    # Rates
    r1 = mu1(S1) * X1
    r2 = mu2(S2) * X2

    # Balances
    dX1 = (mu1(S1) - D) * X1
    dX2 = (mu2(S2) - D) * X2
    dS1 = D*(S1_in - S1) - K1*r1
    dS2 = D*(S2_in - S2) + K3*r1 - K2*r2

    return [dX1, dX2, dS1, dS2]

# ---------- SIMULATION ----------
t_span = (0, 200)
y0 = [10.0, 5.0, 500.0, 50.0]  # initial values: X1, X2, S1, S2

sol = solve_ivp(rhs, t_span, y0, t_eval=np.linspace(*t_span, 1000))

# ---------- TIME PLOTS ----------
fig, axs = plt.subplots(2, 2, figsize=(10,6))
axs[0,0].plot(sol.t, sol.y[0]); axs[0,0].set_title("X1 (acidogens)")
axs[0,1].plot(sol.t, sol.y[1]); axs[0,1].set_title("X2 (methanogens)")
axs[1,0].plot(sol.t, sol.y[2]); axs[1,0].set_title("S1 (organic matter)")
axs[1,1].plot(sol.t, sol.y[3]); axs[1,1].set_title("S2 (VFA)")
plt.tight_layout()
plt.show()

# ---------- PHASE DIAGRAM (example: X1 vs X2) ----------
# Grid for vector field
x1 = np.linspace(0, 40, 20)
x2 = np.linspace(0, 40, 20)
X1g, X2g = np.meshgrid(x1, x2)
S1_eq = 200.0   # fix S1, S2 near equilibrium (approx)
S2_eq = 50.0

dX1g = (mu1(S1_eq)-D)*X1g
dX2g = (mu2(S2_eq)-D)*X2g

plt.figure(figsize=(6,6))
plt.quiver(X1g, X2g, dX1g, dX2g, angles="xy")
plt.plot(sol.y[0], sol.y[1], 'r')  # trajectory from simulation
plt.xlabel("X1 (acidogens)")
plt.ylabel("X2 (methanogens)")
plt.title("Phase plane: X1 vs X2")
plt.grid()
plt.show()

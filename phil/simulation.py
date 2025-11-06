import numpy as np
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt

# ---------- Parameters ----------
mu1_max = 1.2    # 1/h, max growth rate of acidogens
Ks1     = 7   # mg/L, half-saturation for S1
k1      = 40    # mg biomass / mg substrate

mu2_max = 0.75    # 1/h, max growth rate of methanogens
Ks2     = 9   # mg/L, half-saturation for S2
Ki2     = 250   # mg biomass / mg substrate
k2 = 120

# Stoichiometric coefficients
k3 = 270  # VFA produced per unit S1 consumed
k4 = 50  # CO2 per unit S1 consumed
k5 = 350  # CO2 per unit S2 consumed
k6 = 450  # CH4 per unit S2 consumed

# ---------- Kinetics ----------
def mu1(S1):
    return mu1_max * S1 / (Ks1 + S1)

def mu2(S2):
    return mu2_max * S2 / (Ks2 + S2 + ((S2**2)/Ki2))

# ---------- ODE system ----------
def digester(t, y):
    S1, X1, S2, X2 = y
    
    # Rates
    r1 = mu1(S1) * X1
    r2 = mu2(S2) * X2
    
    # Balances
    dS1 = -k1 * r1
    dX1 = r1
    dS2 = k3 * r1 - k2 * r2
    dX2 = r2
    # dP1 = k4 * r1 + k5 * r2
    # dP2 = k6 * r2
    
    return [dS1, dX1, dS2, dX2]
    # return [dS1, dX1, dS2, dX2, dP1, dP2]

# ---------- Initial conditions ----------
S1_0 = 1000.0  # mg/L organic matter
X1_0 = 10.0    # mg/L acidogenic biomass
S2_0 = 0.0     # mg/L VFA
X2_0 = 5.0     # mg/L methanogens
# P1_0 = 0.0     # CO2
# P2_0 = 0.0     # CH4

y0 = [S1_0, X1_0, S2_0, X2_0]
# y0 = [S1_0, X1_0, S2_0, X2_0, P1_0, P2_0]

# ---------- Time span ----------
t_span = (0, 200)       # hours
t_eval = np.linspace(*t_span, 500)

# ---------- Solve ----------
sol = solve_ivp(digester, t_span, y0, t_eval=t_eval, method='RK45')

# ---------- Plot ----------
labels = ["S1 (Organic)", "X1 (Acidogens)", "S2 (VFAs)", 
          "X2 (Methanogens)"]
        #   "X2 (Methanogens)", "P1 (CO2)", "P2 (CH4)"]

plt.figure(figsize=(10,6))
for i in range(len(labels)):
    plt.plot(sol.t, sol.y[i], label=labels[i])

plt.xlabel("Time (h)")
plt.ylabel("Concentration (mg/L or arbitrary units)")
plt.title("Batch Anaerobic Digestion Simulation")
plt.legend()
plt.grid()
plt.show()


# After solving with solve_ivp

plt.figure(figsize=(12,5))

# Phase plane 1: S1 vs X1
plt.subplot(1,2,1)
plt.plot(sol.y[0], sol.y[1], '-b')
plt.xlabel("S1 (Organic matter)")
plt.ylabel("X1 (Acidogens)")
plt.title("Phase Plane: S1 vs X1")
plt.grid()

# Phase plane 2: S2 vs X2
plt.subplot(1,2,2)
plt.plot(sol.y[2], sol.y[3], '-r')
plt.xlabel("S2 (VFAs)")
plt.ylabel("X2 (Methanogens)")
plt.title("Phase Plane: S2 vs X2")
plt.grid()

plt.tight_layout()
plt.show()


# Phase plane plots for X1 vs X2 and S1 vs S2
plt.figure(figsize=(12,5))

# Phase plane 1: X1 vs X2
plt.subplot(1,2,1)
plt.plot(sol.y[1], sol.y[3], '-g')
plt.xlabel("X1 (Acidogens)")
plt.ylabel("X2 (Methanogens)")
plt.title("Phase Plane: X1 vs X2")
plt.grid()

# Phase plane 2: S1 vs S2
plt.subplot(1,2,2)
plt.plot(sol.y[0], sol.y[2], '-m')
plt.xlabel("S1 (Organic matter)")
plt.ylabel("S2 (VFAs)")
plt.title("Phase Plane: S1 vs S2")
plt.grid()

plt.tight_layout()
plt.show()

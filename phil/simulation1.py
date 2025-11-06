import numpy as np
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt

# ---------- Parameters ----------
mu1_max = 1.2    # 1/h, max growth rate of acidogens
Ks1     = 7   # mg/L, half-saturation for S1
k1      = 1/40    # mg biomass / mg substrate
# k1      = 40    # mg biomass / mg substrate

mu2_max = 0.75    # 1/h, max growth rate of methanogens
Ks2     = 9   # mg/L, half-saturation for S2
Ki2     = 250   # mg biomass / mg substrate
k2 = 1/120
# k2 = 120

# Stoichiometric coefficients
k3 = 1/270  # VFA produced per unit S1 consumed
k4 = 1/50  # CO2 per unit S1 consumed
k5 = 1/350  # CO2 per unit S2 consumed
k6 = 1/450  # CH4 per unit S2 consumed

# k3 = 270  # VFA produced per unit S1 consumed
# k4 = 50  # CO2 per unit S1 consumed
# k5 = 350  # CO2 per unit S2 consumed
# k6 = 450  # CH4 per unit S2 consumed

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
S1_0 = 5.0  # mg/L organic matter
X1_0 = 10.0    # mg/L acidogenic biomass
S2_0 = 0.0     # mg/L VFA
X2_0 = 10.0     # mg/L methanogens
# P1_0 = 0.0     # CO2
# P2_0 = 0.0     # CH4

y0 = [S1_0, X1_0, S2_0, X2_0]
# y0 = [S1_0, X1_0, S2_0, X2_0, P1_0, P2_0]

# ---------- Time span ----------
# t_span = (150, 300)       # hours
t_span = (0, 200)       # hours
t_eval = np.linspace(*t_span, 500)

# ---------- Solve ----------
sol = solve_ivp(digester, t_span, y0, t_eval=t_eval, method='RK45')

# ---------- Plot ----------
labels = ["S1 (Organic)", "X1 (Acidogens)", "S2 (VFAs)", 
          "X2 (Methanogens)"]
        #   "X2 (Methanogens)", "P1 (CO2)", "P2 (CH4)"]

# ---------- Plot all ----------
fig, axs = plt.subplots(2, 2, figsize=(12,10))


# --- Substrates Time Series (S1, S2) ---
axs[0,0].plot(sol.t, sol.y[0], label='S1 (Organic)', color='blue')
axs[0,0].plot(sol.t, sol.y[2], label='S2 (VFAs)', color='orange')
axs[0,0].set_title("Substrates Time Series")
axs[0,0].set_xlabel("Time (h)")
axs[0,0].set_ylabel("Concentration")
axs[0,0].legend()
axs[0,0].grid()

# --- Biomass Time Series (X1, X2) ---
axs[0,1].plot(sol.t, sol.y[1], label='X1 (Acidogens)', color='green')
axs[0,1].plot(sol.t, sol.y[3], label='X2 (Methanogens)', color='red')
axs[0,1].set_title("Biomass Time Series")
axs[0,1].set_xlabel("Time (h)")
axs[0,1].set_ylabel("Biomass Concentration")
axs[0,1].legend()
axs[0,1].grid()


# # Time series
# axs[0,0].plot(sol.t, sol.y[0], label="S1 (Organic)")
# axs[0,0].plot(sol.t, sol.y[2], label="S2 (VFAs)")
# axs[0,0].plot(sol.t, sol.y[1], label="X1 (Acidogens)")
# axs[0,0].plot(sol.t, sol.y[3], label="X2 (Methanogens)")
# # axs[0,0].plot(sol.t, sol.y[4], label="P1 (CO2)")
# # axs[0,0].plot(sol.t, sol.y[5], label="P2 (CH4)")
# axs[0,0].set_title("Time Series")
# axs[0,0].set_xlabel("Time (h)")
# axs[0,0].set_ylabel("Concentration")
# axs[0,0].legend()
# axs[0,0].grid()

# Phase plane: X1 vs X2 with coordinate axes
axs[1,0].plot(sol.y[1], sol.y[3], '-g')
axs[1,0].axhline(0, color='black', linewidth=1)   # x-axis
axs[1,0].axvline(0, color='black', linewidth=1)   # y-axis
axs[1,0].set_xlabel("X1 (Acidogens)")
axs[1,0].set_ylabel("X2 (Methanogens)")
axs[1,0].set_title("Phase Plane: X1 vs X2")
axs[1,0].grid()

# Phase plane: S1 vs S2 with coordinate axes
axs[1,1].plot(sol.y[2], sol.y[0], '-m')
# axs[1,1].plot(sol.y[0], sol.y[2], '-m')
axs[1,1].axhline(0, color='black', linewidth=1)   # x-axis
axs[1,1].axvline(0, color='black', linewidth=1)   # y-axis
axs[1,1].set_ylabel("S1 (Organic matter)")
axs[1,1].set_xlabel("S2 (VFAs)")
axs[1,1].set_title("Phase Plane: S1 vs S2")
axs[1,1].grid()

# # Gas production
# axs[1,1].plot(sol.t, sol.y[4], label="P1 (CO2)")
# axs[1,1].plot(sol.t, sol.y[5], label="P2 (CH4)")
# axs[1,1].set_xlabel("Time (h)")
# axs[1,1].set_ylabel("Gas produced")
# axs[1,1].set_title("Gas Production")
# axs[1,1].legend()
# axs[1,1].grid()

plt.tight_layout()
plt.show()
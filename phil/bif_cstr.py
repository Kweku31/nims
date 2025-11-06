import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import fsolve
from numpy.linalg import eig

# ---------- PARAMETERS ----------
mu1_max = 1.2    # h^-1
Ks1     = 7.0
mu2_max = 0.75    # h^-1
Ks2     = 9.0
Ki2      = 250.0
# Yields
K1 = 1/40   # gX/gS
K2 = 1/120  # gX/gS
K3 = 1/270  # VFA produced per unit S1 consumed
K4 = 1/50  # CO2 per unit S1 consumed
K5 = 1/350  # CO2 per unit S2 consumed
K6 = 1/450  # CH4 per unit S2 consumed


# ---------- KINETICS ----------
def mu1(S1):
    return mu1_max * S1 / (Ks1 + S1)

def mu2(S2):
    return mu2_max * S2 / (Ks2 + S2 + (S2**2)/Ki2)

# ---------- ODE SYSTEM ----------
def rhs(t, y, params):
    X1, X2, S1, S2 = y
    D, S1_in, S2_in = params["D"], params["S1_in"], params["S2_in"]
    r1 = mu1(S1) * X1
    r2 = mu2(S2) * X2
    dX1 = (mu1(S1) - D) * X1
    dX2 = (mu2(S2) - D) * X2
    dS1 = D*(S1_in - S1) - K1*r1
    dS2 = D*(S2_in - S2) + K3*r1 - K2*r2
    return [dX1, dX2, dS1, dS2]


def find_equilibria(params, guesses=None):
    if guesses is None:
        guesses = [
            [1, 1, params["S1_in"], params["S2_in"]],   # near inflow values
            [10, 5, 20, 10],                          # biomass present
            [0, 0, params["S1_in"], params["S2_in"]]   # washout
        ]
    
    equilibria = []
    for g in guesses:
        sol, infodict, ier, msg = fsolve(lambda y: rhs(0,y,params), g, full_output=True)
        if ier == 1 and np.all(sol >= -1e-6):
            equilibria.append(sol)
    return equilibria

# ---------- NUMERICAL JACOBIAN ----------
def jacobian(eq, params):
    f0 = np.array(rhs(0, eq, params))
    J = np.zeros((4,4))
    h = 1e-6
    for i in range(4):
        y = np.array(eq)
        y[i] += h
        fi = np.array(rhs(0, y, params))
        J[:,i] = (fi - f0)/h
    return J

# ---------- BIFURCATION PLOT ----------
def plot_bifurcation_sequence(param_name, param_values, fixed_params, plane="X"):
    """Plot phase portraits across a bifurcation parameter sequence"""
    
    n = len(param_values)
    fig, axes = plt.subplots(1, n, figsize=(5*n, 5))
    
    if n == 1:
        axes = [axes]
    
    for i, param_val in enumerate(param_values):
        params = fixed_params.copy()
        params[param_name] = param_val
        
        # Choose plane to project
        if plane == "X":
            idx1, idx2 = 0, 1   # X1 vs X2
            label1, label2 = "X1 (acidogens)", "X2 (methanogens)"
            xrange, yrange = [0, 50], [0, 50]
        else:
            idx1, idx2 = 2, 3   # S1 vs S2
            label1, label2 = "S1 (substrate)", "S2 (VFAs)"
            xrange, yrange = [0, params["S1_in"]*1.2], [0, 200]
        
        x1 = np.linspace(xrange[0], xrange[1], 20)
        x2 = np.linspace(yrange[0], yrange[1], 20)
        X1, X2 = np.meshgrid(x1, x2)
        U, V = np.zeros(X1.shape), np.zeros(X2.shape)
        
        # Fix the other states at inflow values for projection
        for i1 in range(len(x1)):
            for j in range(len(x2)):
                y = [0,0,params["S1_in"],params["S2_in"]]
                y[idx1] = X1[i1,j]
                y[idx2] = X2[i1,j]
                derivatives = rhs(0, y, params)
                U[i1,j] = derivatives[idx1]
                V[i1,j] = derivatives[idx2]
        
        axes[i].streamplot(X1, X2, U, V, density=1.2, color='gray', linewidth=1)
        
        # Plot equilibria
        eq_points = find_equilibria(params)
        for eq in eq_points:
            J = jacobian(eq, params)
            eigenvalues = eig(J)[0]
            real_parts = eigenvalues.real
            if all(real_parts < 0):
                axes[i].plot(eq[idx1], eq[idx2], 'go', markersize=10)
            else:
                axes[i].plot(eq[idx1], eq[idx2], 'ro', markersize=10)
        
        axes[i].set_xlabel(label1)
        axes[i].set_ylabel(label2)
        axes[i].set_title(f"{param_name}={param_val:.2f}")
        axes[i].set_xlim(xrange)
        axes[i].set_ylim(yrange)
        axes[i].grid(True)
    
    plt.tight_layout()
    plt.show()

# ---------- Example ----------
fixed_params = {"D": 0.1, "S1_in": 10, "S2_in": 0}
D_values = [0.05, 0.1, 0.2, 0.5]
plot_bifurcation_sequence("D", D_values, fixed_params, plane="X")

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import fsolve
from numpy.linalg import eig

# ---------- PARAMETERS ----------
D   = 0.1
# K1, K2, K3 = 0.5, 0.4, 0.3
K1 = 1/40   # gX/gS
K2 = 1/120  # gX/gS
K3 = 1/270  # VFA produced per unit S1 consumed
K4 = 1/50  # CO2 per unit S1 consumed
K5 = 1/350  # CO2 per unit S2 consumed
K6 = 1/450  # CH4 per unit S2 consumed

S1_in, S2_in = 5, 0

def mu1(S1):
    mu1_max, Ks1 = 1.2, 7
    return mu1_max * S1 / (Ks1 + S1)

def mu1_prime(S1):
    mu1_max, Ks1 = 1.2, 7
    return mu1_max * Ks1 / (Ks1 + S1)**2

def mu2(S2):
    mu2_max, Ks2, Ki = 0.75, 9, 250   # Haldane
    return mu2_max * S2 / (Ks2 + S2 + (S2**2 / Ki))

def mu2_prime(S2):
    mu2_max, Ks2, Ki = 0.75, 9, 250
    return mu2_max * (Ks2*Ki - S2**2) / (Ki * (Ks2 + S2 + (S2**2 / Ki))**2)

# ---------- MODEL ----------
def rhs(t, y, params=None):
    X1, X2, S1, S2 = y
    dX1 = (mu1(S1) - D) * X1
    dX2 = (mu2(S2) - D) * X2
    dS1 = D*(S1_in - S1) - K1*mu1(S1)*X1
    dS2 = D*(S2_in - S2) + K3*mu1(S1)*X1 - K2*mu2(S2)*X2
    return [dX1, dX2, dS1, dS2]

# ---------- JACOBIAN ----------
def jacobian(X1, X2, S1, S2):
    J = np.zeros((4,4))
    # dX1/d*
    J[0,0] = mu1(S1) - D
    J[0,2] = mu1_prime(S1) * X1
    # dX2/d*
    J[1,1] = mu2(S2) - D
    J[1,3] = mu2_prime(S2) * X2
    # dS1/d*
    J[2,0] = -K1*mu1(S1)
    J[2,2] = -D - K1*mu1_prime(S1)*X1
    # dS2/d*
    J[3,0] = K3*mu1(S1)
    J[3,1] = -K2*mu2(S2)
    J[3,2] = K3*mu1_prime(S1)*X1
    J[3,3] = -D - K2*mu2_prime(S2)*X2
    return J

# ---------- FIND EQUILIBRIA ----------
def find_equilibria(guesses=None):
    if guesses is None:
        guesses = [
            [0, 0, S1_in, S2_in],   # washout
            [5, 0, 10, 10],       # X1 only
            [5, 5, 10, 10]        # coexistence
        ]
    
    equilibria = []
    for g in guesses:
        sol, infodict, ier, msg = fsolve(lambda y: rhs(0,y), g, full_output=True)
        if ier == 1 and np.all(sol >= -1e-6):
            equilibria.append(sol)
    return equilibria

# # ---------- PLOT PHASE PLANE ----------
# def plot_phase_plane():
#     eqs = find_equilibria()
    
#     # choose X1-X2 projection
#     x1 = np.linspace(0, 15, 20)
#     x2 = np.linspace(0, 15, 20)
#     X1, X2 = np.meshgrid(x1, x2)
#     U, V = np.zeros(X1.shape), np.zeros(X2.shape)
    
#     # vector field (approx)
#     for i in range(len(x1)):
#         for j in range(len(x2)):
#             d = rhs(0, [X1[i,j], X2[i,j], 500, 50])  # fix S1,S2 slice
#             U[i,j] = d[0]
#             V[i,j] = d[1]
    
#     plt.figure(figsize=(7,6))
#     plt.streamplot(X1, X2, U, V, density=1.2, color="gray", linewidth=1)

#     # plot equilibria with eigenvalues
#     for eq in eqs:
#         J = jacobian(*eq)
#         eigvals = eig(J)[0]
#         if np.all(np.real(eigvals) < 0):
#             color = "green"
#         else:
#             color = "red"
#         plt.plot(eq[0], eq[1], 'o', color=color, markersize=10)
#         plt.text(eq[0]+0.3, eq[1]+0.3,
#                  "\n".join([f"{lam.real:.2f}{lam.imag:+.2f}i" for lam in eigvals]),
#                  fontsize=8)
    
#     plt.xlabel("X1 (biomass 1)")
#     plt.ylabel("X2 (biomass 2)")
#     plt.title("Phase Plane (X1 vs X2)")
#     plt.grid(True)
#     plt.show()

# # ---------- RUN ----------
# plot_phase_plane()


def plot_all_phase_planes(eqs, span=20):
    """Plot multiple 2D phase planes from the 4D system"""
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    planes = [
        ("X1", "X2", 0, 1),
        ("X1", "S1", 0, 2),
        ("X2", "S2", 1, 3),
        ("S1", "S2", 2, 3),
    ]
    
    for ax, (label_x, label_y, ix, iy) in zip(axes.flat, planes):
        
        # choose equilibrium as center
        center_eq = eqs[-1] if eqs else [1,1,500,50]
        x_center, y_center = center_eq[ix], center_eq[iy]
        
        # define ranges
        x_vals = np.linspace(max(0, x_center - span/2), x_center + span/2, 20)
        y_vals = np.linspace(max(0, y_center - span/2), y_center + span/2, 20)
        X, Y = np.meshgrid(x_vals, y_vals)
        U, V = np.zeros(X.shape), np.zeros(Y.shape)
        
        for i in range(len(x_vals)):
            for j in range(len(y_vals)):
                state = [center_eq[0], center_eq[1], center_eq[2], center_eq[3]]
                state[ix] = X[i,j]
                state[iy] = Y[i,j]
                d = rhs(0, state)   # system dynamics
                U[i,j] = d[ix]
                V[i,j] = d[iy]
        
        # plot streamlines
        ax.streamplot(X, Y, U, V, density=1.2, color="gray", linewidth=1)
        
        # mark equilibria
        for eq in eqs:
            J = jacobian(*eq)
            eigvals = eig(J)[0]
            if np.all(np.real(eigvals) < 0):
                color = "green"
            else:
                color = "red"
            ax.plot(eq[ix], eq[iy], 'o', color=color, markersize=10)
        
        ax.set_xlabel(label_x)
        ax.set_ylabel(label_y)
        ax.set_title(f"Phase Plane: {label_x} vs {label_y}")
        ax.grid(True)
    
    plt.tight_layout()
    plt.show()

# Example usage
eqs = find_equilibria()
plot_all_phase_planes(eqs)

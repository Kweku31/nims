import numpy as np
import matplotlib.pyplot as plt
from scipy.integrate import solve_ivp
from scipy.optimize import fsolve

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

D = 0.1
S1_in = 1.0
S2_in = 0.0

# ---------- KINETIC FUNCTIONS ----------
def mu1(S1):
    return mu1_max * S1 / (Ks1 + S1)

def mu1_prime(S1):
    return mu1_max * Ks1 / (Ks1 + S1)**2

def mu2(S2):
    return mu2_max * S2 / (Ks2 + S2 + (S2**2)/Ki2)

def mu2_prime(S2):
    num = mu2_max * (Ks2 + S2 + (S2**2)/Ki2) - mu2_max*S2*(1 + 2*S2/Ki2)
    den = (Ks2 + S2 + (S2**2)/Ki2)**2
    return num/den

# ---------- ODE SYSTEM ----------
def rhs(t, y):
    X1, X2, S1, S2 = y
    r1 = mu1(S1) * X1
    r2 = mu2(S2) * X2
    dX1 = (mu1(S1) - D) * X1
    dX2 = (mu2(S2) - D) * X2
    dS1 = D*(S1_in - S1) - K1*r1
    dS2 = D*(S2_in - S2) + K3*r1 - K2*r2
    return [dX1, dX2, dS1, dS2]

# ---------- EQUILIBRIUM SOLVER ----------
def find_equilibrium(guess):
    sol, info, ier, _ = fsolve(lambda y: rhs(0,y), guess, full_output=True)
    if ier == 1: 
        return sol
    else:
        return None

guesses = [[5,5,10,0], [10,5,20,5], [50,30,10,10]]
equilibria = []
for g in guesses:
    sol = find_equilibrium(g)
    if sol is not None and np.all(sol >= -1e-6):  # keep positive equilibria
        equilibria.append(sol)

# # ---------- JACOBIAN ----------
# def jacobian(X1, X2, S1, S2):
#     J = np.zeros((4,4))
#     # dX1/d*
#     J[0,0] = mu1(S1) - D
#     J[0,2] = mu1_prime(S1) * X1
#     # dX2/d*
#     J[1,1] = mu2(S2) - D
#     J[1,3] = mu2_prime(S2) * X2
#     # dS1/d*
#     J[2,0] = -K1*mu1(S1)
#     J[2,2] = -D - K1*mu1_prime(S1)*X1
#     # dS2/d*
#     J[3,0] = K3*mu1(S1)
#     J[3,1] = -K2*mu2(S2)
#     J[3,2] = K3*mu1_prime(S1)*X1
#     J[3,3] = -D - K2*mu2_prime(S2)*X2
#     return J

# J = jacobian(X1_eq, X2_eq, S1_eq, S2_eq)
# eigvals = np.linalg.eigvals(J)
# print("Jacobian eigenvalues:", eigvals)

# ---------- JACOBIAN ----------
def jacobian(X1, X2, S1, S2):
    # numerical approx
    f0 = np.array(rhs(0, [X1,X2,S1,S2]))
    J = np.zeros((4,4))
    h = 1e-6
    for i in range(4):
        y = [X1,X2,S1,S2]
        y[i] += h
        fi = np.array(rhs(0,y))
        J[:,i] = (fi - f0)/h
    return J

# ---------- SIMULATION ----------
t_span = (0, 200)
y0 = [15.0, 8.0, 50.0, 20.0]  # ICs near equilibrium
sol = solve_ivp(rhs, t_span, y0, t_eval=np.linspace(*t_span, 1000))

# ---------- PHASE PORTRAIT ----------
x1 = np.linspace(0, 40, 30)
x2 = np.linspace(0, 40, 30)
X1g, X2g = np.meshgrid(x1, x2)

# keep S1,S2 fixed at inflow values (projection for visualization)
S1_fixed, S2_fixed = S1_in, S2_in
dX1g = (mu1(S1_fixed)-D)*X1g
dX2g = (mu2(S2_fixed)-D)*X2g

plt.figure(figsize=(8,6))
plt.streamplot(X1g, X2g, dX1g, dX2g, density=1.2, linewidth=1, arrowsize=1)

# mark equilibria
for eq in equilibria:
    X1_eq, X2_eq, S1_eq, S2_eq = eq
    J = jacobian(*eq)
    eigvals = np.linalg.eigvals(J)
    
    if np.all(np.real(eigvals) < 0):
        color = "green"  # stable
    elif np.any(np.real(eigvals) > 0):
        color = "red"    # unstable
    else:
        color = "orange" # marginal
    
    plt.plot(X1_eq, X2_eq, 'o', color=color, markersize=10)
    text = "\n".join([f"{ev:.2f}" for ev in eigvals])
    plt.text(X1_eq+0.5, X2_eq+0.5, text, fontsize=8,
             bbox=dict(facecolor='white', alpha=0.7))

plt.xlabel("X1 (acidogens)")
plt.ylabel("X2 (methanogens)")
plt.title("Phase Portrait with Equilibria and Eigenvalues")
plt.grid()
plt.show()
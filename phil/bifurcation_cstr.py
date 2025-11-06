import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import fsolve
import matplotlib.pyplot as plt

# System definition
def cstr(t, y, params):
    X1, X2, S1, S2 = y
    mu1 = params["mu1_max"] * S1 / (params["Ks1"] + S1)
    mu2 = params["mu2_max"] * S2 / (params["Ks2"] + S2)
    
    dX1 = (mu1 - params["D"]) * X1
    dX2 = (mu2 - params["D"]) * X2
    dS1 = params["D"]*(params["S1_in"]-S1) - (params["K1"])*mu1*X1
    dS2 = params["D"]*(params["S2_in"]-S2) - (params["K2"])*mu2*X2 + params["K3"]*X1
    
    return [dX1, dX2, dS1, dS2]

# Jacobian
def jacobian(y, params, eps=1e-6):
    n = len(y)
    J = np.zeros((n,n))
    f0 = np.array(cstr(0,y,params))
    for i in range(n):
        y_perturb = y.copy()
        y_perturb[i] += eps
        fi = np.array(cstr(0,y_perturb,params))
        J[:,i] = (fi - f0)/eps
    return J

# Parameters
params = {
    "mu1_max":1.2, "Ks1":7, "K1":0.4,
    "mu2_max":0.8, "Ks2":9, "K2":0.5,
    "K3":0.1, "D":0.2, "S1_in":10, "S2_in":5
}

# Equilibrium solver
def find_equilibria(params):
    guesses = [[0,0,params["S1_in"],params["S2_in"]],
               [1,1,5,2], [5,5,2,2], [10,2,8,4]]
    eqs = []
    for g in guesses:
        sol, info, ier, msg = fsolve(lambda y: cstr(0,y,params), g, full_output=True)
        if ier == 1:  # converged
            if all(sol >= -1e-6):  # discard negatives
                sol = np.round(sol,6)
                if not any(np.allclose(sol,e,atol=1e-4) for e in eqs):
                    eqs.append(sol)
    return eqs

equilibria = find_equilibria(params)
print("Equilibria found:", equilibria)

# Classify and plot
fig, axes = plt.subplots(2,2,figsize=(12,8))
pairs = [(0,1,"X1","X2"), (0,2,"X1","S1"), (1,3,"X2","S2"), (2,3,"S1","S2")]


for ax,(i,j,xi,xj) in zip(axes.flatten(),pairs):
    # Set ranges to include equilibria
    all_i = [eq[i] for eq in equilibria]
    all_j = [eq[j] for eq in equilibria]
    max_i = max(max(all_i)*1.2, 5)
    max_j = max(max(all_j)*1.2, 5)

    Yi = np.linspace(0, max_i, 20)
    Yj = np.linspace(0, max_j, 20)
    U,V = np.meshgrid(Yi,Yj)
    dU = np.zeros_like(U)
    dV = np.zeros_like(V)

    for m in range(U.shape[0]):
        for n in range(U.shape[1]):
            y0 = [0,0,0,0]
            y0[i], y0[j] = U[m,n], V[m,n]
            f = cstr(0,y0,params)
            dU[m,n], dV[m,n] = f[i], f[j]

    ax.streamplot(U,V,dU,dV,density=1)
    
    # Plot equilibria
    for eq in equilibria:
        eigs = np.linalg.eigvals(jacobian(eq,params))
        eigs_str = ", ".join([f"{ev.real:.2f}" for ev in eigs])
        if np.all(np.real(eigs)<0):
            ax.plot(eq[i],eq[j],'go',markersize=10,label="Stable")
            ax.text(eq[i], eq[j], f"Eq={eq[i]:.1f},{eq[j]:.1f}\nλ={eigs_str}",
                    fontsize=7, color="green")
        else:
            ax.plot(eq[i],eq[j],'ro',markersize=10,label="Unstable")
            ax.text(eq[i], eq[j], f"Eq={eq[i]:.1f},{eq[j]:.1f}\nλ={eigs_str}",
                    fontsize=7, color="red")

    ax.set_title(f"Phase Plane: {xi} vs {xj}")
    ax.set_xlabel(xi)
    ax.set_ylabel(xj)

plt.tight_layout()
plt.show()

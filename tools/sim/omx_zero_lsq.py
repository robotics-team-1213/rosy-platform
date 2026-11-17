"""Numpy-only nonlinear least squares for the zero tools: the remote test venv has no SciPy (D-584 hosts, 11-18),
so the fits and their tests ran nowhere while importorskip("scipy") skipped them. Levenberg-Marquardt with
Marquardt's diagonal scaling (what least_squares' x_scale="jac" buys) and SciPy's relative finite-difference step."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np


def rotvec_matrix(v):
    """Rotation matrix of rotation vector v (rad), Rodrigues."""
    v = np.asarray(v, float)
    th = float(np.linalg.norm(v))
    if th < 1e-15:
        return np.eye(3)
    k = v / th
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + np.sin(th) * kx + (1.0 - np.cos(th)) * kx @ kx


def jacobian(f, x, r, diff_step):
    # SciPy's relative step: h = diff_step * sign(x) * max(1, |x|), so x = 0 still moves
    h = diff_step * np.where(x >= 0, 1.0, -1.0) * np.maximum(1.0, np.abs(x))
    J = np.empty((len(r), len(x)))
    for i in range(len(x)):
        xi = x.copy()
        xi[i] += h[i]
        J[:, i] = (f(xi) - r) / h[i]
    return J


def least_squares(f, x0, diff_step=1e-2, xtol=1e-10, ftol=1e-10, max_iter=200, **_):
    x = np.asarray(x0, float).copy()
    r = f(x)
    cost = 0.5 * float(r @ r)
    lam, success, message = 1e-3, False, "iteration limit reached"
    J = jacobian(f, x, r, diff_step)
    for _ in range(max_iter):
        A, g = J.T @ J, J.T @ r
        D = np.maximum(np.diag(A), 1e-12)
        while True:
            dx = np.linalg.solve(A + lam * np.diag(D), -g)
            r_new = f(x + dx)
            cost_new = 0.5 * float(r_new @ r_new)
            if cost_new <= cost or lam > 1e12:
                break
            lam *= 4.0
        if cost_new > cost:
            success, message = True, "no step lowers the cost"
            break
        small_step = np.linalg.norm(dx) <= xtol * (xtol + np.linalg.norm(x))
        small_drop = cost - cost_new <= ftol * cost
        x, r, cost = x + dx, r_new, cost_new
        lam = max(lam / 3.0, 1e-12)
        J = jacobian(f, x, r, diff_step)
        if small_step or small_drop:
            success, message = True, "converged"
            break
    return SimpleNamespace(x=x, fun=r, jac=J, cost=cost, success=success, message=message)

"""Optimization solver utilities (e.g. SLSQP wrapper)."""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
from scipy.optimize import minimize


ObjectiveFunc = Callable[[np.ndarray], float]


def solve_slsqp(
    x0: np.ndarray,
    objective: ObjectiveFunc,
    bounds: Sequence[tuple[float | None, float | None]] | None = None,
    constraints: Sequence[dict] | None = None,
    maxiter: int = 1000,
    tol: float | None = None,
) -> tuple[np.ndarray, bool, str]:
    """Solve a constrained optimization problem using SLSQP.

    Returns (x_opt, success, message).
    """
    result = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints or (),
        options={"maxiter": maxiter},
        tol=tol,
    )
    x_opt = np.asarray(result.x, dtype=float)
    return x_opt, bool(result.success), str(result.message)

"""Shared numerics: a fixed-iteration bisection root-finder.

The electrochemical current solve and the bubble departure-radius solve both
invert a monotone balance with the same bracketed bisection. Factor it once so
every solver uses identical, deterministic numerics.
"""


def bisect(residual, lo, hi, n=80):
    """Root of `residual` on [lo, hi], assuming it increases through the bracket
    (residual(lo) <= 0 <= residual(hi)).

    Fixed iteration count (no early exit) keeps results bit-for-bit reproducible
    regardless of the bracket. Returns the final midpoint — identical to the
    in-line loops this replaces.
    """
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if residual(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)

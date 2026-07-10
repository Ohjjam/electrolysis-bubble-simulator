"""Back-compat shim. Detachment physics moved to `bubblesim.kernel.bubbles.forces`."""
from .kernel.bubbles.forces import fritz_radius, departure_radius  # noqa: F401

__all__ = ["fritz_radius", "departure_radius"]

"""Back-compat shim. `Surface` now lives in `bubblesim.kernel.bubbles.population`."""
from .kernel.bubbles.population import Surface  # noqa: F401

__all__ = ["Surface"]

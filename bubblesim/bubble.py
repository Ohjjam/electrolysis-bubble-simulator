"""Back-compat shim. `Bubble` now lives in `bubblesim.kernel.bubbles.bubble`."""
from .kernel.bubbles.bubble import Bubble  # noqa: F401

__all__ = ["Bubble"]

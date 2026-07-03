"""Camera Module 3 capture and remote multimodal-analysis support.

The package deliberately keeps semantic plant analysis out of the Raspberry Pi:
local code handles capture, deterministic quality checks, scheduling and storage;
an injected multimodal client performs plant interpretation remotely.
"""

# Keep package import side-effect free. Cloud dashboard deployments only need
# ``vision.store`` and ``vision.schemas`` and intentionally do not install the
# Raspberry Pi camera stack. Callers import concrete submodules directly.
__all__ = []

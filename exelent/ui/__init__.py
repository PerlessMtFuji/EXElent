"""GUI layer. The only place in the project that imports Qt.

The core (analysis -> environment -> build -> diagnostics) knows nothing about
the window; `tests/test_layering.py` enforces this. The same logic therefore
works from the CLI and can be tested without a display.
"""

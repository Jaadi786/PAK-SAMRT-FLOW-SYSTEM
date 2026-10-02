"""Streamlit Community Cloud entrypoint.

Community Cloud's deploy form defaults its **Main file path** to
``streamlit_app.py``. This file exists so that a zero-configuration deploy works
out of the box, while the real application stays in ``app_streamlit.py`` where
the README and the demo script point.

If you prefer, skip this file entirely and set the main file path to
``app_streamlit.py`` in the deploy form. Both routes run identical code.

Why ``runpy`` rather than ``import``: Streamlit executes the main script with
``__name__ == "__main__"``. Importing ``app_streamlit`` as a module would also
work, but ``runpy`` reproduces the exact execution semantics Streamlit uses, so
the two entrypoints cannot drift apart.
"""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent / "app_streamlit.py"),
    run_name="__main__",
)

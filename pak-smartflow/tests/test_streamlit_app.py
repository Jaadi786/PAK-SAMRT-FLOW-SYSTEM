"""Headless smoke tests for the Streamlit dashboard.

Why this file exists
--------------------
The development environment for this project had no Streamlit installed, so the
dashboard could not be executed locally at all. Rather than ship an unverified
UI, it is verified in CI: ``.github/workflows/tests.yml`` installs
``requirements.txt`` and runs exactly these tests.

``streamlit.testing.v1.AppTest`` executes the real script through the real
runtime in-process, so an ``ImportError``, a bad API call or a crash on the
first render fails the build instead of failing on stage.

Skipped (not failed) when Streamlit is absent, so the core suite still runs on a
bare interpreter:

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app_streamlit.py"
SHIM = ROOT / "streamlit_app.py"
TMP = Path(__file__).resolve().parent / "_tmp_store"

try:  # pragma: no cover - exercised only when the extras are installed
    from streamlit.testing.v1 import AppTest

    HAVE_STREAMLIT = True
except Exception:  # noqa: BLE001
    AppTest = None  # type: ignore[assignment]
    HAVE_STREAMLIT = False


def _cleanup() -> None:
    for path in sorted(TMP.rglob("*"), reverse=True):
        try:
            path.unlink() if path.is_file() else path.rmdir()
        except OSError:
            pass
    try:
        TMP.rmdir()
    except OSError:
        pass


@unittest.skipUnless(HAVE_STREAMLIT, "streamlit is not installed (pip install -r requirements.txt)")
class AppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TMP.mkdir(parents=True, exist_ok=True)
        os.environ["SMARTFLOW_DB"] = str(TMP / "app.sqlite")

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.pop("SMARTFLOW_DB", None)
        _cleanup()

    def _fresh(self) -> "AppTest":
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        return app

    def test_main_app_renders_without_exception(self) -> None:
        app = self._fresh()
        self.assertFalse(list(app.exception), f"app raised on first render: {app.exception}")
        self.assertTrue(len(app.title) >= 1)
        self.assertEqual(app.title[0].value, "🚦 Pak-SmartFlow")

    def test_cloud_entrypoint_shim_renders(self) -> None:
        """Community Cloud defaults its main file path to ``streamlit_app.py``.

        That shim delegates through ``runpy``; if the delegation is wrong the
        hosted app is a blank error page, so it gets its own test.
        """
        app = AppTest.from_file(str(SHIM), default_timeout=120)
        app.run()
        self.assertFalse(list(app.exception), f"shim raised: {app.exception}")
        self.assertEqual(app.title[0].value, "🚦 Pak-SmartFlow")

    def test_all_seven_tabs_are_present(self) -> None:
        app = self._fresh()
        self.assertFalse(list(app.exception))
        self.assertEqual(len(app.tabs), 7)

    def test_running_a_scenario_produces_a_decision(self) -> None:
        """Click the sidebar's first button and assert the render survives it."""
        app = self._fresh()
        self.assertTrue(app.sidebar.button, "sidebar has no buttons")
        app.sidebar.button[0].click().run()
        self.assertFalse(
            list(app.exception), f"scenario run raised: {app.exception}"
        )
        self.assertTrue(app.metric, "no metrics rendered after a scenario run")

    def test_running_every_scenario_does_not_crash(self) -> None:
        app = self._fresh()
        app.sidebar.button[1].click().run()
        self.assertFalse(
            list(app.exception), f"batch run raised: {app.exception}"
        )
        self.assertTrue(app.metric)

    def test_legal_boundary_tab_content_is_reachable(self) -> None:
        """The legal table is rendered from data in ``smartflow.legal``; if that
        mapping ever loses a key the tab raises, which is a legal-risk surface,
        so it is asserted explicitly."""
        app = self._fresh()
        self.assertFalse(list(app.exception))
        rendered = " ".join(
            str(element.value) for element in app.dataframe if hasattr(element, "value")
        )
        self.assertTrue(rendered, "no dataframe rendered on the legal tab path")


if __name__ == "__main__":
    unittest.main()

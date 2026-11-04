"""`from vidgrab.app import main` is the documented way to start the window from a script
(README); the window itself lives in `vidgrab/ui/app.py`."""
from __future__ import annotations


def main() -> None:
    from vidgrab.ui.app import main as run

    run()

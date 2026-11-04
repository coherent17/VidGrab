"""Keep the tests away from a yt-dlp the person running them downloaded."""

import os
import tempfile

os.environ.setdefault("VIDGRAB_YTDLP_DIR", tempfile.mkdtemp(prefix="vidgrab-ytdlp-test-"))


def patch_ui(monkeypatch, name: str, value) -> None:
    """Patch *name* in every `vidgrab.ui` module that has it. The window's code is spread over
    several modules (`app`, `workers`, `settings_page`, ...), each with its own reference to a
    name such as `_config_dir` or `find_ffmpeg`; patching only one of them would miss the rest."""
    import sys

    hit = False
    for mod_name, mod in list(sys.modules.items()):
        if (mod_name == "vidgrab.ui" or mod_name.startswith("vidgrab.ui.")) and mod is not None and hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)
            hit = True
    assert hit, f"no vidgrab.ui module has {name}"

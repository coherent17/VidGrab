"""Keep the tests away from a yt-dlp the person running them downloaded."""

import os
import tempfile

os.environ.setdefault("VIDGRAB_YTDLP_DIR", tempfile.mkdtemp(prefix="vidgrab-ytdlp-test-"))

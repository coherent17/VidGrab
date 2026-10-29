# ffmpeg / ffprobe are embedded into the single-file executable by VidGrab.spec
# and are NOT committed to git (see .gitignore).

# Every build, CI job and developer machine uses the one version pinned in
# ffmpeg/pin.json (a BtbN month-end build, SHA-256 checked):
#
#   make ffmpeg                          # Linux: -> ffmpeg/linux/
#   python scripts/fetch_ffmpeg.py win   # Windows: -> ffmpeg/win/
#
# In development the app prefers ffmpeg/<platform>/ over a system ffmpeg, and
# `make run` / `make test` put ffmpeg/linux first on PATH.
#
# To upgrade, edit ffmpeg/pin.json (see its "comment") and let CI render-test it.

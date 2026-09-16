# Place ffmpeg binaries in the platform folders below before building.
# They are embedded into the single-file executable by VidGrab.spec and are
# NOT committed to git (see .gitignore).

# --- Windows (Windows builds) -------------------------------------------
# Download the gyan "essentials" build:
#   https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
# Extract and copy into ffmpeg/win/:
#   bin/ffmpeg.exe  -> ffmpeg/win/ffmpeg.exe
#   bin/ffprobe.exe -> ffmpeg/win/ffprobe.exe

# --- Linux (Linux builds) ----------------------------------------------
# Download John Van Sickle's static build (x86_64):
#   https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
# Extract and copy into ffmpeg/linux/:
#   ./ffmpeg  -> ffmpeg/linux/ffmpeg
#   ./ffprobe -> ffmpeg/linux/ffprobe

# The GitHub Actions workflows download these automatically at build time.
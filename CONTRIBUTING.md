# Contributing

Thanks for helping. This page is for people who build or change VidGrab; to just use it, see the [README](README.md).

## Building from source

Requires Python 3.10+.

```bash
make setup    # create .venv and install dependencies (one-time)
make ffmpeg   # download the pinned ffmpeg 9.0.2 into ffmpeg/linux (one-time)
make run      # launch the app
make lint     # ruff
make test     # pytest, including a headless GUI smoke test
make build    # standalone binary for the current OS -> dist/
```

On macOS, `make ffmpeg` is not needed: the app downloads ffmpeg itself (or use `brew install ffmpeg`).
To build the package: `python -m build`; the macOS app: `pyinstaller VidGrab.spec` (see `.github/workflows/build-macos.yml`).

On Windows, use `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt` and
`python -m vidgrab`, or build with `scripts\build.ps1` (which fetches the pinned ffmpeg itself).

Every build, CI job and development setup uses the one ffmpeg version pinned in `ffmpeg/pin.json`
(SHA-256 checked); see `ffmpeg/README.txt` to upgrade it.

> Missing Qt libraries on Linux? `sudo apt install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libxcb-cursor0 libxcb-xinerama0 libdbus-1-3`

See `CLAUDE.md` for how the code is organised.

### CI and releases

Every push and pull request is linted and tested on Linux, Windows and macOS, and the Windows and Linux binaries are built beside the tests (changes to `*.md` / `docs/` only skip CI). The release workflow builds only after the tests pass, builds the macOS apps too, and makes the Linux `.tar.xz`. Each
build also renders real Studio projects with the exact ffmpeg it bundles, and checks that the speech engines load and
run inside the packaged binary.

To release, bump `vidgrab/_version.py`, add a `## <version>` section to `CHANGELOG.md`, and push a matching tag
(`git tag vX.Y.Z && git push origin vX.Y.Z`). The release workflow checks the tag against the version, builds both
platforms and publishes the executables, the demo video, the user guide and `SHA256SUMS.txt`, with notes taken from
the changelog.


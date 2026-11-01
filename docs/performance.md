# Speed and downloads

Numbers behind the claims in the README. The settings that matter are **Settings → Hardware** (two switches, on by default; the app falls back to the CPU whenever a card can't do the job).

## Speech model sizes (downloaded once, on first use)

| Accuracy | Download on an Intel GPU | Download on an NVIDIA GPU or the CPU |
|---|---|---|
| Fast | 85 MB | 150 MB |
| Balanced | 260 MB | 490 MB |
| Best | 830 MB | 1.6 GB |


An NVIDIA card also needs NVIDIA's CUDA libraries (a 1.3 GB download, 2 GB on disk), which VidGrab fetches once from NVIDIA's official packages if they aren't installed.

## Measured speed

Two switches in **Settings → Hardware** (on by default, with an automatic fall back to the CPU whenever a card can't do
the job). Measured on a laptop with a Core Ultra 9 285H and its integrated Intel Arc 140T GPU:

**Auto captions**, one minute of Mandarin speech:

| Accuracy | Before | CPU, tuned | Intel GPU |
|---|---:|---:|---:|
| Fast | 18.1 s | 3.7 s | 2.6 s |
| Balanced | 35.4 s | 8.9 s | 4.9 s |
| **Best** | 27.1 s | 19.0 s | **5.1 s** |

The GPU runs the most accurate model faster than the middle one on the CPU, so a one-hour video takes about five minutes
at *Best*. Even without a graphics card, captions are 5–7× faster than before: on laptop chips with performance and
efficiency cores, VidGrab now uses only the fast cores (using all of them was several times slower).

**Rendering** a 215 s clip to 1080p with the video encoded on the graphics card (Intel Quick Sync, NVIDIA NVENC or AMD AMF):

| Quality | CPU | GPU | With the CPU limited to 4 threads |
|---|---:|---:|---:|
| Fast | 14.9 s | 14.1 s | |
| Balanced | 26.3 s | **18.0 s** | 56 s → **20 s** |
| High | 41.5 s | **22.9 s** | 97 s → **28 s** |

The picture is just as good (SSIM 0.9973 against 0.9975 for the CPU encode at the same file size). Scaling, subtitles and
transitions still run on the CPU, so the gain is biggest at *High* quality and on laptops with fewer cores.

> Tested on that Intel laptop. The NVIDIA and AMD paths are in the app but couldn't be tried on real NVIDIA / AMD
> hardware yet: they check the card first and fall back to the CPU if anything fails. Please
> [open an issue](https://github.com/coherent17/VidGrab/issues) if one misbehaves for you.


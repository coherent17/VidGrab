"""Building and running the audio / video / split-screen renders."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from vidgrab.core.downloader import (
    DEFAULT_MP3_BITRATE,
    LogCallback,
    ProgressCallback,
    TranslateFn,
    _noop_tr,
    _parse_trim,
)
from vidgrab.core.gpu import HwEncoder, detect_encoder, video_args
from vidgrab.media import effects
from vidgrab.media.model import (
    FRAMINGS,
    HW_STALL_S,
    RENDER_QUALITY,
    RESOLUTIONS,
    SAMPLE_RATE,
    SPEED_RANGE,
    SUBTITLE_FONT_NAME,
    BackgroundMusic,
    Clip,
    ImageOverlay,
    Music,
    SubtitleCue,
    SubtitleStyle,
    _atempo,
    _ResolvedClip,
    _songs,
    transition_overlaps,
)
from vidgrab.media.probe import probe_media
from vidgrab.media.runner import (
    _AUDIO_FMT,
    DUCK,
    LOUDNESS,
    _audio_norm,
    _input_args,
    _require_ffmpeg,
    _run_with_progress,
    unique_path,
)
from vidgrab.media.subtitles import _subtitle_font, font_file, format_ass


def _resolve(
    clips: list[Clip],
    *,
    need_video: bool,
    translate: TranslateFn | None,
) -> list[_ResolvedClip]:
    tr = translate or _noop_tr
    if not clips:
        raise RuntimeError(tr("Add at least one clip first."))
    resolved: list[_ResolvedClip] = []
    for clip in clips:
        src = Path(clip.path)
        if not src.is_file():
            raise FileNotFoundError(tr("File not found: {src}", src=src))
        info = probe_media(src, translate=translate)
        start, end = _parse_trim(clip.start, clip.end, translate=translate)
        total = info["duration"]
        if total and start >= total:
            raise RuntimeError(
                tr(
                    "Clip start is past the end of {name}.",
                    name=src.name,
                )
            )
        stop = min(end, total) if total else end
        if stop == float("inf"):
            raise RuntimeError(
                tr("Could not determine the length of {name}.", name=src.name)
            )
        if need_video and not info["has_video"]:
            raise RuntimeError(
                tr("{name} has no video stream.", name=src.name)
            )
        if not need_video and not info["has_audio"]:
            raise RuntimeError(
                tr("{name} has no audio stream.", name=src.name)
            )
        resolved.append(
            _ResolvedClip(
                path=src,
                start=start,
                duration=stop - start,
                has_video=info["has_video"],
                has_audio=info["has_audio"],
                width=info["width"],
                height=info["height"],
                transition=clip.transition,
                transition_duration=clip.transition_duration,
                fit=clip.fit if clip.fit in FRAMINGS else "fit",
                zoom=max(1.0, float(clip.zoom or 1.0)),
                pan_x=min(max(float(clip.pan_x), 0.0), 1.0),
                pan_y=min(max(float(clip.pan_y), 0.0), 1.0),
                gain=min(clip.gain(), 2.0),
                speed=min(max(float(clip.speed or 1.0), SPEED_RANGE[0]), SPEED_RANGE[1]),
                denoise=bool(clip.denoise),
                fx=effects.sanitize(clip.fx),
            )
        )
    return resolved

# ── music medley ──────────────────────────────────────────────────────────


def build_audio_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    crossfade: float = 0.0,
    bitrate: str | None = None,
) -> tuple[list[str], float]:
    """ffmpeg argv + expected output length for an audio join."""
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    graph: list[str] = []
    for i, c in enumerate(clips):
        tempo = f",{_atempo(c.speed)}" if c.speed != 1.0 else ""
        graph.append(f"{_audio_norm(f'[{i}:a:0]', c.gain)}{tempo}[a{i}]")

    # a crossfade can't be longer than either neighbour
    fade = 0.0
    if crossfade > 0 and len(clips) > 1:
        shortest = min(c.out_duration for c in clips)
        fade = max(0.0, min(crossfade, shortest / 2))

    total = sum(c.out_duration for c in clips)
    if len(clips) == 1:
        out = "[a0]"
    elif fade > 0:
        prev = "[a0]"
        for i in range(1, len(clips)):
            nxt = f"[x{i}]"
            graph.append(f"{prev}[a{i}]acrossfade=d={fade:.3f}:c1=tri:c2=tri{nxt}")
            prev = nxt
        out = prev
        total -= fade * (len(clips) - 1)
    else:
        ins = "".join(f"[a{i}]" for i in range(len(clips)))
        graph.append(f"{ins}concat=n={len(clips)}:v=0:a=1[aout]")
        out = "[aout]"

    if output.suffix.lower() == ".m4a":  # AAC: whole 1024-sample frames (see video)
        graph.append(f"{out}{_AUDIO_FMT},asetnsamples=n=1024:p=0[aenc]")
        out = "[aenc]"
    cmd += ["-filter_complex", ";".join(graph), "-map", out, "-vn"]
    if output.suffix.lower() == ".m4a":
        cmd += ["-c:a", "aac", "-b:a", f"{bitrate or DEFAULT_MP3_BITRATE}k"]
    elif output.suffix.lower() == ".wav":
        cmd += ["-c:a", "pcm_s16le"]
    else:
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{bitrate or DEFAULT_MP3_BITRATE}k"]
    cmd.append(str(output))
    return cmd, total


def compose_audio(
    clips: list[Clip],
    output_file: str | Path,
    *,
    crossfade: float = 0.0,
    bitrate: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Join songs / song sections into one audio file."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=False, translate=translate)
    out = unique_path(Path(output_file))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd, total = build_audio_command(
        ffmpeg, resolved, out, crossfade=crossfade, bitrate=bitrate
    )
    _run_with_progress(
        cmd, total, label=tr("Rendering…"),
        on_progress=on_progress, on_log=on_log, translate=translate,
    )
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out


# ── video montage ─────────────────────────────────────────────────────────


def _even(n: float) -> int:
    return max(2, round(n / 2) * 2)


def canvas_size(resolution: str, first_width: int, first_height: int) -> tuple[int, int]:
    """Output frame size for *resolution* ("auto" follows the first clip)."""
    preset = RESOLUTIONS.get(resolution)
    if preset:
        return preset
    w, h = first_width or 1280, first_height or 720
    # cap "auto" at 1080 on the short side to keep renders reasonable
    short = min(w, h)
    if short > 1080:
        scale = 1080 / short
        w, h = w * scale, h * scale
    return _even(w), _even(h)


def _canvas(clips: list[_ResolvedClip], resolution: str) -> tuple[int, int]:
    return canvas_size(resolution, clips[0].width, clips[0].height)


def _frame_filter(c: _ResolvedClip, width: int, height: int, bars: str = "black") -> str:
    """Scale (+ crop) one clip onto the output canvas. *bars* is the colour of
    the padding (``black@0`` keeps it see-through for a green-screen clip)."""
    if c.fit == "fit" and c.zoom == 1.0 and not c.fx.get("keys"):  # the whole picture, centred, with bars
        return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={bars}")
    # cover (fill) or contain (fit) a box `zoom` times the canvas, then cut the
    # canvas out of it at the pan point and pad whatever is still missing
    keys = c.fx.get("keys")
    if keys:  # zoom keyframes: cover the canvas, then zoom and aim frame by frame
        zoom = effects.focus_expr(keys, c.start, 3)
        aim = c.fx.get("follow") or keys  # a face path, when there is one, steers the crop
        x = f"clip(({effects.focus_expr(aim, c.start, 1)})*iw-ow/2,0,iw-ow)"
        y = f"clip(({effects.focus_expr(aim, c.start, 2)})*ih-oh/2,0,ih-oh)"
        return (f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,"
                f"scale=w='trunc(iw*({zoom})/2)*2':h='trunc(ih*({zoom})/2)*2':eval=frame,"
                f"crop=w='min(iw,{width})':h='min(ih,{height})':x='{x}':y='{y}',"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={bars}")
    mode = "increase" if c.fit == "fill" else "decrease"
    zw, zh = _even(width * c.zoom), _even(height * c.zoom)
    x, y = f"(iw-ow)*{c.pan_x:.4f}", f"(ih-oh)*{c.pan_y:.4f}"
    follow = c.fx.get("follow")
    if follow:  # auto-reframe: the crop window centres on the face as the clip plays
        x = f"clip(({effects.focus_expr(follow, c.start, 1)})*iw-ow/2,0,iw-ow)"
        y = f"clip(({effects.focus_expr(follow, c.start, 2)})*ih-oh/2,0,ih-oh)"
    return (f"scale={zw}:{zh}:force_original_aspect_ratio={mode}:force_divisible_by=2,"
            f"crop=w='min(iw,{width})':h='min(ih,{height})':x='{x}':y='{y}',"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={bars}")


def _music_bed(label: str, m: BackgroundMusic, total: float) -> str:
    """One song as the montage hears it: its part, looped or not, coming in
    at its offset, with its own fades, volume and the end-of-video fade."""
    bed = _audio_norm(label)
    if m.trimmed():
        end = m.end or m.length or None
        bed += f",atrim=start={m.start:.3f}" + (f":end={end:.3f}" if end else "")
        bed += ",asetpts=PTS-STARTPTS"
        if m.loop and end and end > m.start:
            bed += f",aloop=loop=-1:size={int((end - m.start) * SAMPLE_RATE)}"
    if m.offset > 0:  # comes in later on the timeline
        # cut to the length still needed and restart the timestamps first
        # (adelay misreads aloop's output), then rebuild them from the
        # sample count (atrim / afade misread adelay's)
        bed += (f",atrim=0:{max(total - m.offset, 0.01):.3f},asetpts=PTS-STARTPTS"
                f",adelay={int(m.offset * 1000)}:all=1,asetpts=N/SR/TB")
    bed += f",atrim=0:{total:.3f}"
    part = m.part()
    if m.fade > 0:
        bed += f",afade=t=in:st={m.offset:.3f}:d={m.fade:.3f}"
        if not m.loop and part:
            stop = min(m.offset + part, total)
            bed += f",afade=t=out:st={max(m.offset, stop - m.fade):.3f}:d={m.fade:.3f}"
    bed += f",volume={max(0.0, m.volume):.3f}"
    if m.fade_out and total > 4:
        bed += f",afade=t=out:st={total - 3:.3f}:d=3"
    return bed


def _image_filter(img: ImageOverlay, frame_width: int) -> str:
    """Scale a picture to its width on the frame, with opacity and fades."""
    w = _even(frame_width * min(max(img.width, 0.01), 4.0))
    if img.motion in ("zoom_in", "zoom_out"):  # slow push in / pull out while it is shown
        size = effects.kenburns_scale(w, img.start, img.end, img.motion[5:])
        chain = f"format=rgba,scale={size}"
    else:
        chain = f"format=rgba,scale={w}:-2"
    if img.opacity < 1.0:
        chain += f",colorchannelmixer=aa={max(img.opacity, 0.0):.3f}"
    if img.fade > 0:
        fade = min(img.fade, (img.end - img.start) / 2)
        chain += (f",fade=t=in:st={img.start:.3f}:d={fade:.3f}:alpha=1"
                  f",fade=t=out:st={img.end - fade:.3f}:d={fade:.3f}:alpha=1")
    angle = img.rotation % 360
    if angle:  # turn around the centre; the corners it uncovers stay transparent
        rad = f"{angle:.3f}*PI/180"
        chain += f",rotate=a={rad}:c=none:ow=rotw({rad}):oh=roth({rad})"
    return chain


def _cover_graph(img: ImageOverlay, k: int, vin: str, width: int, height: int) -> list[str]:
    """Blur / pixelate the box of the frame between the overlay's start and end:
    cut the box out of the picture, hide it, put it back."""
    bw, bh = min(max(img.width, 0.01), 1.0), min(max(img.height, 0.01), 1.0)
    strength = min(max(img.strength, 0.0), 1.0)
    crop = (f"crop=w=trunc(iw*{bw:.4f}/2)*2:h=trunc(ih*{bh:.4f}/2)*2"
            f":x='max(0,min(iw-ow,iw*{img.x:.4f}-ow/2))':y='max(0,min(ih-oh,ih*{img.y:.4f}-oh/2))'")
    if img.kind == "pixel":
        blocks = 4 + round(strength * 28)  # bigger blocks the stronger it is
        hide = (f"scale=w='max(2,iw/{blocks})':h='max(2,ih/{blocks})',"
                f"scale=w='iw*{blocks}':h='ih*{blocks}':flags=neighbor")
    else:
        sigma = max(3.0, min(width, height) * (0.006 + 0.04 * strength))
        hide = f"gblur=sigma={sigma:.2f}:steps=2"
    return [
        f"{vin}split[cv{k}a][cv{k}b]",
        f"[cv{k}b]{crop},{hide}[cb{k}]",
        (f"[cv{k}a][cb{k}]overlay=x='max(0,min(main_w-overlay_w,main_w*{img.x:.4f}-overlay_w/2))'"
         f":y='max(0,min(main_h-overlay_h,main_h*{img.y:.4f}-overlay_h/2))'"
         f":enable='between(t,{img.start:.3f},{img.end:.3f})'[vo{k}]"),
    ]


def build_video_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    resolution: str = "auto",
    fps: int = 30,
    subtitles_file: str | None = None,
    fonts_dir: str | None = None,
    music: Music = None,
    music_has_audio: bool = True,
    quality: str = "balanced",
    images: list[ImageOverlay] | None = None,
    encoder: HwEncoder | None = None,
    normalize_loudness: bool = False,
) -> tuple[list[str], float]:
    """ffmpeg argv + output length for a video montage. With *normalize_loudness*
    the finished mix is brought to `LOUDNESS` (and clips with `denoise` are cleaned).

    *subtitles_file* (an ASS script from `format_ass`) / *fonts_dir* are
    paths relative to the ffmpeg working
    directory — the subtitles filter's own escaping rules make absolute
    Windows paths (``C:\\…``) fragile, so callers run ffmpeg from a temp dir."""
    width, height = _canvas(clips, resolution)
    preset, crf, abr = RENDER_QUALITY.get(quality, RENDER_QUALITY["balanced"])
    overlaps = transition_overlaps([c.out_duration for c in clips],
                                   [(c.transition, c.transition_duration) for c in clips])
    total = sum(c.out_duration for c in clips) - sum(overlaps)
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    next_input = len(clips)

    # silent stand-ins for clips that have no audio track
    silence: dict[int, int] = {}
    for i, c in enumerate(clips):
        if not c.has_audio:
            cmd += [
                "-f", "lavfi", "-t", f"{c.out_duration:.3f}",
                "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
            ]
            silence[i] = next_input
            next_input += 1

    # green-screen clips: what shows through them (a picture, or black)
    key_inputs: dict[int, int] = {}
    matte_inputs: dict[int, int] = {}
    for i, c in enumerate(clips):
        if not (effects.key_filter(c.fx) or c.matte):
            continue
        bg = c.fx.get("key_bg")
        if bg:
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{c.out_duration:.3f}", "-i", str(bg)]
        else:
            cmd += ["-f", "lavfi", "-t", f"{c.out_duration:.3f}",
                    "-i", f"color=c=black:s={width}x{height}:r={fps}"]
        key_inputs[i] = next_input
        next_input += 1
        if c.matte:
            cmd += ["-i", str(c.matte)]
            matte_inputs[i] = next_input
            next_input += 1

    # pictures: one looped still per overlay, only as long as it is needed
    image_inputs: list[int] = []
    for img in images or []:
        if not img.is_picture():  # a cover box has no file: it works on the video itself
            image_inputs.append(-1)
            continue
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{min(img.end, total):.3f}",
                "-i", str(img.path)]
        image_inputs.append(next_input)
        next_input += 1

    songs = _songs(music) if music_has_audio else []
    song_inputs: list[int] = []
    for m in songs:
        if m.loop and not m.trimmed():  # a trimmed part loops in the graph
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(m.path)]
        song_inputs.append(next_input)
        next_input += 1

    graph: list[str] = []
    for i, c in enumerate(clips):
        keyed = i in key_inputs
        # speed before fps, so the output still has a steady frame rate
        speed = f"setpts=(PTS-STARTPTS)/{c.speed:.6g}," if c.speed != 1.0 else ""
        if c.speed < 1.0 and c.fx.get("smooth"):
            speed += effects.smooth_filter(fps) + ","
        # xfade needs both inputs on one timebase, and concat changes it
        # ffmpeg 7.0's setpts forgets the frame rate, which xfade requires:
        # restate it, then put every input on one timebase
        tail = f",fps={fps},settb=AVTB" if any(overlaps) else ""
        key = effects.key_filter(c.fx)
        head = f"[{i}:v:0]{effects.source_chain(c.fx, trf_name=c.trf, lut_name=c.lut)}" + (key + "," if key else "")
        if keyed and i in matte_inputs:  # background removed: the matte is the clip's alpha
            graph.append(f"{head}{_frame_filter(c, width, height)},setsar=1,{speed}"
                         f"fps={fps},format=yuv420p,setpts=PTS-STARTPTS[kc{i}]")
            # the matte goes through the same framing, speed and frame rate as the picture,
            # softened a little and pushed towards 0 / 1 so the edge is clean
            graph.append(f"[{matte_inputs[i]}:v]scale={c.width or width}:{c.height or height}:flags=bicubic,"
                         f"{_frame_filter(c, width, height)},setsar=1,{speed}fps={fps},"
                         f"gblur=sigma=1.2,lut=y='clip((val-70)*2.4,0,255)',format=gray,setpts=PTS-STARTPTS[km{i}]")
            graph.append(f"[kc{i}][km{i}]alphamerge,format=yuva420p[k{i}]")
        elif keyed:  # the clip, see-through where the colour was, over its background
            graph.append(f"{head}{_frame_filter(c, width, height, 'black@0')},setsar=1,{speed}"
                         f"fps={fps},format=yuva420p,setpts=PTS-STARTPTS[k{i}]")
        if keyed:  # (either way) what shows through: the clip's background picture, or black
            graph.append(f"[{key_inputs[i]}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                         f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p,setpts=PTS-STARTPTS[kb{i}]")
            graph.append(f"[kb{i}][k{i}]overlay=shortest=1,format=yuv420p,setpts=PTS-STARTPTS{tail}[v{i}]")
        else:
            graph.append(f"{head}{_frame_filter(c, width, height)},setsar=1,{speed}"
                         f"fps={fps},format=yuv420p,setpts=PTS-STARTPTS{tail}[v{i}]")
        if i in silence:
            graph.append(f"{_audio_norm(f'[{silence[i]}:a]')}[a{i}]")
        else:
            tempo = f",{_atempo(c.speed)}" if c.speed != 1.0 else ""
            graph.append(f"{_audio_norm(f'[{i}:a:0]', c.gain, c.denoise)}{tempo}[a{i}]")
    if not any(overlaps):
        pairs = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
        graph.append(f"{pairs}concat=n={len(clips)}:v=1:a=1[vc][ac]")
    else:
        # join pairwise: xfade / acrossfade where a transition overlaps the
        # clips, a plain concat at cuts; `at` = where clip i starts in the output
        vprev, aprev, at = "[v0]", "[a0]", clips[0].out_duration
        for i in range(1, len(clips)):
            d = overlaps[i]
            vnext, anext = ("[vc]", "[ac]") if i == len(clips) - 1 else (f"[vx{i}]", f"[ax{i}]")
            if d > 0:
                at -= d
                graph.append(f"{vprev}[v{i}]xfade=transition={clips[i].transition}:"
                             f"duration={d:.3f}:offset={at:.3f}{vnext}")
                graph.append(f"{aprev}[a{i}]acrossfade=d={d:.3f}:c1=tri:c2=tri,{_AUDIO_FMT}{anext}")
            else:
                # concat drops the frame rate / timebase that the next xfade
                # checks (some ffmpeg builds refuse the mismatch): restate them
                graph.append(f"{vprev}[v{i}]concat=n=2:v=1:a=0,fps={fps},settb=AVTB{vnext}")
                graph.append(f"{aprev}[a{i}]concat=n=2:v=0:a=1,{_AUDIO_FMT}{anext}")
            at += clips[i].out_duration
            vprev, aprev = vnext, anext

    vout = "[vc]"
    # pictures go under the subtitles, each only between its start and end
    for k, (img, idx) in enumerate(zip(images or [], image_inputs, strict=True)):
        if not img.is_picture():
            graph.extend(_cover_graph(img, k, vout, width, height))
            vout = f"[vo{k}]"
            continue
        graph.append(f"[{idx}:v]{_image_filter(img, width)}[im{k}]")
        graph.append(
            f"{vout}[im{k}]overlay=x='main_w*{img.x:.4f}-overlay_w/2'"
            f":y='main_h*{img.y:.4f}-overlay_h/2'"
            f":enable='between(t,{img.start:.3f},{img.end:.3f})':eof_action=pass[vo{k}]")
        vout = f"[vo{k}]"
    if subtitles_file:
        opts = f"filename={subtitles_file}"
        if fonts_dir:
            opts += f":fontsdir={fonts_dir}"
        graph.append(f"{vout}subtitles={opts}[vs]")
        vout = "[vs]"

    aout = "[ac]"
    if songs:
        for k, (m, idx) in enumerate(zip(songs, song_inputs)):
            graph.append(f"{_music_bed(f'[{idx}:a:0]', m, total)}[bg{k}]")
        orig = f"volume={max(0.0, songs[0].original_volume):.3f}"
        beds = "".join(f"[bg{k}]" for k in range(len(songs)))
        if any(m.duck for m in songs):
            # the clips' own sound steers a compressor on the music (a "side chain"):
            # it presses the music down while someone talks and lets it back up after
            graph.append(f"[ac]asplit=2[acm][acs];[acm]{orig}[orig]")
            graph.append(f"{beds}amix=inputs={len(songs)}:duration=longest:dropout_transition=0"
                         ":normalize=0[bgm]")
            graph.append(f"[bgm][acs]{DUCK}[ducked]")
            graph.append("[orig][ducked]amix=inputs=2:duration=first:dropout_transition=0"
                         ":normalize=0[am]")
        else:
            graph.append(f"[ac]{orig}[orig]")
            graph.append(f"[orig]{beds}amix=inputs={len(songs) + 1}:duration=first"
                         ":dropout_transition=0:normalize=0[am]")
        aout = "[am]"

    # hand AAC whole 1024-sample frames (crossfades emit bigger ones, which some
    # ffmpeg builds pass straight to the encoder and it rejects)
    loud = f"{LOUDNESS}," if normalize_loudness else ""
    graph.append(f"{aout}{loud}{_AUDIO_FMT},asetnsamples=n=1024:p=0[aenc]")
    aout = "[aenc]"
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", vout, "-map", aout,
        *video_args(encoder, preset, crf),
        "-c:a", "aac", "-b:a", abr,
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd, total


# ── two videos at once (split screen) ─────────────────────────────────────

# layout -> how two videos share the frame; the first is drawn first, so in
# "pip" the second sits on top of it
SPLIT_LAYOUTS = ("side", "stack", "wide", "pip")
SPLIT_AUDIO = ("both", "first", "second", "none")
SPLIT_LENGTHS = ("longest", "shortest")


def _down(n: float) -> int:  # rounded down to even, so a gap is never squeezed
    return max(2, int(n) // 2 * 2)


def split_panels(layout: str, width: int, height: int, gap: int = 0) -> list[tuple[int, int, int, int]]:
    """(x, y, w, h) of the two videos on a *width* x *height* frame; *gap*
    pixels of background stay between side-by-side panels. The preview in the
    window calls this too, so both show the same picture."""
    gap = max(0, int(gap))
    if layout == "stack":
        h = _down((height - gap) / 2)
        return [(0, 0, width, h), (0, height - h, width, h)]
    if layout == "wide":  # a big picture and a narrow one beside it
        a = _down((width - gap) * 0.66)
        b = _down(width - gap - a)
        return [(0, 0, a, height), (width - b, 0, b, height)]
    if layout == "pip":  # the second video as a small window in the corner
        w, h = _even(width * 0.32), _even(height * 0.32)
        margin = _even(min(width, height) * 0.03)
        return [(0, 0, width, height), (width - w - margin, height - h - margin, w, h)]
    w = _down((width - gap) / 2)
    return [(0, 0, w, height), (width - w, 0, w, height)]


def split_canvas(resolution: str) -> tuple[int, int]:
    return RESOLUTIONS.get(resolution) or (1920, 1080)


def build_split_command(
    ffmpeg: str,
    clips: list[_ResolvedClip],
    output: Path,
    *,
    layout: str = "side",
    resolution: str = "1080p",
    fps: int = 30,
    gap: int = 0,
    audio: str = "both",
    length: str = "longest",
    quality: str = "balanced",
    encoder: HwEncoder | None = None,
) -> tuple[list[str], float]:
    """ffmpeg argv + output length for two videos playing at the same time.
    With *length* "longest" the shorter video holds its last picture."""
    if len(clips) != 2:
        raise ValueError("a split screen needs exactly two videos")
    width, height = split_canvas(resolution)
    preset, crf, abr = RENDER_QUALITY.get(quality, RENDER_QUALITY["balanced"])
    durations = [c.out_duration for c in clips]
    total = min(durations) if length == "shortest" else max(durations)
    keep = {"both": (1.0, 1.0), "first": (1.0, 0.0), "second": (0.0, 1.0)}.get(audio, (0.0, 0.0))
    cmd = [ffmpeg, "-y"]
    for c in clips:
        cmd += _input_args(c)
    silence: dict[int, int] = {}
    for i, c in enumerate(clips):
        if not c.has_audio:
            cmd += ["-f", "lavfi", "-t", f"{c.out_duration:.3f}",
                    "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo"]
            silence[i] = len(clips) + len(silence)

    panels = split_panels(layout, width, height, gap)
    graph = [f"color=c=black:s={width}x{height}:r={fps}:d={total:.3f},format=yuv420p[base]"]
    vprev = "[base]"
    for i, (c, (x, y, w, h)) in enumerate(zip(clips, panels)):
        hold = total - durations[i]
        graph.append(
            f"[{i}:v:0]{_frame_filter(c, w, h)},setsar=1,"
            + (f"setpts=(PTS-STARTPTS)/{c.speed:.6g}," if c.speed != 1.0 else "")
            + f"fps={fps},format=yuv420p,setpts=PTS-STARTPTS"
            + (f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.04 else "")
            + f"[p{i}]")
        graph.append(f"{vprev}[p{i}]overlay=x={x}:y={y}[o{i}]")
        vprev = f"[o{i}]"
        label = f"[{silence[i]}:a]" if i in silence else f"[{i}:a:0]"
        tempo = f",{_atempo(c.speed)}" if c.speed != 1.0 else ""
        graph.append(f"{_audio_norm(label, keep[i] * c.gain)}{tempo}[a{i}]")
    graph.append("[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                 f"alimiter=limit=0.95,{_AUDIO_FMT},asetnsamples=n=1024:p=0[aenc]")
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", vprev, "-map", "[aenc]", "-t", f"{total:.3f}",
        *video_args(encoder, preset, crf),
        "-c:a", "aac", "-b:a", abr,
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd, total


def compose_split(
    clips: list[Clip],
    output_file: str | Path,
    *,
    layout: str = "side",
    resolution: str = "1080p",
    gap: int = 0,
    audio: str = "both",
    length: str = "longest",
    quality: str = "balanced",
    hardware: bool = False,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Play two videos at the same time in one frame (see `split_panels`)
    and save the result as an MP4 that can be used like any other clip."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if len(clips) != 2:
        raise RuntimeError(tr("Choose two videos first."))
    if layout not in SPLIT_LAYOUTS:
        layout = "side"
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=True, translate=translate)
    out = unique_path(Path(output_file).resolve())
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vidgrab-split-") as tmp:
        _encode(
            lambda enc: build_split_command(
                ffmpeg, resolved, out, layout=layout, resolution=resolution, gap=gap,
                audio=audio, length=length, quality=quality, encoder=enc),
            ffmpeg, Path(tmp), hardware=hardware, on_progress=on_progress,
            on_log=on_log, translate=translate)
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out


EXPORT_FORMATS = (".mp4", ".gif", ".mp3", ".m4a", ".wav")


def _export_args(kind: str, gif_width: int, gif_fps: int) -> list[str]:
    """ffmpeg arguments that turn the rendered MP4 into *kind*."""
    if kind == ".gif":  # two-pass palette: GIF has 256 colours, pick the right ones
        graph = (f"[0:v]fps={gif_fps},scale={_even(gif_width)}:-2:flags=lanczos,split[a][b];"
                 "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
        return ["-filter_complex", graph, "-an", "-loop", "0"]
    if kind == ".mp3":
        return ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
    if kind == ".m4a":
        return ["-vn", "-c:a", "aac", "-b:a", "192k"]
    if kind == ".wav":
        return ["-vn", "-c:a", "pcm_s16le"]
    raise ValueError(f"unsupported export format {kind}")


def _encode(
    build,
    ffmpeg: str,
    work: Path,
    *,
    hardware: bool,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    translate: TranslateFn | None,
) -> float:
    """Run `build(encoder)` -> (argv, length): on the graphics card first when
    *hardware* and one works, and again on the CPU if that render fails or
    stalls. Returns the output length."""
    tr = translate or _noop_tr
    encoder = detect_encoder(ffmpeg) if hardware else None
    for attempt in (encoder, None) if encoder else (None,):
        cmd, total = build(attempt)
        if attempt and on_log:
            on_log(tr("Encoding on the graphics card ({name})", name=attempt.label))
        try:
            _run_with_progress(
                cmd, total, cwd=work, label=tr("Rendering…"),
                on_progress=on_progress, on_log=on_log, translate=translate,
                stall_s=HW_STALL_S if attempt else None,
            )
            return total
        except RuntimeError as exc:
            if attempt is None:
                raise
            if on_log:  # a driver problem in the middle of the render: do it on the CPU
                on_log(tr("The graphics card could not encode this ({err}); "
                          "rendering on the CPU instead", err=str(exc).splitlines()[-1]))
    raise RuntimeError("unreachable")  # pragma: no cover


def _prepare_effects(
    clips: list[_ResolvedClip],
    ffmpeg: str,
    work: Path,
    *,
    on_progress: ProgressCallback | None,
    on_log: LogCallback | None,
    translate: TranslateFn | None,
    models_dir: str | Path | None = None,
) -> list[_ResolvedClip]:
    """Do what the effects need before the render: analyse shaky clips (one
    pass each, written to *work*) and copy colour-look files next to the
    render, so the filter graph only ever names files in its own folder."""
    tr = translate or _noop_tr
    out: list[_ResolvedClip] = []
    for k, c in enumerate(clips):
        if c.fx.get("lut"):
            lut = Path(c.fx["lut"])
            if lut.is_file():
                shutil.copy2(lut, work / f"lut{k}.cube")
                c = replace(c, lut=f"lut{k}.cube")
            elif on_log:
                on_log(tr("File not found: {src}", src=lut))
        if c.fx.get("cutout") and c.has_video:
            from vidgrab.ai import matting

            if models_dir is None or not matting.available():
                if on_log:
                    on_log(tr("Removing the background needs the speech add-on (onnxruntime), which this "
                              "installation doesn't have."))
            else:
                name = f"matte{k}.mkv"
                matting.make_matte(c.path, c.start, c.start + c.duration, work / name, models_dir,
                                   on_progress=on_progress, translate=translate)
                c = replace(c, matte=name)
        if c.fx.get("stabilize") and c.has_video and not c.matte:  # (the matte would not follow the shake fix)
            name = f"stab{k}.trf"
            _run_with_progress(
                [ffmpeg, "-y", *_input_args(c), "-an", "-vf", effects.detect_filter(name),
                 "-f", "null", "-"],
                c.duration, cwd=work, label=tr("Steadying shaky video…"),
                on_progress=on_progress, on_log=on_log, translate=translate)
            c = replace(c, trf=name)
        out.append(c)
    return out


def compose_video(
    clips: list[Clip],
    output_file: str | Path,
    *,
    resolution: str = "auto",
    subtitles: list[SubtitleCue] | None = None,
    subtitle_style: SubtitleStyle | None = None,
    music: Music = None,
    quality: str = "balanced",
    images: list[ImageOverlay] | None = None,
    gif_width: int = 480,
    gif_fps: int = 15,
    hardware: bool = False,
    normalize_loudness: bool = False,
    models_dir: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    translate: TranslateFn | None = None,
) -> Path:
    """Join video clips, then optionally burn in subtitles and add music.
    The output's suffix picks the format: .mp4, or .gif / .mp3 / .m4a / .wav
    (rendered as MP4 first, then converted). With *hardware*, the video is
    encoded on the graphics card when one works (see `gpu.detect_encoder`),
    and again on the CPU if that render fails."""
    tr = translate or _noop_tr
    ffmpeg = _require_ffmpeg(translate)
    if on_progress:
        on_progress(tr("Reading clips…"), None)
    resolved = _resolve(clips, need_video=True, translate=translate)

    songs: list[BackgroundMusic] = []
    for m in _songs(music):
        mpath = Path(m.path)
        if not mpath.is_file():
            raise FileNotFoundError(tr("File not found: {src}", src=mpath))
        info = probe_media(mpath, translate=translate)
        if not info["has_audio"]:
            if on_log:
                on_log(tr("Background music has no audio track; skipping it."))
            continue
        songs.append(replace(m, path=str(mpath.resolve()), start=max(0.0, m.start),
                             offset=max(0.0, m.offset), length=info["duration"]))

    out = unique_path(Path(output_file).resolve())
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vidgrab-studio-") as tmp:
        work = Path(tmp)
        subs_name = fonts_name = None
        if subtitles:
            width, height = _canvas(resolved, resolution)
            (work / "subs.ass").write_text(
                format_ass(subtitles, width, height, subtitle_style), encoding="utf-8"
            )
            subs_name = "subs.ass"
            # hand libass the font files themselves: the bundled CJK font (also
            # the fallback for Chinese glyphs) plus the chosen font, if another
            wanted = [_subtitle_font()]
            fonts = {subtitle_style.font} if subtitle_style else set()
            fonts |= {c.look["font"] for c in subtitles if c.look and c.look.get("font")}
            wanted += [font_file(f) for f in fonts if f and f != SUBTITLE_FONT_NAME]
            for font in filter(None, wanted):
                (work / "fonts").mkdir(exist_ok=True)
                shutil.copy2(font, work / "fonts" / font.name)
                fonts_name = "fonts"
        resolved = _prepare_effects(resolved, ffmpeg, work, on_progress=on_progress,
                                    on_log=on_log, translate=translate, models_dir=models_dir)
        # GIF / audio-only exports: render the video first, then convert it
        kind = out.suffix.lower()
        render_to = out if kind == ".mp4" else work / "render.mp4"
        for attempt in (0, 1):
            try:
                total = _encode(
                    lambda enc, clips=resolved: build_video_command(
                        ffmpeg, clips, render_to,
                        resolution=resolution,
                        subtitles_file=subs_name,
                        fonts_dir=fonts_name,
                        music=songs,
                        images=[img for img in images or [] if img.end > img.start],
                        quality=quality,
                        encoder=enc,
                        normalize_loudness=normalize_loudness,
                    ),
                    ffmpeg, work, hardware=hardware, on_progress=on_progress, on_log=on_log,
                    translate=translate)
                break
            except RuntimeError:
                if attempt or not any(c.trf for c in resolved):
                    raise
                # a stabilising file this ffmpeg can't use: render without that effect
                if on_log:
                    on_log(tr("Could not steady the video; rendering without it"))
                resolved = [replace(c, trf=None) for c in resolved]
        if render_to != out:
            if on_progress:
                on_progress(tr("Converting…"), None)
            _run_with_progress(
                [ffmpeg, "-y", "-i", str(render_to), *_export_args(kind, gif_width, gif_fps),
                 str(out)],
                total, cwd=work, label=tr("Converting…"),
                on_progress=on_progress, on_log=on_log, translate=translate,
            )
    if on_log:
        on_log(tr("Saved: {name}", name=out.name))
    if on_progress:
        on_progress(tr("Complete"), 100.0)
    return out

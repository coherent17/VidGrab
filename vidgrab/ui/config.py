"""Settings file, defaults and the config / models folders."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from vidgrab.ai.captions import (
    default_models_dir,
)
from vidgrab.i18n import LANGUAGES
from vidgrab.ui.theme import _THEMES


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "VidGrab"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "vidgrab"


def _models_dir() -> Path:
    """The speech models live in the local cache (see captions.default_models_dir)."""
    return default_models_dir()


# every persisted setting with its default; config.json may hold any subset
DEFAULT_SETTINGS: dict = {
    "theme": "dark",
    "lang": "en",
    "out_dir": "",  # "" = ~/Downloads/VidGrab
    "fmt": "mp4",  # mp4 | mp3 | both
    "video_quality": None,  # None = best available
    "audio_quality": "192",
    "sub_enabled": False,
    "sub_lang": "zh-Hant",
    "sub_mode": "file",  # file | burn
    "name_template": "title",  # key of downloader.NAME_TEMPLATES
    "notify": True,
    "render_quality": "balanced",  # key of studio.RENDER_QUALITY
    "studio_resolution": "auto",
    "subtitle_presets": {},  # name -> SubtitleStyle fields
    "recent_projects": [],  # Studio .vgproj files, newest first
    "gpu_render": True,  # encode Studio videos on the graphics card when one works
    "gpu_captions": True,  # let auto captions use a graphics card when one works
    "caption_language": "auto",  # key of captions.LANGUAGES
    "caption_model": "balanced",  # key of captions.MODELS
    "audio_format": "mp3",  # key of downloader.AUDIO_FORMATS
    "rate_limit": 0,  # bytes per second, 0 = unlimited
    "proxy": "",  # e.g. http://host:8080 or socks5://host:1080
    "retries": 10,  # attempts for a failing download piece
    "skip_downloaded": False,  # playlists: leave out videos downloaded before
    "caption_style": "highlight",  # how auto captions come on screen (studio.ANIMATIONS)
    "sponsorblock": False,  # cut sponsor / self-promo parts out of downloads
    "cookies_browser": "",  # borrow this browser's login ("" = none)
    "online_suggest": True,  # offer YouTube's own search suggestions while typing in the link box
    "recent_searches": [],  # what was typed into the link box to search YouTube, newest first
    "update_check": True,  # tell me when a newer VidGrab is out (one quiet request to github.com)
    "ytdlp_check": True,  # look for a newer yt-dlp when the app starts
    "ui_font": "jakarta",  # a key of UI_FONTS (bundled), or "system" (the computer's own font)
}


def _load_config() -> dict:
    try:
        data = json.loads((_config_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    cfg = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy of the defaults
    cfg.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    if cfg["theme"] not in _THEMES:
        cfg["theme"] = "dark"
    if cfg["lang"] not in LANGUAGES:
        cfg["lang"] = "en"
    return cfg


def _save_config(theme: str, lang: str = "en", extra: dict | None = None) -> None:
    """Persist theme / language plus any *extra* settings, keeping the rest."""
    cfg = _load_config()
    cfg.update(theme=theme, lang=lang)
    cfg.update(extra or {})
    try:
        d = _config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    except OSError:
        pass

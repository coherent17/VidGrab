"""VidGrab internationalisation — English and Traditional Chinese."""

from __future__ import annotations

from collections.abc import Callable

LANGUAGES: dict[str, str] = {"en": "English", "zh": "繁體中文"}

_Translator = Callable[..., str]


def _fmt(text: str, kw: dict[str, object]) -> str:
    try:
        return text.format(**kw)
    except (KeyError, IndexError):
        return text


# ── translation table ───────────────────────────────────────────────────────
# Keys are the English source strings (used as lookup key).
# Values: {"en": ..., "zh": ...}.
# {…} placeholders are preserved and passed through via str.format().

TRANS: dict[str, dict[str, str]] = {
    # ── sidebar ──
    "Download":        {"en": "Download",        "zh": "下載"},
    "Edit":            {"en": "Edit",            "zh": "編輯"},
    "Settings":        {"en": "Settings",        "zh": "設定"},
    # ── header ──
    "☾ Dark":          {"en": "☾ Dark",          "zh": "☾ 深色"},
    "☀ Light":         {"en": "☀ Light",         "zh": "☀ 淺色"},
    # ── download page cards ──
    "SOURCE":          {"en": "SOURCE",          "zh": "來源"},
    "FORMAT":          {"en": "FORMAT",          "zh": "格式"},
    "FLIP":            {"en": "FLIP",            "zh": "翻轉"},
    "TRIM":            {"en": "TRIM",            "zh": "裁剪"},
    "SAVE TO":         {"en": "SAVE TO",         "zh": "儲存至"},
    # ── inputs / checkboxes ──
    "Paste a YouTube link…":        {"en": "Paste a YouTube link…",        "zh": "貼上 YouTube 連結…"},
    "Choose a local video or audio file…": {"en": "Choose a local video or audio file…", "zh": "選擇本地影片或音訊檔案…"},
    "Horizontal":      {"en": "Horizontal",      "zh": "水平"},
    "Vertical":        {"en": "Vertical",        "zh": "垂直"},
    "MP4 (video)":     {"en": "MP4 (video)",     "zh": "MP4 (影片)"},
    "MP3 (audio)":     {"en": "MP3 (audio)",     "zh": "MP3 (音訊)"},
    "Start:":          {"en": "Start:",          "zh": "開始:"},
    "End:":            {"en": "End:",            "zh": "結束:"},
    "Paste":           {"en": "Paste",           "zh": "貼上"},
    "Browse…":         {"en": "Browse…",         "zh": "瀏覽…"},
    "Clear":           {"en": "Clear",           "zh": "清除"},
    # ── settings page ──
    "APPEARANCE":      {"en": "APPEARANCE",      "zh": "外觀"},
    "Theme:":          {"en": "Theme:",          "zh": "主題:"},
    "Language:":       {"en": "Language:",       "zh": "語言:"},
    "ABOUT":           {"en": "ABOUT",           "zh": "關於"},
    "about_text": {
        "en": (
            "<b>VidGrab {ver}</b><br><br>"
            "Download YouTube videos (MP4 / MP3), or open a local file "
            "and flip or trim it.<br><br>"
            "Built with Python, PySide6, yt-dlp and ffmpeg.<br>"
            "MIT License — use and modify freely."
        ),
        "zh": (
            "<b>VidGrab {ver}</b><br><br>"
            "下載 YouTube 影片（MP4 / MP3），或開啟本地檔案<br>"
            "進行翻轉或裁剪。<br><br>"
            "使用 Python、PySide6、yt-dlp 與 ffmpeg 製作。<br>"
            "MIT 授權條款 — 自由使用與修改。"
        ),
    },
    # ── about dialog ──
    "about_title": {
        "en": "About VidGrab",
        "zh": "關於 VidGrab",
    },
    "about_dialog": {
        "en": (
            "<h3>VidGrab {ver}</h3>"
            "<p>Download YouTube videos (MP4 / MP3), or open a local file "
            "and flip or trim it.</p>"
            "<p>Built with Python, PySide6, yt-dlp and ffmpeg.<br>"
            "MIT License — use and modify freely.</p>"
        ),
        "zh": (
            "<h3>VidGrab {ver}</h3>"
            "<p>下載 YouTube 影片（MP4 / MP3），或開啟本地檔案<br>"
            "進行翻轉或裁剪。</p>"
            "<p>使用 Python、PySide6、yt-dlp 與 ffmpeg 製作。<br>"
            "MIT 授權條款 — 自由使用與修改。</p>"
        ),
    },
    # ── action buttons ──
    "⬇  Download":     {"en": "⬇  Download",     "zh": "⬇  下載"},
    "✂  Process":      {"en": "✂  Process",      "zh": "✂  處理"},
    "⬇  Downloading…": {"en": "⬇  Downloading…", "zh": "⬇  下載中…"},
    "✂  Processing…":  {"en": "✂  Processing…",  "zh": "✂  處理中…"},
    # ── status bar ──
    "checking…":       {"en": "checking…",       "zh": "檢查中…"},
    "Online":          {"en": "Online",          "zh": "已連線"},
    "Offline":         {"en": "Offline",         "zh": "離線"},
    "ffmpeg: embedded": {"en": "ffmpeg: embedded", "zh": "ffmpeg: 內建"},
    "ffmpeg: not found": {"en": "ffmpeg: not found", "zh": "ffmpeg: 未找到"},
    "ffmpeg: {name}":  {"en": "ffmpeg: {name}",  "zh": "ffmpeg: {name}"},
    # ── log header / progress ──
    "LOG":             {"en": "LOG",             "zh": "記錄"},
    "Ready":           {"en": "Ready",           "zh": "就緒"},
    "Done":            {"en": "Done",            "zh": "完成"},
    "Failed":          {"en": "Failed",          "zh": "失敗"},
    # ── dialogs ──
    "Missing URL":     {"en": "Missing URL",     "zh": "未提供網址"},
    "Please paste a YouTube link.": {
        "en": "Please paste a YouTube link.",
        "zh": "請貼上 YouTube 連結。",
    },
    "No internet":     {"en": "No internet",     "zh": "無網路連線"},
    "You appear to be offline.\nVidGrab needs a live connection.": {
        "en": "You appear to be offline.\nVidGrab needs a live connection.",
        "zh": "目前無法連線。\nVidGrab 需要網路連線。",
    },
    "ffmpeg required":  {"en": "ffmpeg required",  "zh": "需要 ffmpeg"},
    "Downloads need ffmpeg for MP3 and most MP4 merges. "
    "Install ffmpeg or rebuild with an embedded copy.": {
        "en": "Downloads need ffmpeg for MP3 and most MP4 merges. "
              "Install ffmpeg or rebuild with an embedded copy.",
        "zh": "MP3 與大部分 MP4 合併下載需要 ffmpeg。\n請安裝 ffmpeg 或使用內建版本。",
    },
    "Processing local files requires ffmpeg. "
    "Install ffmpeg or rebuild with an embedded copy.": {
        "en": "Processing local files requires ffmpeg. "
              "Install ffmpeg or rebuild with an embedded copy.",
        "zh": "處理本地檔案需要 ffmpeg。\n請安裝 ffmpeg 或使用內建版本。",
    },
    "No file":         {"en": "No file",         "zh": "未選擇檔案"},
    "Please select a local media file.": {
        "en": "Please select a local media file.",
        "zh": "請選擇一個本地媒體檔案。",
    },
    "File not found":  {"en": "File not found",  "zh": "找不到檔案"},
    "The file does not exist:\n{path}": {
        "en": "The file does not exist:\n{path}",
        "zh": "檔案不存在:\n{path}",
    },
    "Success":         {"en": "Success",         "zh": "成功"},
    "Saved to:\n{paths}": {
        "en": "Saved to:\n{paths}",
        "zh": "已儲存至:\n{paths}",
    },
    "Something went wrong": {
        "en": "Something went wrong",
        "zh": "發生錯誤",
    },
    "Task in progress": {
        "en": "Task in progress",
        "zh": "任務執行中",
    },
    "A download or processing task is still running.\n"
    "Please wait for it to complete before closing.": {
        "en": "A download or processing task is still running.\n"
              "Please wait for it to complete before closing.",
        "zh": "下載或處理任務仍在執行中。\n請等待完成後再關閉。",
    },
    # ── tooltips ──
    "tooltip_switch_theme": {
        "en": "Switch between dark and light theme",
        "zh": "切換深色與淺色主題",
    },
    "tooltip_page_download": {
        "en": "Download a video from YouTube",
        "zh": "從 YouTube 下載影片",
    },
    "tooltip_page_edit": {
        "en": "Trim or flip a local media file",
        "zh": "裁剪或翻轉本地媒體檔案",
    },
    "tooltip_page_settings": {
        "en": "Theme, language and about",
        "zh": "主題、語言與關於",
    },
    "tooltip_paste": {
        "en": "Paste the URL from the clipboard (Ctrl+V)",
        "zh": "從剪貼簿貼上網址（Ctrl+V）",
    },
    "tooltip_browse_out": {
        "en": "Choose the output folder",
        "zh": "選擇輸出資料夾",
    },
    "tooltip_browse_file": {
        "en": "Select a local media file",
        "zh": "選擇本地媒體檔案",
    },
    "tooltip_clear": {
        "en": "Clear the log (Ctrl+L)",
        "zh": "清除記錄（Ctrl+L）",
    },
    "tooltip_action_download": {
        "en": "Start downloading",
        "zh": "開始下載",
    },
    "tooltip_action_edit": {
        "en": "Start processing",
        "zh": "開始處理",
    },
}

# ── downloader messages ─────────────────────────────────────────────────────
# The key is the exact English format-string template.
TRANS.update({
    "Trimming…":       {"en": "Trimming…",       "zh": "裁剪中…"},
    "ffmpeg failed to process the file (exit code {code}).": {
        "en": "ffmpeg failed to process the file (exit code {code}).",
        "zh": "ffmpeg 處理檔案失敗（結束代碼 {code}）。",
    },
    'Invalid start time "{t}". '
    "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).": {
        "en": 'Invalid start time "{t}". '
              "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).",
        "zh": '無效的開始時間「{t}」。'
              "請輸入秒數（90）、M:SS（1:30）或 H:MM:SS（1:02:03）。",
    },
    'Invalid end time "{t}". '
    "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).": {
        "en": 'Invalid end time "{t}". '
              "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).",
        "zh": '無效的結束時間「{t}」。'
              "請輸入秒數（90）、M:SS（1:30）或 H:MM:SS（1:02:03）。",
    },
    "Trim end time must be after the start time. "
    "Got start {s}s, end {e}s.": {
        "en": "Trim end time must be after the start time. "
              "Got start {s}s, end {e}s.",
        "zh": "裁剪結束時間必須晚於開始時間。"
              "開始 {s} 秒，結束 {e} 秒。",
    },
    "Extracting audio…": {"en": "Extracting audio…", "zh": "正在提取音訊…"},
    "Saved: {name}":     {"en": "Saved: {name}",     "zh": "已儲存: {name}"},
    "Complete":          {"en": "Complete",          "zh": "完成"},
    "Copied: {name}":    {"en": "Copied: {name}",    "zh": "已複製: {name}"},
    "No URL provided.":  {"en": "No URL provided.",  "zh": "未提供連結。"},
    "Downloading… {pct:.1f}%": {
        "en": "Downloading… {pct:.1f}%", "zh": "下載中… {pct:.1f}%",
    },
    "Downloading…":      {"en": "Downloading…",      "zh": "下載中…"},
    "Processing…":       {"en": "Processing…",       "zh": "處理中…"},
    "ffmpeg is required for MP3 downloads. "
    "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
    "or install ffmpeg and add it to PATH.": {
        "en": "ffmpeg is required for MP3 downloads. "
              "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
              "or install ffmpeg and add it to PATH.",
        "zh": "MP3 下載需要 ffmpeg。請將 ffmpeg 放入應用程式旁的 'ffmpeg' 資料夾，"
              "或安裝 ffmpeg 並加入 PATH。",
    },
    "ffmpeg is required to trim downloads.": {
        "en": "ffmpeg is required to trim downloads.",
        "zh": "裁剪下載需要 ffmpeg。",
    },
    "Could not fetch video information.": {
        "en": "Could not fetch video information.",
        "zh": "無法取得影片資訊。",
    },
    "Section download unavailable ({exc}); downloading in full.": {
        "en": "Section download unavailable ({exc}); downloading in full.",
        "zh": "片段下載不可用（{exc}），改為下載完整檔案。",
    },
    "Download finished but output file was not found.": {
        "en": "Download finished but output file was not found.",
        "zh": "下載完成但找不到輸出檔案。",
    },
    "ffmpeg failed to extract MP3 audio": {
        "en": "ffmpeg failed to extract MP3 audio",
        "zh": "ffmpeg 提取 MP3 音訊失敗",
    },
    "File not found: {src}": {
        "en": "File not found: {src}",
        "zh": "找不到檔案: {src}",
    },
    "ffmpeg is required to extract MP3 audio.": {
        "en": "ffmpeg is required to extract MP3 audio.",
        "zh": "提取 MP3 音訊需要 ffmpeg。",
    },
    "ffmpeg is required to process local files. "
    "Install ffmpeg or place it next to the app.": {
        "en": "ffmpeg is required to process local files. "
              "Install ffmpeg or place it next to the app.",
        "zh": "處理本地檔案需要 ffmpeg。"
              "請安裝 ffmpeg 或將其放置於應用程式旁。",
    },
    "{prefix} (exit code {code}).": {
        "en": "{prefix} (exit code {code}).",
        "zh": "{prefix}（結束代碼 {code}）。",
    },
    "ffmpeg failed":     {"en": "ffmpeg failed",     "zh": "ffmpeg 失敗"},
})


# ── public API ──────────────────────────────────────────────────────────────


def translate(lang: str, text: str, **kw: object) -> str:
    """Return *text* translated for *lang*, with optional *kw* formatting."""
    entry = TRANS.get(text)
    if entry is not None:
        text = entry.get(lang) or entry["en"]
    if kw:
        text = _fmt(text, kw)
    return text


def make_translator(lang: str) -> _Translator:
    """Return a callable ``tr(text, **kw)`` bound to *lang*."""
    return lambda text, **kw: translate(lang, text, **kw)  # type: ignore[return-value]

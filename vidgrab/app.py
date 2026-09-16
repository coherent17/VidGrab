#!/usr/bin/env python3
"""VidGrab — modern dark/light desktop UI (CustomTkinter)."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from vidgrab import __version__
from vidgrab.downloader import (
    default_output_dir,
    download,
    download_both,
    find_ffmpeg,
    get_app_dir,
    process_local_file,
)
from vidgrab.network import ConnectionStatus, check_internet

# --- palette (used by custom widgets / pills / log; theme handles the rest) ---
BG = "#0f141c"
SURFACE = "#1b2230"
ACCENT = "#4f7cff"
ACCENT_HI = "#6a92ff"
ACCENT_DARK = "#3b5fd0"
TEXT = "#e8ecf4"
MUTED = "#8b97aa"
SUCCESS = "#3ecf8e"
ORANGE = "#f0a050"
ERROR = "#ff6b6b"
LOG_BG = "#0c1017"
TROUGH = "#11151f"

PILL = {"online": SUCCESS, "offline": ERROR, "checking": ORANGE}


def get_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "VidGrab"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "vidgrab"


class _Tooltip:
    """Lightweight hover tooltip for any widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._win: ctk.CTkToplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _event: tk.Event) -> str | None:
        if self._win is not None:
            return None
        x, y, _, _ = self._widget.winfo_rootx(), self._widget.winfo_rooty(), 0, 0
        x += 12
        y += self._widget.winfo_height() + 8
        win = ctk.CTkToplevel(self._widget)
        win.wm_overrideredirect(True)
        win.geometry(f"+{x}+{y}")
        win.attributes("-topmost", True)
        win.configure(fg_color=SURFACE)
        label = ctk.CTkLabel(
            win, text=self._text, text_color=TEXT, font=ctk.CTkFont(size=11),
            fg_color=SURFACE, padx=10, pady=6,
        )
        label.pack()
        self._win = win
        return None

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self._win is not None:
            self._win.destroy()
            self._win = None


class VidGrabApp(ctk.CTk):
    def __init__(self) -> None:
        self._warn_high_dpi()
        self._load_config()
        ctk.set_appearance_mode(self._theme)
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("VidGrab")
        self.geometry("660x720")
        self.minsize(580, 640)

        self._download_thread: threading.Thread | None = None
        self._internet_thread: threading.Thread | None = None
        self._internet_online: bool | None = None
        self._busy = False

        self._set_window_icon()
        self._build_ui()
        self._update_ffmpeg_status()
        self._internet_tick()
        self._bind_shortcuts()

    # ------------------------------------------------------------ helpers
    def _warn_high_dpi(self) -> None:
        if sys.platform != "win32":
            return
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001,S110 - best effort, ignore
            pass

    def _load_config(self) -> None:
        try:
            data = json.loads((get_config_dir() / "config.json").read_text())
            self._theme = data.get("theme", "dark")
        except (OSError, json.JSONDecodeError):
            self._theme = "dark"
        if self._theme not in ("dark", "light"):
            self._theme = "dark"

    def _save_config(self) -> None:
        try:
            cfg_dir = get_config_dir()
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "config.json").write_text(json.dumps({"theme": self._theme}))
        except OSError:
            pass

    def _set_window_icon(self) -> None:
        app_dir = get_app_dir()
        try:
            if sys.platform == "win32":
                ico = app_dir / "assets" / "icon.ico"
                if ico.is_file():
                    self.iconbitmap(str(ico))
            else:
                png = app_dir / "assets" / "icon.png"
                if png.is_file():
                    photo = tk.PhotoImage(file=str(png))
                    self.iconphoto(True, photo)
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        padx = 16

        # header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill=tk.X, padx=padx, pady=(12, 4))
        title = ctk.CTkLabel(
            header, text="⬇  VidGrab",
            font=ctk.CTkFont(size=20, weight="bold"), anchor="w",
        )
        title.pack(side=tk.LEFT)
        _Tooltip(title, f"VidGrab {__version__}\nFree & open source")
        ctk.CTkLabel(
            header, text=f"v{__version__}", text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).pack(side=tk.LEFT, padx=(8, 0), pady=(6, 0))

        self.theme_menu = ctk.CTkOptionMenu(
            header, width=96, values=["Dark", "Light"],
            command=self._set_theme, fg_color=SURFACE,
            button_color=ACCENT, button_hover_color=ACCENT_HI,
        )
        self.theme_menu.set(self._theme.capitalize())
        self.theme_menu.pack(side=tk.RIGHT)

        ctk.CTkButton(
            header, text="About", width=64, command=self._show_about,
            fg_color=SURFACE, hover_color=ACCENT_DARK,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        ctk.CTkLabel(
            header, text="YouTube videos or local files with flip & trim",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        ).pack(side=tk.LEFT, padx=(4, 0), pady=(7, 0))

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill=tk.BOTH, expand=True, padx=padx, pady=10)
        main.columnconfigure(0, weight=1)

        # --- source card ---
        source = ctk.CTkFrame(
            main, fg_color=SURFACE, corner_radius=10,
            border_width=1, border_color="#2a3342",
        )
        source.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(0, weight=1)

        self.source_seg = ctk.CTkSegmentedButton(
            source, values=["YouTube URL", "Local File"],
            command=self._refresh_source_row, height=32,
            fg_color=LOG_BG, selected_color=ACCENT,
            selected_hover_color=ACCENT_HI, text_color=MUTED,
        )
        self.source_seg.grid(row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 8))
        self.source_seg.set("YouTube URL")

        # url row
        self._url_row = ctk.CTkFrame(source, fg_color="transparent")
        self._url_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        self._url_row.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar()
        self.url_entry = ctk.CTkEntry(
            self._url_row, textvariable=self.url_var, placeholder_text="Paste a YouTube link…",
            height=36, corner_radius=6,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda _e: self._start_download())
        ctk.CTkButton(
            self._url_row, text="Paste", width=72, height=36,
            command=self._do_paste, fg_color=SURFACE, hover_color=ACCENT_DARK,
        ).grid(row=0, column=1, padx=(8, 0))

        # local file row
        self._file_row = ctk.CTkFrame(source, fg_color="transparent")
        self._file_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        self._file_row.columnconfigure(0, weight=1)
        self.local_file_var = tk.StringVar()
        self.local_entry = ctk.CTkEntry(
            self._file_row, textvariable=self.local_file_var,
            placeholder_text="Choose a local video or audio file…", height=36, corner_radius=6,
        )
        self.local_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            self._file_row, text="Browse…", width=88, height=36,
            command=self._browse_local_file, fg_color=SURFACE, hover_color=ACCENT_DARK,
        ).grid(row=0, column=1, padx=(8, 0))

        # --- format card ---
        self._fmt_card = ctk.CTkFrame(
            main, fg_color=SURFACE, corner_radius=10,
            border_width=1, border_color="#2a3342",
        )
        self._fmt_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.format_mp4_var = tk.BooleanVar(value=True)
        self.format_mp3_var = tk.BooleanVar(value=False)
        self._fmt_mp4_cb = ctk.CTkCheckBox(
            self._fmt_card, text="MP4 (video)", variable=self.format_mp4_var,
            fg_color=SUCCESS, hover_color=SUCCESS, corner_radius=4,
            font=ctk.CTkFont(size=13), checkbox_width=20, checkbox_height=20,
        )
        self._fmt_mp4_cb.grid(row=0, column=0, padx=(16, 28), pady=14, sticky="w")
        self._fmt_mp3_cb = ctk.CTkCheckBox(
            self._fmt_card, text="MP3 (audio)", variable=self.format_mp3_var,
            fg_color=ORANGE, hover_color=ORANGE, corner_radius=4,
            font=ctk.CTkFont(size=13), checkbox_width=20, checkbox_height=20,
        )
        self._fmt_mp3_cb.grid(row=0, column=1, padx=(0, 16), pady=14, sticky="w")
        _Tooltip(self._fmt_mp4_cb, "MP4 keeps video (and audio)")
        _Tooltip(self._fmt_mp3_cb, "MP3 extracts audio only")

        # --- flip + trim ---
        opts = ctk.CTkFrame(main, fg_color="transparent")
        opts.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)

        flip = ctk.CTkFrame(opts, fg_color=SURFACE, corner_radius=10, border_width=1, border_color="#2a3342")
        flip.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.hflip_var = tk.BooleanVar(value=False)
        self.vflip_var = tk.BooleanVar(value=False)
        ctk.CTkLabel(flip, text="FLIP", text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 2))
        ctk.CTkCheckBox(flip, text="Horizontal", variable=self.hflip_var, fg_color=ACCENT, corner_radius=4).grid(
            row=1, column=0, sticky="w", padx=14, pady=(4, 12))
        ctk.CTkCheckBox(flip, text="Vertical", variable=self.vflip_var, fg_color=ACCENT, corner_radius=4).grid(
            row=1, column=1, sticky="w", padx=(0, 14), pady=(4, 12))

        trim = ctk.CTkFrame(opts, fg_color=SURFACE, corner_radius=10, border_width=1, border_color="#2a3342")
        trim.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(trim, text="TRIM", text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(10, 2))
        self.trim_start_var = tk.StringVar()
        self.trim_end_var = tk.StringVar()
        ctk.CTkLabel(trim, text="Start", text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
            row=1, column=0, padx=(14, 6), pady=(4, 12))
        ctk.CTkEntry(trim, textvariable=self.trim_start_var, placeholder_text="0:00", width=72, height=32, corner_radius=6).grid(
            row=1, column=1, pady=(4, 12))
        ctk.CTkLabel(trim, text="End", text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
            row=1, column=2, padx=(10, 6), pady=(4, 12))
        ctk.CTkEntry(trim, textvariable=self.trim_end_var, placeholder_text="∞", width=72, height=32, corner_radius=6).grid(
            row=1, column=3, padx=(0, 14), pady=(4, 12))

        # --- save to ---
        save = ctk.CTkFrame(main, fg_color=SURFACE, corner_radius=10, border_width=1, border_color="#2a3342")
        save.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        save.columnconfigure(0, weight=1)
        self.output_var = tk.StringVar(value=str(default_output_dir()))
        ctk.CTkEntry(save, textvariable=self.output_var, height=36, corner_radius=6).grid(
            row=0, column=0, sticky="ew", padx=(14, 8), pady=12)
        ctk.CTkButton(save, text="Browse…", width=88, height=36, command=self._browse_output,
                      fg_color=SURFACE, hover_color=ACCENT_DARK).grid(row=0, column=1, padx=(0, 14))

        # --- progress + status ---
        prog = ctk.CTkFrame(main, fg_color="transparent")
        prog.grid(row=4, column=0, sticky="ew", pady=(4, 6))
        prog.columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(prog, height=10, corner_radius=5,
                                           progress_color=ACCENT, fg_color=TROUGH)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)
        self.status_var = tk.StringVar(value="Ready")
        ctk.CTkLabel(prog, textvariable=self.status_var, text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=1, padx=(12, 0))

        # --- log ---
        log_card = ctk.CTkFrame(main, fg_color=LOG_BG, corner_radius=10, border_width=1, border_color="#2a3342")
        log_card.grid(row=5, column=0, sticky="nsew", pady=(4, 8))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(8, 2))
        ctk.CTkLabel(log_header, text="LOG", text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold")).pack(side=tk.LEFT)
        ctk.CTkButton(log_header, text="Clear", width=52, height=22, command=self._clear_log,
                      fg_color=SURFACE, hover_color=ACCENT_DARK, font=ctk.CTkFont(size=11)).pack(side=tk.RIGHT)
        self.log_text = ctk.CTkTextbox(
            log_card, height=150, corner_radius=8, fg_color=LOG_BG,
            text_color=MUTED, font=ctk.CTkFont(family="Consolas", size=11), wrap="word",
        )
        self.log_text.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=14, pady=(2, 12))
        self.log_text.configure(state="disabled")

        # --- download button ---
        self.download_btn = ctk.CTkButton(
            main, text="⬇  Download", command=self._start_download,
            height=44, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HI,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.download_btn.grid(row=6, column=0, sticky="ew", pady=(2, 6))
        # enabled once the first internet probe reports online
        self.download_btn.configure(state="disabled")
        # initialize source-mode visibility
        self._refresh_source_row()

        # --- footer: ffmpeg + internet ---
        footer = ctk.CTkFrame(main, fg_color="transparent")
        footer.grid(row=7, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.ffmpeg_var = tk.StringVar()
        ctk.CTkLabel(footer, textvariable=self.ffmpeg_var, text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self.net_pill = ctk.CTkLabel(
            footer, text="● checking…", text_color=ORANGE,
            font=ctk.CTkFont(size=11, weight="bold"), anchor="e",
        )
        self.net_pill.grid(row=0, column=1, sticky="e")
        _Tooltip(self.net_pill, "Live internet status")

        main.rowconfigure(5, weight=1)

    # ------------------------------------------------------------- theme
    def _set_theme(self, choice: str) -> None:
        self._theme = choice.lower()
        ctk.set_appearance_mode(self._theme)
        self._save_config()

    def _show_about(self) -> None:
        self._dlg(
            "About VidGrab",
            f"VidGrab {__version__}\n\n"
            "Download YouTube videos (MP4 / MP3), or open a local file "
            "and flip or trim it.\n\n"
            "Built with Python, CustomTkinter, yt-dlp and ffmpeg.\n"
            "MIT License — use and modify freely.",
            actions=[("OK", None)],
        )

    # ------------------------------------------------------------ dialogs
    def _dlg(
        self,
        title: str,
        message: str,
        *,
        kind: str = "info",
        actions: list[tuple[str, callable | None]] | None = None,
        parent: ctk.CTkToplevel | None = None,
    ) -> None:
        win = ctk.CTkToplevel(parent or self)
        win.title(title)
        win.configure(fg_color=SURFACE)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        color = {"error": ERROR, "success": SUCCESS, "info": ACCENT}.get(kind, ACCENT)
        ctk.CTkLabel(win, text=title, text_color=color, font=ctk.CTkFont(size=15, weight="bold")).pack(
            padx=26, pady=(18, 6), anchor="w")
        msg = ctk.CTkLabel(win, text=message, text_color=TEXT, justify="left", wraplength=420,
                           font=ctk.CTkFont(size=12))
        msg.pack(fill=tk.X, padx=26, pady=(0, 14))
        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill=tk.X, padx=26, pady=(0, 16))
        for text, cb in (actions or [("OK", None)]):
            ctk.CTkButton(btn_row, text=text, width=96, height=32, corner_radius=6,
                          fg_color=ACCENT, hover_color=ACCENT_HI,
                          command=lambda w=win, c=cb: (w.destroy(), (c() if c else None))[-1]).pack(
                side=tk.RIGHT, padx=(8, 0))

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 3)
        win.geometry(f"+{int(x)}+{int(y)}")
        win.grab_set()
        self.wait_window(win)

    # ------------------------------------------------------------ handlers
    def _bind_shortcuts(self) -> None:
        self.bind("<Control-o>", lambda _e: self._browse_local_file())
        self.bind("<Control-O>", lambda _e: self._browse_local_file())
        self.bind("<Control-l>", lambda _e: self._clear_log())
        self.bind("<Control-L>", lambda _e: self._clear_log())
        self.bind("<F1>", lambda _e: self._show_about())

    def _do_paste(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        self.url_entry.focus_set()
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, text)

    def _browse_output(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_var.get())
        if folder:
            self.output_var.set(folder)

    def _browse_local_file(self) -> None:
        filetypes = [
            ("Media files", "*.mp4 *.mp3 *.mkv *.webm *.avi *.mov *.m4a *.wav *.flac"),
            ("MP4 files", "*.mp4"),
            ("MP3 files", "*.mp3"),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.local_file_var.set(path)

    def _refresh_source_row(self, _value: str | None = None) -> None:
        mode = self.source_seg.get()
        if mode.startswith("YouTube"):
            self._url_row.grid()
            self._file_row.grid_remove()
            self._fmt_card.grid()
            self.download_btn.configure(text="⬇  Download")
        else:
            self._url_row.grid_remove()
            self._file_row.grid()
            self._fmt_card.grid_remove()
            self.download_btn.configure(text="⬇  Process")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_ffmpeg_status(self) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            if Path(ffmpeg).is_relative_to(get_app_dir()):
                self.ffmpeg_var.set("ffmpeg: embedded")
            else:
                self.ffmpeg_var.set(f"ffmpeg: {Path(ffmpeg)}")
        else:
            self.ffmpeg_var.set("ffmpeg not found — install ffmpeg or rebuild")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        mode = self.source_seg.get()
        label = "Processing…" if mode.startswith("Local") else "Downloading…"
        text = label if busy else ("⬇  Process" if mode.startswith("Local") else "⬇  Download")
        self.download_btn.configure(state="disabled" if (busy or not self._internet_online) else "normal",
                                    text=text)

    # ------------------------------------------------- neutron status
    def _internet_tick(self) -> None:
        if self._internet_thread is None or not self._internet_thread.is_alive():
            self._internet_thread = threading.Thread(target=self._internet_probe, daemon=True)
            self._internet_thread.start()
        self.after(10000, self._internet_tick)

    def _internet_probe(self) -> None:
        status = check_internet(timeout=2.5)
        try:
            self.after(0, lambda: self._apply_internet(status))
        except Exception:  # noqa: BLE001 - app may already be closed
            pass

    def _apply_internet(self, status: ConnectionStatus) -> None:
        self._internet_online = status.online
        self.net_pill.configure(
            text="● Online" if status.online else "○ Offline",
            text_color=PILL["online" if status.online else "offline"],
        )
        if not self._busy:
            state = "normal" if status.online else "disabled"
            self.download_btn.configure(state=state)

    # ---------------------------------------------------------- progress
    def _on_progress(self, message: str, percent: float | None) -> None:
        def update() -> None:
            self.status_var.set(message)
            if percent is not None:
                self.progress.set(min(1.0, percent / 100))

        self.after(0, update)

    def _on_log(self, message: str) -> None:
        self.after(0, lambda: self._append_log(message))

    # -------------------------------------------------------------- start
    def _start_download(self) -> None:
        if self._download_thread and self._download_thread.is_alive():
            return

        if not self._internet_online and self.source_seg.get().startswith("YouTube"):
            self._dlg(
                "No internet connection",
                "You appear to be offline.\n\n"
                "VidGrab needs a live internet connection to reach YouTube.",
                kind="error",
                actions=[("Exit", self.destroy), ("Check again", self._internet_tick)],
            )
            return

        mode = self.source_seg.get()
        if mode.startswith("Local"):
            self._start_local_file()
        else:
            self._start_url()

    def _start_local_file(self) -> None:
        input_path = self.local_file_var.get().strip()
        if not input_path:
            self._dlg("No file", "Please select a local media file.", kind="error")
            return
        if not Path(input_path).is_file():
            self._dlg("File not found", f"The file does not exist:\n{input_path}", kind="error")
            return
        if not find_ffmpeg():
            self._dlg(
                "ffmpeg required",
                "Processing local files requires ffmpeg.\n\n"
                "Linux/macOS:\n  sudo apt install ffmpeg\n\n"
                "Windows:\n  Put ffmpeg.exe in an 'ffmpeg' folder next to the app.",
                kind="error",
            )
            return

        self.progress.set(0)
        self.status_var.set("Starting…")
        self._set_busy(True)

        def worker() -> None:
            try:
                flip_parts = []
                if self.hflip_var.get():
                    flip_parts.append("hflip")
                if self.vflip_var.get():
                    flip_parts.append("vflip")
                flip = ",".join(flip_parts) or None
                result = process_local_file(
                    input_path,
                    self.output_var.get(),
                    video_filter=flip,
                    section_start=self.trim_start_var.get().strip() or None,
                    section_end=self.trim_end_var.get().strip() or None,
                    on_progress=self._on_progress,
                    on_log=self._on_log,
                )
                self.after(0, lambda: self._finish_ok([result]))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: self._finish_err(e))

        self._download_thread = threading.Thread(target=worker, daemon=True)
        self._download_thread.start()

    def _start_url(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            self._dlg("Missing URL", "Please paste a YouTube link.", kind="error")
            return
        if not find_ffmpeg():
            self._dlg(
                "ffmpeg required",
                "Downloads need ffmpeg for MP3 and most MP4 merges.",
                kind="error",
            )
            return

        self.progress.set(0)
        self.status_var.set("Starting…")
        self._set_busy(True)

        def worker() -> None:
            try:
                flip_parts = []
                if self.hflip_var.get():
                    flip_parts.append("hflip")
                if self.vflip_var.get():
                    flip_parts.append("vflip")
                flip = ",".join(flip_parts) or None
                start = self.trim_start_var.get().strip()
                end = self.trim_end_var.get().strip()
                out_dir = self.output_var.get()
                want_mp4 = self.format_mp4_var.get()
                want_mp3 = self.format_mp3_var.get()

                if want_mp4 and want_mp3:
                    mp4, mp3 = download_both(
                        url, out_dir, video_filter=flip,
                        section_start=start or None, section_end=end or None,
                        on_progress=self._on_progress, on_log=self._on_log,
                    )
                    self.after(0, lambda: self._finish_ok([mp4, mp3]))
                else:
                    fmt = "mp3" if want_mp3 else "mp4"
                    result = download(
                        url, out_dir, fmt, video_filter=flip,
                        section_start=start or None, section_end=end or None,
                        on_progress=self._on_progress, on_log=self._on_log,
                    )
                    self.after(0, lambda: self._finish_ok([result]))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: self._finish_err(e))

        self._download_thread = threading.Thread(target=worker, daemon=True)
        self._download_thread.start()

    def _finish_ok(self, saved_paths: list[Path]) -> None:
        self._set_busy(False)
        self.progress.set(1.0)
        self.status_var.set("Done")
        self._dlg(
            "Success",
            "Saved to:\n" + "\n".join(str(p) for p in saved_paths),
            kind="success",
        )

    def _finish_err(self, exc: Exception) -> None:
        self._set_busy(False)
        self.status_var.set("Failed")
        self._append_log(f"Error: {exc}")
        self._dlg("Something went wrong", str(exc), kind="error")


def main() -> None:
    app = VidGrabApp()
    app.mainloop()


if __name__ == "__main__":
    main()
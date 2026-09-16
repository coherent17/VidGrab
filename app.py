#!/usr/bin/env python3
"""VidGrab — download, flip & trim media."""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from downloader import (
    default_output_dir,
    download,
    find_ffmpeg,
    get_app_dir,
    process_local_file,
)

# --- palette ---
BG = "#151922"          # window background
SURFACE = "#1f2633"     # card background
SURFACE_ALT = "#242c3b" # input / hover background
BORDER = "#2e3850"      # card border
TEXT = "#e8ecf4"        # main text
MUTED = "#8b97aa"       # secondary text
ACCENT = "#4f7cff"      # primary accent (blue)
ACCENT_HI = "#6a92ff"   # accent hover
ACCENT_DARK = "#3b5fd0"
SUCCESS = "#3ecf8e"
ORANGE = "#f0a050"
ERROR = "#ff6b6b"
LOG_BG = "#10141c"
TROUGH = "#11151f"


class VidGrabApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VidGrab")
        self.geometry("620x680")
        self.minsize(540, 600)
        self.configure(bg=BG)

        self._download_thread: threading.Thread | None = None
        self._configure_style()
        self._set_window_icon()
        self._build_ui()
        self._update_ffmpeg_status()

    def _set_window_icon(self) -> None:
        """Use the bundled app icon instead of tkinter's default feather."""
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

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=TROUGH,
            background=ACCENT,
            bordercolor=TROUGH,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=10,
        )

    # ---------------------------------------------------------------- style
    def _card(self, parent, title: str) -> tk.Frame:
        """Return a titled card frame with a border."""
        card = tk.Frame(
            parent,
            bg=SURFACE,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )
        tk.Label(
            card,
            text=title.upper(),
            bg=SURFACE,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 2))
        return card

    # ---------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        padx = 18

        # --- header ---
        header = tk.Frame(self, bg=SURFACE, bd=0, highlightthickness=0)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="⬇  VidGrab",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI", 20, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, padx=padx, pady=(14, 4))
        tk.Label(
            header,
            text="Download, flip & trim YouTube videos or local files",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side=tk.LEFT, padx=(4, 0), pady=(20, 0))

        main = tk.Frame(self, bg=BG)
        main.pack(fill=tk.BOTH, expand=True, padx=padx, pady=14)
        main.columnconfigure(0, weight=1)

        self._name_var = tk.StringVar()

        # --- source card (URL or local file) ---
        url_card = self._card(main, "Source")
        url_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        url_card.columnconfigure(0, weight=1)

        # mode toggle row
        toggle_row = tk.Frame(url_card, bg=SURFACE)
        toggle_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))

        self._source_mode = tk.StringVar(value="url")

        def _make_toggle(mode):
            def _cmd():
                self._source_mode.set(mode)
                self._refresh_source_row()
            return _cmd

        self._toggle_url_btn = tk.Button(
            toggle_row, text="YouTube URL", command=_make_toggle("url"),
            bg=ACCENT, fg="white", activebackground=ACCENT_HI, activeforeground="white",
            relief=tk.FLAT, font=("Segoe UI", 9, "bold"), cursor="hand2", padx=12, pady=3,
        )
        self._toggle_url_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._toggle_file_btn = tk.Button(
            toggle_row, text="Local File", command=_make_toggle("file"),
            bg=SURFACE_ALT, fg=MUTED, activebackground=ACCENT, activeforeground="white",
            relief=tk.FLAT, font=("Segoe UI", 9), cursor="hand2", padx=12, pady=3,
        )
        self._toggle_file_btn.pack(side=tk.LEFT)

        # URL input row
        self._url_input_row = tk.Frame(url_card, bg=SURFACE)
        self._url_input_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))
        self._url_input_row.columnconfigure(0, weight=1)

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(
            self._url_input_row,
            textvariable=self.url_var,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", ipady=7)
        self.url_entry.bind("<Control-v>", self._paste_url)
        self.url_entry.bind("<Control-V>", self._paste_url)

        tk.Button(
            self._url_input_row,
            text="Paste",
            command=self._paste_from_button,
            bg=SURFACE_ALT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="white",
            relief=tk.FLAT,
            padx=16,
            cursor="hand2",
        ).grid(row=0, column=1, padx=(8, 0), ipady=3)
        self.url_entry.focus_set()

        # local file input row (hidden by default)
        self._file_input_row = tk.Frame(url_card, bg=SURFACE)
        self._file_input_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))
        self._file_input_row.columnconfigure(0, weight=1)

        self.local_file_var = tk.StringVar()
        self.local_file_entry = tk.Entry(
            self._file_input_row,
            textvariable=self.local_file_var,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            state=tk.DISABLED,
        )
        self.local_file_entry.grid(row=0, column=0, sticky="ew", ipady=7)

        tk.Button(
            self._file_input_row,
            text="Browse…",
            command=self._browse_local_file,
            bg=SURFACE_ALT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="white",
            relief=tk.FLAT,
            padx=16,
            cursor="hand2",
        ).grid(row=0, column=1, padx=(8, 0), ipady=3)

        # start in URL mode
        self._file_input_row.grid_remove()

        # --- format card ---
        self._fmt_card = self._card(main, "Format")
        self._fmt_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        fmt_row = tk.Frame(self._fmt_card, bg=SURFACE)
        fmt_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))

        self.format_mp4_var = tk.BooleanVar(value=True)
        self.format_mp3_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            fmt_row,
            text="MP4 (video)",
            variable=self.format_mp4_var,
            bg=SURFACE,
            fg=TEXT,
            activebackground=SURFACE,
            activeforeground=TEXT,
            selectcolor=SUCCESS,
            font=("Segoe UI", 10),
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 24))
        tk.Checkbutton(
            fmt_row,
            text="MP3 (audio)",
            variable=self.format_mp3_var,
            bg=SURFACE,
            fg=TEXT,
            activebackground=SURFACE,
            activeforeground=TEXT,
            selectcolor=ORANGE,
            font=("Segoe UI", 10),
            cursor="hand2",
        ).pack(side=tk.LEFT)

        # --- options: flip + trim side by side ---
        opts = tk.Frame(main, bg=BG)
        opts.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)

        # flip card
        flip_card = self._card(opts, "Flip")
        flip_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        flip_row = tk.Frame(flip_card, bg=SURFACE)
        flip_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))
        self.hflip_var = tk.BooleanVar(value=False)
        self.vflip_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            flip_row,
            text="Horizontal",
            variable=self.hflip_var,
            bg=SURFACE,
            fg=TEXT,
            activebackground=SURFACE,
            activeforeground=TEXT,
            selectcolor=SURFACE,
            font=("Segoe UI", 10),
        ).pack(side=tk.LEFT, padx=(0, 14), anchor="w")
        tk.Checkbutton(
            flip_row,
            text="Vertical",
            variable=self.vflip_var,
            bg=SURFACE,
            fg=TEXT,
            activebackground=SURFACE,
            activeforeground=TEXT,
            selectcolor=SURFACE,
            font=("Segoe UI", 10),
        ).pack(side=tk.LEFT, anchor="w")

        # trim card
        trim_card = self._card(opts, "Trim")
        trim_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        trim_row = tk.Frame(trim_card, bg=SURFACE)
        trim_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))

        self.trim_start_var = tk.StringVar()
        self.trim_end_var = tk.StringVar()
        self._dim_label(trim_row, "Start").pack(side=tk.LEFT)
        tk.Entry(
            trim_row,
            textvariable=self.trim_start_var,
            width=9,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=(4, 10), ipady=3)
        self._dim_label(trim_row, "End").pack(side=tk.LEFT)
        tk.Entry(
            trim_row,
            textvariable=self.trim_end_var,
            width=9,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=(4, 0), ipady=3)

        # --- save to card ---
        save_card = self._card(main, "Save to")
        save_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        save_card.columnconfigure(0, weight=1)

        save_row = tk.Frame(save_card, bg=SURFACE)
        save_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))
        save_row.columnconfigure(0, weight=1)

        self.output_var = tk.StringVar(value=str(default_output_dir()))
        tk.Entry(
            save_row,
            textvariable=self.output_var,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="ew", ipady=4)
        tk.Button(
            save_row,
            text="Browse…",
            command=self._browse_output,
            bg=SURFACE_ALT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="white",
            relief=tk.FLAT,
            padx=14,
            cursor="hand2",
        ).grid(row=0, column=1, padx=(8, 0), ipady=2)

        # --- progress ---
        prog_row = tk.Frame(main, bg=BG)
        prog_row.grid(row=4, column=0, sticky="ew", pady=(6, 4))
        prog_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            prog_row,
            mode="determinate",
            maximum=100,
            length=400,
        )
        self.progress.grid(row=0, column=0, sticky="ew", ipady=3)
        self.progress_var = tk.StringVar(value="Ready")
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            prog_row,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="e",
        ).grid(row=0, column=1, padx=(10, 0))

        # --- log card ---
        log_card = self._card(main, "Log")
        log_card.grid(row=5, column=0, sticky="nsew", pady=(4, 10))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        self.log_text = tk.Text(
            log_card,
            height=8,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg=LOG_BG,
            fg=MUTED,
            insertbackground=TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=8,
            font=("Consolas", 9),
            selectbackground=ACCENT_DARK,
        )
        log_card.rowconfigure(1, weight=1)
        self.log_text.grid(
            row=1, column=0, columnspan=3, sticky="nsew", padx=12, pady=(0, 12)
        )
        scroll = tk.Scrollbar(
            log_card, command=self.log_text.yview, bg=SURFACE, troughcolor=TROUGH
        )
        scroll.grid(row=1, column=3, sticky="ns", pady=(0, 12))
        self.log_text.configure(yscrollcommand=scroll.set)

        # --- download button ---
        self.download_btn = tk.Button(
            main,
            text="⬇  Download",
            command=self._start_download,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_HI,
            activeforeground="white",
            disabledforeground="#aebcf0",
            relief=tk.FLAT,
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
            pady=10,
        )
        self.download_btn.grid(row=6, column=0, sticky="ew", pady=(4, 8))

        # --- ffmpeg status footer ---
        self.ffmpeg_var = tk.StringVar()
        tk.Label(
            main,
            textvariable=self.ffmpeg_var,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).grid(row=7, column=0, sticky="ew")

        main.rowconfigure(5, weight=1)

    def _dim_label(self, parent, text) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9, "bold"),
        )

    # ---------------------------------------------------------------- handlers
    def _paste_url(self, event: tk.Event) -> str:
        self._do_paste()
        return "break"

    def _paste_from_button(self) -> None:
        self._do_paste()

    def _do_paste(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        entry = self.url_entry
        entry.focus_set()
        if entry.selection_present():
            entry.delete("sel.first", "sel.last")
        entry.insert(tk.INSERT, text)

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

    def _refresh_source_row(self) -> None:
        mode = self._source_mode.get()
        if mode == "url":
            self._url_input_row.grid()
            self._file_input_row.grid_remove()
            self._fmt_card.grid()
            self._toggle_url_btn.configure(bg=ACCENT, fg="white", font=("Segoe UI", 9, "bold"))
            self._toggle_file_btn.configure(bg=SURFACE_ALT, fg=MUTED, font=("Segoe UI", 9))
            self.download_btn.configure(text="⬇  Download")
        else:
            self._url_input_row.grid_remove()
            self._file_input_row.grid()
            self._fmt_card.grid_remove()
            self._toggle_url_btn.configure(bg=SURFACE_ALT, fg=MUTED, font=("Segoe UI", 9))
            self._toggle_file_btn.configure(bg=ACCENT, fg="white", font=("Segoe UI", 9, "bold"))
            self.download_btn.configure(text="⬇  Process")

    def _update_ffmpeg_status(self) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            from downloader import get_app_dir
            if Path(ffmpeg).is_relative_to(get_app_dir()):
                self.ffmpeg_var.set("ffmpeg: embedded (bundled in this app)")
            else:
                self.ffmpeg_var.set(f"ffmpeg: {ffmpeg}")
        else:
            self.ffmpeg_var.set(
                "ffmpeg not found — install with: sudo apt install ffmpeg"
            )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        mode = self._source_mode.get()
        if busy:
            label = "Processing…" if mode == "file" else "Downloading…"
        else:
            label = "⬇  Process" if mode == "file" else "⬇  Download"
        self.download_btn.configure(
            state=tk.DISABLED if busy else tk.NORMAL,
            text=label,
        )

    def _on_progress(self, message: str, percent: float | None) -> None:
        def update() -> None:
            self.status_var.set(message)
            if percent is not None:
                self.progress["value"] = percent

        self.after(0, update)

    def _on_log(self, message: str) -> None:
        self.after(0, lambda: self._append_log(message))

    def _start_download(self) -> None:
        mode = self._source_mode.get()

        if self._download_thread and self._download_thread.is_alive():
            return

        # --- local file mode ---
        if mode == "file":
            input_path = self.local_file_var.get().strip()
            if not input_path:
                messagebox.showwarning("No file", "Please select a local media file.")
                return
            from pathlib import Path as _P
            if not _P(input_path).is_file():
                messagebox.showwarning("File not found", f"The file does not exist:\n{input_path}")
                return

            if not find_ffmpeg():
                messagebox.showerror(
                    "ffmpeg required",
                    "Processing local files requires ffmpeg.\n\n"
                    "WSL/Linux:\n  sudo apt install ffmpeg\n\n"
                    "Windows:\n  Place ffmpeg.exe in a folder named 'ffmpeg' next to this app, "
                    "or install ffmpeg and add it to PATH.",
                )
                return

            self.progress["value"] = 0
            self.status_var.set("Starting…")
            self._set_busy(True)

            def worker_file() -> None:
                try:
                    flip_parts = []
                    if self.hflip_var.get():
                        flip_parts.append("hflip")
                    if self.vflip_var.get():
                        flip_parts.append("vflip")
                    video_filter = ",".join(flip_parts) if flip_parts else None

                    start = self.trim_start_var.get().strip()
                    end = self.trim_end_var.get().strip()

                    result = process_local_file(
                        input_path,
                        self.output_var.get(),
                        video_filter=video_filter,
                        section_start=start or None,
                        section_end=end or None,
                        on_progress=self._on_progress,
                        on_log=self._on_log,
                    )

                    def done_ok() -> None:
                        self._set_busy(False)
                        self.progress["value"] = 100
                        self.status_var.set("Done")
                        messagebox.showinfo("Success", f"Processed file saved to:\n{result}")

                    self.after(0, done_ok)
                except Exception as exc:
                    err_msg = str(exc)

                    def done_err() -> None:
                        self._set_busy(False)
                        self.status_var.set("Failed")
                        self._append_log(f"Error: {err_msg}")
                        messagebox.showerror("Processing failed", err_msg)

                    self.after(0, done_err)

            self._download_thread = threading.Thread(target=worker_file, daemon=True)
            self._download_thread.start()
            return

        # --- URL mode ---
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a YouTube link.")
            return

        if not find_ffmpeg():
            messagebox.showerror(
                "ffmpeg required",
                "Downloads need ffmpeg for MP3 and most MP4 merges.\n\n"
                "WSL/Linux:\n  sudo apt install ffmpeg\n\n"
                "Windows:\n  Place ffmpeg.exe in a folder named 'ffmpeg' next to this app, "
                "or install ffmpeg and add it to PATH.",
            )
            return

        self.progress["value"] = 0
        self.status_var.set("Starting…")
        self._set_busy(True)

        def worker_url() -> None:
            try:
                flip_parts = []
                if self.hflip_var.get():
                    flip_parts.append("hflip")
                if self.vflip_var.get():
                    flip_parts.append("vflip")
                video_filter = ",".join(flip_parts) if flip_parts else None

                start = self.trim_start_var.get().strip()
                end = self.trim_end_var.get().strip()

                formats = []
                if self.format_mp4_var.get():
                    formats.append("mp4")
                if self.format_mp3_var.get():
                    formats.append("mp3")
                if not formats:
                    formats.append("mp4")

                saved_paths = []
                for fmt in formats:
                    saved_paths.append(
                        download(
                            url,
                            self.output_var.get(),
                            fmt,
                            video_filter=video_filter,
                            section_start=start or None,
                            section_end=end or None,
                            on_progress=self._on_progress,
                            on_log=self._on_log,
                        )
                    )

                def done_ok() -> None:
                    self._set_busy(False)
                    self.progress["value"] = 100
                    self.status_var.set("Done")
                    paths = "\n".join(str(p) for p in saved_paths)
                    messagebox.showinfo("Success", f"Saved to:\n{paths}")

                self.after(0, done_ok)
            except Exception as exc:
                err_msg = str(exc)

                def done_err() -> None:
                    self._set_busy(False)
                    self.status_var.set("Failed")
                    self._append_log(f"Error: {err_msg}")
                    messagebox.showerror("Download failed", err_msg)

                self.after(0, done_err)

        self._download_thread = threading.Thread(target=worker_url, daemon=True)
        self._download_thread.start()


def main() -> None:
    app = VidGrabApp()
    app.mainloop()


if __name__ == "__main__":
    main()
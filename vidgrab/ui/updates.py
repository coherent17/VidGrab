"""yt-dlp and VidGrab updates."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import (
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QMessageBox,
)

from vidgrab.core import (
    opener,
    self_update,
    update_check,
    ytdlp_update,
)
from vidgrab.core.downloader import (
    NETWORK,
)
from vidgrab.ui.chrome import PAGE_SETTINGS
from vidgrab.ui.workers import _detached, _InstallThread, _ReleaseThread, _YtdlpThread


class UpdatesMixin:
    """yt-dlp and VidGrab updates."""

    def _refresh_ytdlp(self) -> None:
        t = self._t
        try:
            version, own = ytdlp_update.current_version(), ytdlp_update.in_use()
        except Exception:  # noqa: BLE001
            version, own = "?", False
        pending = ytdlp_update.installed()
        self._ytdlp_lbl.setText(f"yt-dlp <b>{version}</b> · "
                                + (t("updated by you") if own else t("built in")))
        self._ytdlp_lbl.setTextFormat(Qt.RichText)
        info = self._ytdlp_info
        busy = self._ytdlp_thread is not None and self._ytdlp_thread.isRunning()
        if info and info.get("newer"):
            self._ytdlp_btn.setText(t("Update to {v}", v=info["latest"]))
        else:
            self._ytdlp_btn.setText(t("Check for updates"))
        self._ytdlp_btn.setEnabled(not busy)
        # a pip install is updated by pip: no second updater next to it
        for w in (self._ytdlp_btn, self._set_ytdlp_auto, self._ytdlp_hint):
            w.setVisible(self._can_update_ytdlp)
        self._ytdlp_pip.setVisible(not self._can_update_ytdlp)
        self._ytdlp_reset.setVisible(bool(pending) or own)
        if not self._ytdlp_msg:
            self._ytdlp_status.setText(
                t("Version {v} will be used after you restart VidGrab.", v=pending["version"])
                if pending and not own else "")
        self._ytdlp_status.setVisible(bool(self._ytdlp_status.text()))

    def _ytdlp_say(self, text: str) -> None:
        self._ytdlp_msg = text
        self._ytdlp_status.setText(text)
        self._ytdlp_status.setVisible(bool(text))

    def _ytdlp_action(self) -> None:
        if self._ytdlp_thread is not None and self._ytdlp_thread.isRunning():
            return
        updating = bool(self._ytdlp_info and self._ytdlp_info.get("newer"))
        self._ytdlp_say(self._t("Downloading the update…") if updating
                        else self._t("Looking for updates…"))
        self._start_ytdlp("update" if updating else "check")

    def _start_ytdlp(self, task: str, quiet: bool = False) -> None:
        thread = _YtdlpThread(task)
        thread.result.connect(lambda r, q=quiet: self._on_ytdlp_result(r, q))
        thread.failed.connect(lambda m, q=quiet: self._on_ytdlp_failed(m, q))
        thread.finished.connect(self._refresh_ytdlp)
        self._ytdlp_thread = thread
        self._refresh_ytdlp()
        thread.start()

    def _on_ytdlp_result(self, result: dict, quiet: bool) -> None:
        t = self._t
        if "updated" in result:
            self._ytdlp_info = None
            self._ytdlp_say(t("Updated to {v}. Restart VidGrab to use it.", v=result["updated"]))
            self._update_note.hide()
            return
        self._ytdlp_info = result
        if result["newer"]:
            self._ytdlp_say(t("Version {v} is available.", v=result["latest"]))
            self._update_note.setText(t("A newer yt-dlp ({v}) is available — update", v=result["latest"]))
            self._update_note.show()
        else:
            self._ytdlp_say("" if quiet else t("yt-dlp is up to date."))
            self._update_note.hide()

    def _on_ytdlp_failed(self, msg: str, quiet: bool) -> None:
        if not quiet:
            self._ytdlp_say(self._t("Could not reach the update server: {err}", err=msg))

    def _ytdlp_use_builtin(self) -> None:
        ytdlp_update.reset()
        self._ytdlp_info = None
        self._ytdlp_say(self._t("The built-in version will be used after you restart VidGrab."))
        self._refresh_ytdlp()

    def check_for_release(self) -> None:
        """Ask (in the background) whether a newer VidGrab was released."""
        if getattr(self, "_release_thread", None) is not None and self._release_thread.isRunning():
            return
        self._release_thread = _ReleaseThread(NETWORK.proxy)
        self._release_thread.found.connect(self._on_release)
        self._release_thread.start()

    def _on_release(self, news: dict) -> None:
        self._release_info = news
        self._release_plan = self_update.plan(news)  # None: this copy can't replace itself, so the button opens the page
        key = "VidGrab {v} is out — update now" if self._release_plan else "VidGrab {v} is out — see what is new"
        self._release_note.setText(self._t(key, v=news["version"]))
        self._release_note.setToolTip(news.get("notes", ""))
        self._release_note.show()

    def _release_clicked(self) -> None:
        news = getattr(self, "_release_info", None) or {}
        how = getattr(self, "_release_plan", None)
        if not how:
            self.open_url(update_check.PAGE)
            return
        box = QMessageBox(self)
        box.setWindowTitle(self._t("Update VidGrab"))
        box.setText(self._t("Install VidGrab {v} now?", v=news.get("version", "")))
        box.setInformativeText(self._t("VidGrab downloads it, checks the file and swaps it in. Your projects and "
                                       "settings stay as they are. Restart afterwards to use it."))
        go = box.addButton(self._t("Update now"), QMessageBox.AcceptRole)
        notes = box.addButton(self._t("What's new"), QMessageBox.ActionRole)
        box.addButton(self._t("Later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is notes:
            self.open_url(news.get("url") or update_check.PAGE)
        elif box.clickedButton() is go:
            self._install_release(news, how)

    def _install_release(self, news: dict, how) -> None:
        if getattr(self, "_install_thread", None) is not None and self._install_thread.isRunning():
            return
        self._release_note.setEnabled(False)
        self._release_note.setText(self._t("Downloading the update…"))
        self._install_thread = _InstallThread(news, how, NETWORK.proxy)
        self._install_thread.progress.connect(
            lambda pct: self._release_note.setText(
                self._t("Downloading the update… {p}%", p=pct) if pct >= 0 else self._t("Downloading the update…")))
        self._install_thread.done.connect(self._release_installed)
        self._install_thread.failed.connect(self._release_failed)
        self._install_thread.start()

    def _release_failed(self, message: str) -> None:
        self._release_note.setEnabled(True)
        self._on_release(self._release_info)
        QMessageBox.warning(self, self._t("Update VidGrab"), self._t(message) + "\n\n" +
                            self._t("Nothing was changed. You can download it from the release page."))

    def _release_installed(self) -> None:
        self._release_note.setText(self._t("Installed — restart VidGrab to use it"))
        self._release_note.setEnabled(True)
        self._release_note.clicked.disconnect()
        self._release_note.clicked.connect(self._restart_app)
        ask = QMessageBox.question(self, self._t("Update VidGrab"),
                                   self._t("VidGrab {v} is installed. Restart now?",
                                           v=self._release_info.get("version", "")))
        if ask == QMessageBox.Yes:
            self._restart_app()

    def _restart_app(self) -> None:
        try:
            subprocess.Popen([sys.executable], close_fds=True, **_detached())
        except OSError as exc:
            QMessageBox.warning(self, self._t("Update VidGrab"), str(exc))
            return
        self.close()

    def open_url(self, url: str) -> None:
        if not opener.open_url(url):
            QDesktopServices.openUrl(QUrl(url))

    def _update_note_clicked(self) -> None:
        self._sidebar.set_page(PAGE_SETTINGS) if hasattr(self._sidebar, "set_page") else None
        self._stack.setCurrentIndex(PAGE_SETTINGS)
        self._set_tabs[1].click()
        self._ytdlp_action()

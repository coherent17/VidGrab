import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SMOKE_GUI") != "1", reason="set SMOKE_GUI=1 to enable")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_import_fills_the_link_box(qapp, tmp_path, monkeypatch):
    from vidgrab.ui import app as appmod

    monkeypatch.setattr(appmod, "_config_dir", lambda: tmp_path)
    listing = tmp_path / "links.txt"
    listing.write_text("# playlist\nhttps://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb\n"
                       "https://youtu.be/aaaaaaaaaaa\n", encoding="utf-8")
    win = appmod.VidGrabWindow()
    monkeypatch.setattr(win, "pick_file", lambda *_a: str(listing))
    win._import_links()
    assert win._links() == ["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"]
    # a file without links changes nothing and tells the user
    empty = tmp_path / "empty.txt"
    empty.write_text("nothing here", encoding="utf-8")
    told = []
    monkeypatch.setattr(win, "pick_file", lambda *_a: str(empty))
    monkeypatch.setattr(appmod.QMessageBox, "information", staticmethod(lambda *a: told.append(a)))
    win._import_links()
    assert told and len(win._links()) == 2
    win.close()

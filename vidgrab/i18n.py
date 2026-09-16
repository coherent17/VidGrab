"""VidGrab internationalisation — English, Traditional Chinese, Japanese, Korean."""

from __future__ import annotations

from collections.abc import Callable

LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "繁體中文",
    "ja": "日本語",
    "ko": "한국어",
}

_Translator = Callable[..., str]


def _fmt(text: str, kw: dict[str, object]) -> str:
    try:
        return text.format(**kw)
    except (KeyError, IndexError):
        return text


# ── translation table ───────────────────────────────────────────────────────
# Keys are the English source strings (used as lookup key).
# Values: {"en": ..., "zh": ..., "ja": ..., "ko": ...}.
# {…} placeholders are preserved and passed through via str.format().

TRANS: dict[str, dict[str, str]] = {
    # ── sidebar ──
    "Download":        {"en": "Download",        "zh": "下載",        "ja": "ダウンロード",        "ko": "다운로드"},
    "Edit":            {"en": "Edit",            "zh": "編輯",        "ja": "編集",                "ko": "편집"},
    "Settings":        {"en": "Settings",        "zh": "設定",        "ja": "設定",                "ko": "설정"},
    # ── header ──
    "☾ Dark":          {"en": "☾ Dark",          "zh": "☾ 深色",      "ja": "☾ ダーク",            "ko": "☾ 다크"},
    "☀ Light":         {"en": "☀ Light",         "zh": "☀ 淺色",      "ja": "☀ ライト",            "ko": "☀ 라이트"},
    # ── download page cards ──
    "SOURCE":          {"en": "SOURCE",          "zh": "來源",        "ja": "ソース",              "ko": "소스"},
    "FORMAT":          {"en": "FORMAT",          "zh": "格式",        "ja": "形式",                "ko": "형식"},
    "FLIP":            {"en": "FLIP",            "zh": "翻轉",        "ja": "反転",                "ko": "반전"},
    "SPEED":           {"en": "SPEED",           "zh": "速度",        "ja": "速度",                "ko": "속도"},
    "TRIM":            {"en": "TRIM",            "zh": "裁剪",        "ja": "トリミング",          "ko": "자르기"},
    "SAVE TO":         {"en": "SAVE TO",         "zh": "儲存至",      "ja": "保存先",              "ko": "저장 위치"},
    # ── inputs / checkboxes ──
    "Paste a YouTube link…":        {"en": "Paste a YouTube link…",        "zh": "貼上 YouTube 連結…",        "ja": "YouTube リンクを貼り付け…",        "ko": "YouTube 링크를 붙여넣기…"},
    "Choose a local video or audio file…": {"en": "Choose a local video or audio file…", "zh": "選擇本地影片或音訊檔案…", "ja": "ローカルの動画・音声ファイルを選択…", "ko": "로컬 동영상/오디오 파일을 선택…"},
    "Horizontal":      {"en": "Horizontal",      "zh": "水平",        "ja": "水平",                "ko": "가로"},
    "Vertical":        {"en": "Vertical",        "zh": "垂直",        "ja": "垂直",                "ko": "세로"},
    "MP4 (video)":     {"en": "MP4 (video)",     "zh": "MP4 (影片)",  "ja": "MP4（動画）",          "ko": "MP4 (동영상)"},
    "MP3 (audio)":     {"en": "MP3 (audio)",     "zh": "MP3 (音訊)",  "ja": "MP3（音声）",          "ko": "MP3 (오디오)"},
    "Quality:":        {"en": "Quality:",        "zh": "品質:",       "ja": "品質:",               "ko": "품질:"},
    "Best available":  {"en": "Best available",  "zh": "最佳可用",    "ja": "最高品質",            "ko": "최상의 품질"},
    "▶ Preview":       {"en": "▶ Preview",       "zh": "▶ 預覽",      "ja": "▶ プレビュー",        "ko": "▶ 미리보기"},
    "Preview":         {"en": "Preview",         "zh": "預覽",        "ja": "プレビュー",          "ko": "미리보기"},
    "ffplay not found": {"en": "ffplay not found", "zh": "找不到 ffplay", "ja": "ffplay が見つかりません", "ko": "ffplay를 찾을 수 없음"},
    "Install ffmpeg (which includes ffplay) or rebuild with an embedded copy to preview clips.": {
        "en": "Install ffmpeg (which includes ffplay) or rebuild with an embedded copy to preview clips.",
        "zh": "請安裝 ffmpeg（內含 ffplay）或使用內嵌版本重建，以便預覽片段。",
        "ja": "ffplay を含む ffmpeg をインストールするか、埋め込み版で再ビルドしてプレビューしてください。",
        "ko": "클립을 미리보려면 ffplay를 포함한 ffmpeg을 설치하거나 내장 버전으로 다시 빌드하세요.",
    },
    "Start:":          {"en": "Start:",          "zh": "開始:",       "ja": "開始:",               "ko": "시작:"},
    "End:":            {"en": "End:",            "zh": "結束:",       "ja": "終了:",               "ko": "종료:"},
    "Paste":           {"en": "Paste",           "zh": "貼上",        "ja": "貼り付け",            "ko": "붙여넣기"},
    "Browse…":         {"en": "Browse…",         "zh": "瀏覽…",       "ja": "参照…",               "ko": "찾아보기…"},
    "Clear":           {"en": "Clear",           "zh": "清除",        "ja": "クリア",              "ko": "지우기"},
    # ── settings page ──
    "APPEARANCE":      {"en": "APPEARANCE",      "zh": "外觀",        "ja": "外観",                "ko": "모양"},
    "Theme:":          {"en": "Theme:",          "zh": "主題:",       "ja": "テーマ:",             "ko": "테마:"},
    "Language:":       {"en": "Language:",       "zh": "語言:",       "ja": "言語:",               "ko": "언어:"},
    "ABOUT":           {"en": "ABOUT",           "zh": "關於",        "ja": "情報",                "ko": "정보"},
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
        "ja": (
            "<b>VidGrab {ver}</b><br><br>"
            "YouTube の動画をダウンロード（MP4 / MP3）、またはローカルファイルを開いて"
            "反転・トリミングできます。<br><br>"
            "Python、PySide6、yt-dlp、ffmpeg で制作。<br>"
            "MIT ライセンス — 自由に使用・改変できます。"
        ),
        "ko": (
            "<b>VidGrab {ver}</b><br><br>"
            "YouTube 동영상을 다운로드(MP4 / MP3)하거나 로컬 파일을 열어 "
            "반전·자르기를 할 수 있습니다.<br><br>"
            "Python, PySide6, yt-dlp, ffmpeg으로 제작되었습니다.<br>"
            "MIT 라이선스 — 자유롭게 사용·수정할 수 있습니다."
        ),
    },
    # ── about dialog ──
    "about_title": {
        "en": "About VidGrab",
        "zh": "關於 VidGrab",
        "ja": "VidGrab について",
        "ko": "VidGrab 정보",
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
        "ja": (
            "<h3>VidGrab {ver}</h3>"
            "<p>YouTube の動画（MP4 / MP3）をダウンロード、またはローカルファイルを"
            "反転・トリミングできます。</p>"
            "<p>Python、PySide6、yt-dlp、ffmpeg で制作。<br>"
            "MIT ライセンス — 自由に使用・改変できます。</p>"
        ),
        "ko": (
            "<h3>VidGrab {ver}</h3>"
            "<p>YouTube 동영상(MP4 / MP3)을 다운로드하거나 로컬 파일을 "
            "반전·자르기할 수 있습니다.</p>"
            "<p>Python, PySide6, yt-dlp, ffmpeg으로 제작되었습니다.<br>"
            "MIT 라이선스 — 자유롭게 사용·수정할 수 있습니다.</p>"
        ),
    },
    # ── action buttons ──
    "⬇  Download":     {"en": "⬇  Download",     "zh": "⬇  下載",     "ja": "⬇  ダウンロード",     "ko": "⬇  다운로드"},
    "✂  Process":      {"en": "✂  Process",      "zh": "✂  處理",     "ja": "✂  処理",            "ko": "✂  처리"},
    "⬇  Downloading…": {"en": "⬇  Downloading…", "zh": "⬇  下載中…", "ja": "⬇  ダウンロード中…", "ko": "⬇  다운로드 중…"},
    "✂  Processing…":  {"en": "✂  Processing…",  "zh": "✂  處理中…", "ja": "✂  処理中…",         "ko": "✂  처리 중…"},
    # ── status bar ──
    "checking…":       {"en": "checking…",       "zh": "檢查中…",     "ja": "確認中…",            "ko": "확인 중…"},
    "Online":          {"en": "Online",          "zh": "已連線",      "ja": "オンライン",          "ko": "온라인"},
    "Offline":         {"en": "Offline",         "zh": "離線",        "ja": "オフライン",          "ko": "오프라인"},
    "ffmpeg: embedded": {"en": "ffmpeg: embedded", "zh": "ffmpeg: 內建", "ja": "ffmpeg: 内蔵",     "ko": "ffmpeg: 내장"},
    "ffmpeg: not found": {"en": "ffmpeg: not found", "zh": "ffmpeg: 未找到", "ja": "ffmpeg: 見つかりません", "ko": "ffmpeg: 찾을 수 없음"},
    "ffmpeg: {name}":  {"en": "ffmpeg: {name}",  "zh": "ffmpeg: {name}", "ja": "ffmpeg: {name}",   "ko": "ffmpeg: {name}"},
    # ── log header / progress ──
    "LOG":             {"en": "LOG",             "zh": "記錄",        "ja": "ログ",                "ko": "로그"},
    "Ready":           {"en": "Ready",           "zh": "就緒",        "ja": "準備完了",            "ko": "준비됨"},
    "Done":            {"en": "Done",            "zh": "完成",        "ja": "完了",                "ko": "완료"},
    "Failed":          {"en": "Failed",          "zh": "失敗",        "ja": "失敗",                "ko": "실패"},
    # ── dialogs ──
    "Missing URL":     {"en": "Missing URL",     "zh": "未提供網址",  "ja": "URL がありません",    "ko": "URL 누락"},
    "Please paste a YouTube link.": {
        "en": "Please paste a YouTube link.",
        "zh": "請貼上 YouTube 連結。",
        "ja": "YouTube リンクを貼り付けてください。",
        "ko": "YouTube 링크를 붙여넣어 주세요.",
    },
    "No internet":     {"en": "No internet",     "zh": "無網路連線",  "ja": "ネットワークなし",    "ko": "네트워크 없음"},
    "You appear to be offline.\nVidGrab needs a live connection.": {
        "en": "You appear to be offline.\nVidGrab needs a live connection.",
        "zh": "目前無法連線。\nVidGrab 需要網路連線。",
        "ja": "現在オフラインです。\nVidGrab にはネットワーク接続が必要です。",
        "ko": "현재 오프라인 상태입니다.\nVidGrab에는 네트워크 연결이 필요합니다.",
    },
    "ffmpeg required":  {"en": "ffmpeg required",  "zh": "需要 ffmpeg",  "ja": "ffmpeg が必要です",  "ko": "ffmpeg 필요"},
    "Downloads need ffmpeg for MP3 and most MP4 merges. "
    "Install ffmpeg or rebuild with an embedded copy.": {
        "en": "Downloads need ffmpeg for MP3 and most MP4 merges. "
              "Install ffmpeg or rebuild with an embedded copy.",
        "zh": "MP3 與大部分 MP4 合併下載需要 ffmpeg。\n請安裝 ffmpeg 或使用內建版本。",
        "ja": "MP3 および大半の MP4 結合には ffmpeg が必要です。\nffmpeg をインストールするか、埋め込み版で再ビルドしてください。",
        "ko": "MP3 및 대부분의 MP4 병합에는 ffmpeg이 필요합니다.\nffmpeg을 설치하거나 내장 버전으로 다시 빌드하세요.",
    },
    "Processing local files requires ffmpeg. "
    "Install ffmpeg or rebuild with an embedded copy.": {
        "en": "Processing local files requires ffmpeg. "
              "Install ffmpeg or rebuild with an embedded copy.",
        "zh": "處理本地檔案需要 ffmpeg。\n請安裝 ffmpeg 或使用內建版本。",
        "ja": "ローカルファイルの処理には ffmpeg が必要です。\nffmpeg をインストールするか、埋め込み版で再ビルドしてください。",
        "ko": "로컬 파일 처리에는 ffmpeg이 필요합니다.\nffmpeg을 설치하거나 내장 버전으로 다시 빌드하세요.",
    },
    "No file":         {"en": "No file",         "zh": "未選擇檔案",  "ja": "ファイルなし",        "ko": "파일 없음"},
    "Please select a local media file.": {
        "en": "Please select a local media file.",
        "zh": "請選擇一個本地媒體檔案。",
        "ja": "ローカルのメディアファイルを選択してください。",
        "ko": "로컬 미디어 파일을 선택해 주세요.",
    },
    "File not found":  {"en": "File not found",  "zh": "找不到檔案",  "ja": "ファイルが見つかりません", "ko": "파일을 찾을 수 없음"},
    "The file does not exist:\n{path}": {
        "en": "The file does not exist:\n{path}",
        "zh": "檔案不存在:\n{path}",
        "ja": "ファイルが存在しません:\n{path}",
        "ko": "파일이 존재하지 않습니다:\n{path}",
    },
    "Success":         {"en": "Success",         "zh": "成功",        "ja": "成功",                "ko": "성공"},
    "Saved to:\n{paths}": {
        "en": "Saved to:\n{paths}",
        "zh": "已儲存至:\n{paths}",
        "ja": "保存先:\n{paths}",
        "ko": "저장 위치:\n{paths}",
    },
    "Something went wrong": {
        "en": "Something went wrong",
        "zh": "發生錯誤",
        "ja": "エラーが発生しました",
        "ko": "문제가 발생했습니다",
    },
    "Task in progress": {
        "en": "Task in progress",
        "zh": "任務執行中",
        "ja": "タスク実行中",
        "ko": "작업 진행 중",
    },
    "A download or processing task is still running.\n"
    "Please wait for it to complete before closing.": {
        "en": "A download or processing task is still running.\n"
              "Please wait for it to complete before closing.",
        "zh": "下載或處理任務仍在執行中。\n請等待完成後再關閉。",
        "ja": "ダウンロードまたは処理タスクが実行中です。\n完了するまでお待ちください。",
        "ko": "다운로드 또는 처리 작업이 실행 중입니다.\n완료될 때까지 기다려 주세요.",
    },
    # ── tooltips ──
    "tooltip_switch_theme": {
        "en": "Switch between dark and light theme",
        "zh": "切換深色與淺色主題",
        "ja": "ダークテーマとライトテーマを切り替え",
        "ko": "다크/라이트 테마 전환",
    },
    "tooltip_page_download": {
        "en": "Download a video from YouTube",
        "zh": "從 YouTube 下載影片",
        "ja": "YouTube から動画をダウンロード",
        "ko": "YouTube에서 동영상 다운로드",
    },
    "tooltip_page_edit": {
        "en": "Trim or flip a local media file",
        "zh": "裁剪或翻轉本地媒體檔案",
        "ja": "ローカルファイルをトリミング・反転",
        "ko": "로컬 미디어 자르기/반전",
    },
    "tooltip_page_settings": {
        "en": "Theme, language and about",
        "zh": "主題、語言與關於",
        "ja": "テーマ・言語・情報",
        "ko": "테마, 언어, 정보",
    },
    "tooltip_paste": {
        "en": "Paste the URL from the clipboard (Ctrl+V)",
        "zh": "從剪貼簿貼上網址（Ctrl+V）",
        "ja": "クリップボードから URL を貼り付け（Ctrl+V）",
        "ko": "클립보드에서 URL 붙여넣기(Ctrl+V)",
    },
    "tooltip_browse_out": {
        "en": "Choose the output folder",
        "zh": "選擇輸出資料夾",
        "ja": "出力フォルダを選択",
        "ko": "출력 폴더 선택",
    },
    "tooltip_browse_file": {
        "en": "Select a local media file",
        "zh": "選擇本地媒體檔案",
        "ja": "ローカルのメディアファイルを選択",
        "ko": "로컬 미디어 파일 선택",
    },
    "tooltip_clear": {
        "en": "Clear the log (Ctrl+L)",
        "zh": "清除記錄（Ctrl+L）",
        "ja": "ログをクリア（Ctrl+L）",
        "ko": "로그 지우기(Ctrl+L)",
    },
    "tooltip_action_download": {
        "en": "Start downloading",
        "zh": "開始下載",
        "ja": "ダウンロードを開始",
        "ko": "다운로드 시작",
    },
    "tooltip_action_edit": {
        "en": "Start processing",
        "zh": "開始處理",
        "ja": "処理を開始",
        "ko": "처리 시작",
    },
}

# ── downloader messages ─────────────────────────────────────────────────────
# The key is the exact English format-string template.
TRANS.update({
    "Trimming…":       {"en": "Trimming…",       "zh": "裁剪中…",     "ja": "トリミング中…",       "ko": "자르는 중…"},
    "ffmpeg failed to process the file (exit code {code}).": {
        "en": "ffmpeg failed to process the file (exit code {code}).",
        "zh": "ffmpeg 處理檔案失敗（結束代碼 {code}）。",
        "ja": "ffmpeg がファイルの処理に失敗しました（終了コード {code}）。",
        "ko": "ffmpeg이 파일 처리에 실패했습니다(종료 코드 {code}).",
    },
    'Invalid start time "{t}". '
    "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).": {
        "en": 'Invalid start time "{t}". '
              "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).",
        "zh": '無效的開始時間「{t}」。'
              "請輸入秒數（90）、M:SS（1:30）或 H:MM:SS（1:02:03）。",
        "ja": '開始時間「{t}」が無効です。'
              "秒（90）、M:SS（1:30）、H:MM:SS（1:02:03）で入力してください。",
        "ko": '"{t}" 시작 시간이 잘못되었습니다.'
              "초(90), M:SS(1:30) 또는 H:MM:SS(1:02:03) 형식으로 입력하세요.",
    },
    'Invalid end time "{t}". '
    "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).": {
        "en": 'Invalid end time "{t}". '
              "Use seconds (90), M:SS (1:30) or H:MM:SS (1:02:03).",
        "zh": '無效的結束時間「{t}」。'
              "請輸入秒數（90）、M:SS（1:30）或 H:MM:SS（1:02:03）。",
        "ja": '終了時間「{t}」が無効です。'
              "秒（90）、M:SS（1:30）、H:MM:SS（1:02:03）で入力してください。",
        "ko": '"{t}" 종료 시간이 잘못되었습니다.'
              "초(90), M:SS(1:30) 또는 H:MM:SS(1:02:03) 형식으로 입력하세요.",
    },
    "Trim end time must be after the start time. "
    "Got start {s}s, end {e}s.": {
        "en": "Trim end time must be after the start time. "
              "Got start {s}s, end {e}s.",
        "zh": "裁剪結束時間必須晚於開始時間。"
              "開始 {s} 秒，結束 {e} 秒。",
        "ja": "終了時間は開始時間より後である必要があります。"
              "開始 {s} 秒、終了 {e} 秒。",
        "ko": "종료 시간은 시작 시간보다 뒤여야 합니다. "
              "시작 {s}초, 종료 {e}초.",
    },
    "Extracting audio…": {"en": "Extracting audio…", "zh": "正在提取音訊…", "ja": "音声を抽出中…", "ko": "오디오 추출 중…"},
    "Speed must be between {lo}x and {hi}x.": {
        "en": "Speed must be between {lo}x and {hi}x.",
        "zh": "速度必須介於 {lo}x 與 {hi}x 之間。",
        "ja": "速度は {lo}x〜{hi}x の範囲で指定してください。",
        "ko": "속도는 {lo}배에서 {hi}배 사이여야 합니다.",
    },
    "Saved: {name}":     {"en": "Saved: {name}",     "zh": "已儲存: {name}",     "ja": "保存しました: {name}",     "ko": "저장됨: {name}"},
    "Complete":          {"en": "Complete",          "zh": "完成",               "ja": "完了",                       "ko": "완료"},
    "Copied: {name}":    {"en": "Copied: {name}",    "zh": "已複製: {name}",     "ja": "コピーしました: {name}",     "ko": "복사됨: {name}"},
    "No URL provided.":  {"en": "No URL provided.",  "zh": "未提供連結。",       "ja": "URL が指定されていません。",  "ko": "URL이 제공되지 않았습니다."},
    "Downloading… {pct:.1f}%": {
        "en": "Downloading… {pct:.1f}%", "zh": "下載中… {pct:.1f}%",
        "ja": "ダウンロード中… {pct:.1f}%", "ko": "다운로드 중… {pct:.1f}%",
    },
    "Downloading…":      {"en": "Downloading…",      "zh": "下載中…",   "ja": "ダウンロード中…",   "ko": "다운로드 중…"},
    "Processing…":       {"en": "Processing…",       "zh": "處理中…",   "ja": "処理中…",          "ko": "처리 중…"},
    "ffmpeg is required for MP3 downloads. "
    "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
    "or install ffmpeg and add it to PATH.": {
        "en": "ffmpeg is required for MP3 downloads. "
              "Place ffmpeg.exe in an 'ffmpeg' folder next to the app, "
              "or install ffmpeg and add it to PATH.",
        "zh": "MP3 下載需要 ffmpeg。請將 ffmpeg 放入應用程式旁的 'ffmpeg' 資料夾，"
              "或安裝 ffmpeg 並加入 PATH。",
        "ja": "MP3 ダウンロードには ffmpeg が必要です。アプリの隣の 'ffmpeg' フォルダに ffmpeg.exe を置くか、"
              "ffmpeg をインストールして PATH に追加してください。",
        "ko": "MP3 다운로드에는 ffmpeg이 필요합니다. 앱 옆 'ffmpeg' 폴더에 ffmpeg.exe를 넣거나 "
              "ffmpeg을 설치하고 PATH에 추가하세요.",
    },
    "ffmpeg is required to trim downloads.": {
        "en": "ffmpeg is required to trim downloads.",
        "zh": "裁剪下載需要 ffmpeg。",
        "ja": "ダウンロードのトリミングには ffmpeg が必要です。",
        "ko": "다운로드 자르기에는 ffmpeg이 필요합니다.",
    },
    "Could not fetch video information.": {
        "en": "Could not fetch video information.",
        "zh": "無法取得影片資訊。",
        "ja": "動画情報を取得できませんでした。",
        "ko": "동영상 정보를 가져올 수 없습니다.",
    },
    "Section download unavailable ({exc}); downloading in full.": {
        "en": "Section download unavailable ({exc}); downloading in full.",
        "zh": "片段下載不可用（{exc}），改為下載完整檔案。",
        "ja": "部分ダウンロードが利用できません（{exc}）。全編をダウンロードします。",
        "ko": "구간 다운로드를 사용할 수 없습니다({exc}). 전체를 다운로드합니다.",
    },
    "Download finished but output file was not found.": {
        "en": "Download finished but output file was not found.",
        "zh": "下載完成但找不到輸出檔案。",
        "ja": "ダウンロードは完了しましたが、出力ファイルが見つかりません。",
        "ko": "다운로드는 완료되었지만 출력 파일을 찾을 수 없습니다.",
    },
    "ffmpeg failed to extract MP3 audio": {
        "en": "ffmpeg failed to extract MP3 audio",
        "zh": "ffmpeg 提取 MP3 音訊失敗",
        "ja": "ffmpeg が MP3 音声の抽出に失敗しました",
        "ko": "ffmpeg이 MP3 오디오 추출에 실패했습니다",
    },
    "File not found: {src}": {
        "en": "File not found: {src}",
        "zh": "找不到檔案: {src}",
        "ja": "ファイルが見つかりません: {src}",
        "ko": "파일을 찾을 수 없음: {src}",
    },
    "ffmpeg is required to extract MP3 audio.": {
        "en": "ffmpeg is required to extract MP3 audio.",
        "zh": "提取 MP3 音訊需要 ffmpeg。",
        "ja": "MP3 音声の抽出には ffmpeg が必要です。",
        "ko": "MP3 오디오 추출에는 ffmpeg이 필요합니다.",
    },
    "ffmpeg is required to process local files. "
    "Install ffmpeg or place it next to the app.": {
        "en": "ffmpeg is required to process local files. "
              "Install ffmpeg or place it next to the app.",
        "zh": "處理本地檔案需要 ffmpeg。"
              "請安裝 ffmpeg 或將其放置於應用程式旁。",
        "ja": "ローカルファイルの処理には ffmpeg が必要です。ffmpeg をインストールするか、アプリの隣に置いてください。",
        "ko": "로컬 파일 처리에는 ffmpeg이 필요합니다. ffmpeg을 설치하거나 앱 옆에 두세요.",
    },
    "{prefix} (exit code {code}).": {
        "en": "{prefix} (exit code {code}).",
        "zh": "{prefix}（結束代碼 {code}）。",
        "ja": "{prefix}（終了コード {code}）。",
        "ko": "{prefix}(종료 코드 {code}).",
    },
    "ffmpeg failed":     {"en": "ffmpeg failed",     "zh": "ffmpeg 失敗",     "ja": "ffmpeg エラー",     "ko": "ffmpeg 실패"},
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
"""Qt-free text of the Help page: how-to guides and a FAQ, in both UI languages.

Each topic is ``(id, section, page, {lang: title}, {lang: html})``. *page* is
the page (0 Download, 1 Studio, 2 Settings) the "Open it" button jumps to, or
None. Bodies use only <p>, <ol>, <ul>, <li>, <b> and <i>."""
from __future__ import annotations

SECTIONS: dict[str, dict[str, str]] = {
    "start": {"en": "Getting started", "zh": "開始使用"},
    "download": {"en": "Download", "zh": "下載"},
    "studio": {"en": "Studio", "zh": "Studio 剪輯"},
    "captions": {"en": "Captions and effects", "zh": "字幕與特效"},
    "faq": {"en": "Questions and fixes", "zh": "常見問題"},
}

# one line under each section's tile on the Help home
BLURBS: dict[str, dict[str, str]] = {
    "start": {"en": "A two-minute tour and your first download", "zh": "兩分鐘導覽與第一次下載"},
    "download": {"en": "Playlists, trimming, sponsors and logins", "zh": "播放清單、裁切、業配與登入"},
    "studio": {"en": "Build videos, Shorts, music and cuts", "zh": "剪輯影片、短影片、音樂與剪裁"},
    "captions": {"en": "Auto captions, styles and picture effects", "zh": "自動字幕、樣式與畫面特效"},
    "faq": {"en": "Fixes, privacy and keyboard shortcuts", "zh": "問題排解、隱私與快速鍵"},
}

# shown as chips on the Help home
FEATURED = ["first_video", "studio_basics", "shorts", "captions_auto", "faq_shortcuts"]

TOPICS: list[tuple[str, str, int | None, dict[str, str], dict[str, str]]] = [
    ("welcome", "start", None,
     {"en": "What VidGrab does", "zh": "VidGrab 可以做什麼"},
     {"en": "<p>VidGrab has three pages, chosen in the bar on the left.</p>"
            "<ul><li><b>Download</b> saves videos, playlists and music from YouTube and other sites "
            "as MP4 or MP3, optionally trimmed, sped up or flipped.</li>"
            "<li><b>Studio</b> is a small video editor: join clips, add subtitles, music and pictures, "
            "then render one file.</li>"
            "<li><b>Settings</b> holds the look, language, download defaults and hardware options.</li></ul>"
            "<p>Press <b>F1</b> at any time to come back to this Help page.</p>",
      "zh": "<p>VidGrab 有三個頁面，由左側的欄位切換。</p>"
            "<ul><li><b>下載</b>：把 YouTube 等網站的影片、播放清單和音樂存成 MP4 或 MP3，"
            "可同時裁切、變速或翻轉。</li>"
            "<li><b>Studio</b>：簡易的影片剪輯器，可接合片段、加入字幕、音樂與圖片，再輸出成一個檔案。</li>"
            "<li><b>設定</b>：外觀、語言、下載預設值與硬體選項。</li></ul>"
            "<p>隨時按 <b>F1</b> 即可回到這個說明頁。</p>"}),
    ("first_video", "start", 0,
     {"en": "Your first download", "zh": "第一次下載"},
     {"en": "<ol><li>Copy a video link and press <b>Paste</b> (or Ctrl+V).</li>"
            "<li>Pick <b>MP4</b> for video or <b>MP3</b> for audio, and a quality.</li>"
            "<li>Press <b>Download</b>. The file appears in the Downloads list below, with buttons to open "
            "it or send it to the Studio.</li></ol>"
            "<p>Typing words instead of a link turns the button into <b>Search</b> and lists YouTube results "
            "you can tick.</p>",
      "zh": "<ol><li>複製影片連結，按<b>貼上</b>（或 Ctrl+V）。</li>"
            "<li>選擇 <b>MP4</b>（影片）或 <b>MP3</b>（音訊），以及畫質。</li>"
            "<li>按<b>下載</b>。檔案會出現在下方的下載清單，可直接開啟或傳送到 Studio。</li></ol>"
            "<p>輸入文字而不是連結時，按鈕會變成<b>搜尋</b>，列出可勾選的 YouTube 結果。</p>"}),
    ("playlists", "download", 0,
     {"en": "Playlists, channels and many links", "zh": "播放清單、頻道與多個連結"},
     {"en": "<p>Paste a playlist or channel link and VidGrab downloads every video in it. You can also put "
            "several links in the box, one per line.</p>"
            "<p><b>Import…</b> next to Paste reads links from a text file (one per line; lines starting with "
            "<b>#</b> are ignored and repeats are dropped).</p>"
            "<p>Turn on <i>skip already downloaded</i> in Settings → Downloads to fetch only new videos "
            "next time.</p>",
      "zh": "<p>貼上播放清單或頻道連結，VidGrab 會下載其中所有影片。也可以在輸入框放入多個連結，每行一個。</p>"
            "<p>貼上旁邊的<b>匯入…</b>可從文字檔讀取連結（每行一個；以 <b>#</b> 開頭的行會略過，重複的會刪除）。</p>"
            "<p>在 設定 → 下載 開啟「略過已下載」，下次只會抓新的影片。</p>"}),
    ("trim_speed", "download", 0,
     {"en": "Trim, speed and flip while downloading", "zh": "下載時裁切、變速與翻轉"},
     {"en": "<p>In the options card, <b>Trim</b> takes a start and end such as <b>1:30</b> or <b>90</b>. "
            "<b>Speed</b> changes how fast it plays, and <b>Flip</b> mirrors it.</p>"
            "<p>VidGrab always downloads the whole video and cuts it on your computer, because YouTube "
            "often refuses partial downloads.</p>",
      "zh": "<p>在選項卡片中，<b>裁切</b>可輸入開始與結束時間，例如 <b>1:30</b> 或 <b>90</b>。"
            "<b>速度</b>調整播放快慢，<b>翻轉</b>可做鏡像。</p>"
            "<p>VidGrab 一律先下載完整影片，再在你的電腦上剪裁，因為 YouTube 常拒絕只下載一部分。</p>"}),
    ("sponsors", "download", 2,
     {"en": "Skip sponsor segments (SponsorBlock)", "zh": "跳過業配片段（SponsorBlock）"},
     {"en": "<p>In Settings → Downloads, turn on <b>Cut sponsor segments</b>. Sponsor reads, self-promotion "
            "and “like and subscribe” reminders that the community has marked are cut out of the file. "
            "It is off by default, and live streams are left alone.</p>",
      "zh": "<p>在 設定 → 下載 開啟<b>剪除業配片段</b>。社群標記的業配、自我宣傳與「訂閱按讚」提醒會從檔案中剪掉。"
            "預設關閉，直播不會處理。</p>"}),
    ("login", "download", 2,
     {"en": "Age-restricted or members-only videos", "zh": "年齡限制或會員限定影片"},
     {"en": "<p>In Settings → Downloads, choose <b>Use login of</b> and pick the browser where you are signed "
            "in to YouTube. VidGrab reads that login for the download; nothing is sent anywhere else.</p>"
            "<p>If it says it could not read the login, close that browser and try again.</p>",
      "zh": "<p>在 設定 → 下載 選擇<b>使用其登入狀態</b>，並選擇你已登入 YouTube 的瀏覽器。"
            "VidGrab 只用它來下載，不會傳到其他地方。</p>"
            "<p>若顯示讀取登入失敗，請先關閉該瀏覽器再試一次。</p>"}),
    ("studio_basics", "studio", 1,
     {"en": "Build a video in the Studio", "zh": "在 Studio 製作影片"},
     {"en": "<ol><li>Add clips with <b>Add</b>, or press <b>Send to Studio</b> on a finished download. "
            "You can also drop files on the window.</li>"
            "<li>Drag a block on the timeline up or down to reorder it. Drag its edges to trim.</li>"
            "<li>Move the playhead and press <b>Split</b> to cut a clip in two.</li>"
            "<li>Pick a size and quality in the project panel, then press <b>Render</b>.</li></ol>"
            "<p>Everything can be undone with Ctrl+Z. Save the project to keep working later; "
            "VidGrab also keeps a recovery copy and offers it after a crash.</p>",
      "zh": "<ol><li>用<b>新增</b>加入片段，或在已完成的下載按<b>傳送到 Studio</b>。</li>"
            "<li>在時間軸上下拖曳區塊可調整順序，拖曳邊緣可裁切。</li>"
            "<li>移動播放頭並按<b>分割</b>，把片段切成兩段。</li>"
            "<li>在專案面板選擇尺寸與畫質，再按<b>輸出</b>。</li></ol>"
            "<p>所有操作都可以用 Ctrl+Z 復原。儲存專案以便日後繼續；VidGrab 也會保留復原檔，當機後會詢問是否還原。</p>"}),
    ("shorts", "studio", 1,
     {"en": "Make a vertical Short", "zh": "製作直式短影片"},
     {"en": "<ol><li>Pick the <b>Shorts / vertical</b> size in the project panel.</li>"
            "<li>Select the clip and, in its frame settings, choose <b>Fill</b> so the picture covers the "
            "screen.</li>"
            "<li>Press <b>Follow the face</b> so the crop keeps the speaker in view. The first use downloads "
            "a 1.2 MB face finder after asking you.</li>"
            "<li>Add captions (see “Automatic captions”) and render.</li></ol>"
            "<p>Follow the face tracks the main face only. You can still drag the picture afterwards.</p>",
      "zh": "<ol><li>在專案面板選擇<b>短影片／直式</b>尺寸。</li>"
            "<li>選取片段，在畫面設定選擇<b>填滿</b>，讓畫面鋪滿螢幕。</li>"
            "<li>按<b>追蹤人臉</b>，裁切範圍會跟著說話的人移動。第一次使用時會先詢問，再下載 1.2 MB 的人臉偵測模型。</li>"
            "<li>加入字幕（見「自動字幕」）後輸出。</li></ol>"
            "<p>追蹤人臉只會跟隨最主要的一張臉，之後仍可手動拖曳畫面。</p>"}),
    ("silences", "studio", 1,
     {"en": "Cut out the pauses", "zh": "剪掉停頓"},
     {"en": "<p>Select a clip, open the <b>Trim</b> tab and press <b>Remove silences…</b>. Choose how quiet "
            "counts as a pause, review the preview strip, and apply. A little breathing room is kept around "
            "speech, and the whole thing is one undo step.</p>",
      "zh": "<p>選取片段，開啟<b>裁切</b>分頁並按<b>移除靜音…</b>。選擇多安靜才算停頓，確認預覽後套用。"
            "說話前後會保留一點空隙，整個動作只算一次復原。</p>"}),
    ("music", "studio", 1,
     {"en": "Background music and volume", "zh": "背景音樂與音量"},
     {"en": "<p>Press <b>Music…</b> or double-click the Music row to add a song. Each song has its own start, "
            "end, volume and fade, and you can add several; only the last one loops to fill the video.</p>"
            "<p>Choose <b>Audio only (MP3)</b> as the export format to make a music medley.</p>",
      "zh": "<p>按<b>音樂…</b>或在音樂列雙擊即可新增歌曲。每首歌都有自己的起訖、音量與淡入淡出，可加入多首；"
            "只有最後一首會循環到影片結束。</p>"
            "<p>輸出格式選<b>僅音訊（MP3）</b>即可製作音樂串燒。</p>"}),
    ("captions_auto", "captions", 1,
     {"en": "Automatic captions", "zh": "自動字幕"},
     {"en": "<ol><li>Press <b>Auto captions…</b> in the Studio.</li>"
            "<li>Choose the language and model size. The first run downloads the model (the dialog says how "
            "big) and everything after that works offline.</li>"
            "<li>Pick a <b>caption style</b>, for example <i>Word highlight</i> that lights each word as it is "
            "spoken.</li>"
            "<li>Press <b>Create captions</b>. Lines appear in the Subtitles row; click one to fix the text.</li></ol>"
            "<p>A graphics card speeds this up a lot. You can turn that off in Settings → Studio.</p>",
      "zh": "<ol><li>在 Studio 按<b>自動字幕…</b>。</li>"
            "<li>選擇語言與模型大小。第一次會下載模型（對話框會顯示大小），之後完全離線運作。</li>"
            "<li>選擇<b>字幕樣式</b>，例如<i>逐字亮起</i>，會在說到每個字時亮起。</li>"
            "<li>按<b>建立字幕</b>。字幕會出現在字幕列，點選即可修改文字。</li></ol>"
            "<p>有顯示卡時速度會快很多，可在 設定 → Studio 關閉。</p>"}),
    ("captions_style", "captions", 1,
     {"en": "Subtitle look and animation", "zh": "字幕外觀與動畫"},
     {"en": "<p>Select a subtitle and use its panel to change the font size, colour, box and position, "
            "or drag it right on the preview. <b>Own look</b> gives one line a different style from the rest.</p>"
            "<p>The animation list adds fade, pop, slide, typewriter, karaoke and word highlight. "
            "The ready-made text styles (title, lower third, quote) place a line for you.</p>",
      "zh": "<p>選取字幕後，可在面板調整字體大小、顏色、底框與位置，也可以直接在預覽中拖曳。"
            "<b>獨立外觀</b>可以讓單行字幕與其他行不同。</p>"
            "<p>動畫清單包含淡入淡出、彈出、滑入、打字機、卡拉 OK 與逐字亮起。"
            "現成的文字樣式（標題、下三分之一、引言）會自動擺好位置。</p>"}),
    ("effects", "captions", 1,
     {"en": "Colour looks, stabilise and green screen", "zh": "調色、防震與綠幕"},
     {"en": "<p>Select a clip and open its <b>Effects</b> tab.</p>"
            "<ul><li><b>Look</b>: one-click colour styles, plus sliders or your own .cube file.</li>"
            "<li><b>Stabilise</b> steadies shaky footage; <b>Clean up</b> and <b>Sharpen</b> improve the picture.</li>"
            "<li><b>Green screen</b> makes a colour see-through so a picture or video shows behind it.</li></ul>"
            "<p>The player shows colour changes live as an approximation; the rendered file is the exact result. "
            "Stabilise and sharpen show in the before / after pictures and in the render.</p>",
      "zh": "<p>選取片段並開啟<b>特效</b>分頁。</p>"
            "<ul><li><b>風格</b>：一鍵調色，也可使用滑桿或自己的 .cube 檔。</li>"
            "<li><b>防震</b>讓晃動的畫面穩定；<b>降噪</b>與<b>銳化</b>改善畫質。</li>"
            "<li><b>綠幕</b>可讓某個顏色變透明，後方顯示圖片或影片。</li></ul>"
            "<p>播放器即時顯示的顏色是近似效果，輸出的檔案才是精確結果。防震與銳化可在前後對照圖與輸出檔中看到。</p>"}),
    ("faq_ffmpeg", "faq", None,
     {"en": "It says ffmpeg is missing", "zh": "顯示找不到 ffmpeg"},
     {"en": "<p>The Windows and Linux downloads include ffmpeg. If you installed VidGrab with pip or on macOS, "
            "it offers to download ffmpeg once, and you can accept. After that trimming, MP3 and the "
            "Studio work.</p>",
      "zh": "<p>Windows 與 Linux 版本已內建 ffmpeg。若你是用 pip 或在 macOS 安裝，VidGrab 會詢問是否下載一次 ffmpeg，"
            "同意後裁切、MP3 與 Studio 都能正常使用。</p>"}),
    ("faq_403", "faq", 2,
     {"en": "A download fails or is only 360p", "zh": "下載失敗或只有 360p"},
     {"en": "<p>YouTube changes often. In Settings → Downloads press <b>Update yt-dlp</b>; the new version "
            "applies the next time you start VidGrab. Using a different network or turning off a VPN also "
            "helps with “403” and “not a bot” messages.</p>"
            "<p>For videos that need an account, see “Age-restricted or members-only videos”.</p>",
      "zh": "<p>YouTube 經常改版。到 設定 → 下載 按<b>更新 yt-dlp</b>，下次啟動時生效。"
            "遇到「403」或「不是機器人」訊息時，換個網路或關閉 VPN 也有幫助。</p>"
            "<p>需要帳號的影片請見「年齡限制或會員限定影片」。</p>"}),
    ("faq_slow", "faq", 2,
     {"en": "Rendering or captions are slow", "zh": "輸出或字幕很慢"},
     {"en": "<p>Settings → Studio has two switches that use your graphics card for rendering and for captions. "
            "Both fall back to the processor by themselves if the card fails. A smaller caption model and "
            "a lower export size are the other quick fixes.</p>",
      "zh": "<p>設定 → Studio 有兩個開關，可用顯示卡加速輸出與字幕；顯示卡失敗時會自動改用處理器。"
            "選用較小的字幕模型、降低輸出尺寸也能加快速度。</p>"}),
    ("faq_privacy", "faq", None,
     {"en": "What stays on my computer?", "zh": "哪些資料會留在我的電腦？"},
     {"en": "<p>Captions are made on your computer; no audio is uploaded. Your settings, history and "
            "recovery file are stored in the app's config folder. VidGrab contacts the network only to "
            "download, to fetch models or ffmpeg when you agree, and for a quiet yt-dlp version check "
            "that you can turn off in Settings.</p>",
      "zh": "<p>字幕在你的電腦上產生，不會上傳任何音訊。設定、歷史紀錄與復原檔存放在應用程式的設定資料夾。"
            "VidGrab 只會在下載、經你同意下載模型或 ffmpeg，以及安靜地檢查 yt-dlp 版本時連線，檢查可在設定中關閉。</p>"}),
    ("faq_shortcuts", "faq", None,
     {"en": "Keyboard shortcuts", "zh": "鍵盤快速鍵"},
     {"en": "<ul><li><b>F1</b> Help</li><li><b>Ctrl+V</b> paste a link (or Studio items)</li>"
            "<li><b>Ctrl+Z / Ctrl+Y</b> undo / redo in the Studio</li>"
            "<li><b>Ctrl+C / Ctrl+V / Ctrl+D</b> copy, paste at the playhead, duplicate</li>"
            "<li><b>Ctrl+0</b> fit the whole project in the timeline</li>"
            "<li>Hold <b>Shift</b> while trimming for fine steps</li></ul>",
      "zh": "<ul><li><b>F1</b> 說明</li><li><b>Ctrl+V</b> 貼上連結（或 Studio 項目）</li>"
            "<li><b>Ctrl+Z / Ctrl+Y</b> Studio 復原／重做</li>"
            "<li><b>Ctrl+C / Ctrl+V / Ctrl+D</b> 複製、貼到播放頭、複製一份</li>"
            "<li><b>Ctrl+0</b> 讓整個專案符合時間軸寬度</li>"
            "<li>裁切時按住 <b>Shift</b> 可微調</li></ul>"}),
]


def text_of(html: str) -> str:
    """The words of a body without its tags (for searching)."""
    out, tag = [], False
    for ch in html:
        if ch == "<":
            tag = True
            out.append(" ")
        elif ch == ">":
            tag = False
        elif not tag:
            out.append(ch)
    return "".join(out).lower()


def search(query: str, lang: str) -> list[str]:
    """Ids of the topics whose title or text contains every word of *query*
    (in order of the list; all of them for an empty query)."""
    words = query.lower().split()
    hits = []
    for tid, _sec, _page, title, body in TOPICS:
        hay = title[lang].lower() + " " + text_of(body[lang])
        if all(w in hay for w in words):
            hits.append(tid)
    return hits

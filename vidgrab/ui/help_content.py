"""Qt-free text of the Help page: how-to guides and a FAQ, in both UI languages.

Each topic is ``(id, section, page, {lang: title}, {lang: html})``. *page* is
the page ("download", "studio", "settings", …) the "Open it" button jumps to, or
None. Bodies use only <p>, <ol>, <ul>, <li>, <b> and <i>."""
from __future__ import annotations

from vidgrab.core.fuzzy import FuzzyIndex

SECTIONS: dict[str, dict[str, str]] = {
    "start": {"en": "Getting started", "zh": "開始使用"},
    "download": {"en": "Download", "zh": "下載"},
    "studio": {"en": "Studio", "zh": "Studio 剪輯"},
    "captions": {"en": "Captions and effects", "zh": "字幕與特效"},
    "more": {"en": "Library, tools and channels", "zh": "媒體庫、工具與頻道"},
    "faq": {"en": "Questions and fixes", "zh": "常見問題"},
}

# one line under each section's tile on the Help home
BLURBS: dict[str, dict[str, str]] = {
    "start": {"en": "A two-minute tour and your first download", "zh": "兩分鐘導覽與第一次下載"},
    "download": {"en": "Playlists, trimming, sponsors and logins", "zh": "播放清單、裁切、業配與登入"},
    "studio": {"en": "Build videos, Shorts, music and cuts", "zh": "剪輯影片、短影片、音樂與剪裁"},
    "captions": {"en": "Auto captions, styles and picture effects", "zh": "自動字幕、樣式與畫面特效"},
    "more": {"en": "Find files, shrink videos, follow channels", "zh": "找檔案、壓縮影片、追蹤頻道"},
    "faq": {"en": "Fixes, privacy and keyboard shortcuts", "zh": "問題排解、隱私與快速鍵"},
}

# shown as chips on the Help home
FEATURED = ["first_video", "studio_basics", "shorts", "captions_auto", "faq_shortcuts"]

TOPICS: list[tuple[str, str, str | None, dict[str, str], dict[str, str]]] = [
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
    ("first_video", "start", "download",
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
    ("playlists", "download", "download",
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
    ("trim_speed", "download", "download",
     {"en": "Trim, speed and flip while downloading", "zh": "下載時裁切、變速與翻轉"},
     {"en": "<p>In the options card, <b>Trim</b> takes a start and end such as <b>1:30</b> or <b>90</b>. "
            "<b>Speed</b> changes how fast it plays, and <b>Flip</b> mirrors it.</p>"
            "<p>VidGrab always downloads the whole video and cuts it on your computer, because YouTube "
            "often refuses partial downloads.</p>",
      "zh": "<p>在選項卡片中，<b>裁切</b>可輸入開始與結束時間，例如 <b>1:30</b> 或 <b>90</b>。"
            "<b>速度</b>調整播放快慢，<b>翻轉</b>可做鏡像。</p>"
            "<p>VidGrab 一律先下載完整影片，再在你的電腦上剪裁，因為 YouTube 常拒絕只下載一部分。</p>"}),
    ("sponsors", "download", "settings",
     {"en": "Skip sponsor segments (SponsorBlock)", "zh": "跳過業配片段（SponsorBlock）"},
     {"en": "<p>In Settings → Downloads, turn on <b>Cut sponsor segments</b>. Sponsor reads, self-promotion "
            "and “like and subscribe” reminders that the community has marked are cut out of the file. "
            "It is off by default, and live streams are left alone.</p>",
      "zh": "<p>在 設定 → 下載 開啟<b>剪除業配片段</b>。社群標記的業配、自我宣傳與「訂閱按讚」提醒會從檔案中剪掉。"
            "預設關閉，直播不會處理。</p>"}),
    ("login", "download", "settings",
     {"en": "Age-restricted or members-only videos", "zh": "年齡限制或會員限定影片"},
     {"en": "<p>In Settings → Downloads, choose <b>Use login of</b> and pick the browser where you are signed "
            "in to YouTube. VidGrab reads that login for the download; nothing is sent anywhere else.</p>"
            "<p>If it says it could not read the login, close that browser and try again.</p>",
      "zh": "<p>在 設定 → 下載 選擇<b>使用其登入狀態</b>，並選擇你已登入 YouTube 的瀏覽器。"
            "VidGrab 只用它來下載，不會傳到其他地方。</p>"
            "<p>若顯示讀取登入失敗，請先關閉該瀏覽器再試一次。</p>"}),
    ("studio_basics", "studio", "studio",
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
    ("shorts", "studio", "studio",
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
    ("silences", "studio", "studio",
     {"en": "Cut out the pauses", "zh": "剪掉停頓"},
     {"en": "<p>Select a clip, open the <b>Trim</b> tab and press <b>Remove silences…</b>. Choose how quiet "
            "counts as a pause, review the preview strip, and apply. A little breathing room is kept around "
            "speech, and the whole thing is one undo step.</p>",
      "zh": "<p>選取片段，開啟<b>裁切</b>分頁並按<b>移除靜音…</b>。選擇多安靜才算停頓，確認預覽後套用。"
            "說話前後會保留一點空隙，整個動作只算一次復原。</p>"}),
    ("music", "studio", "studio",
     {"en": "Background music and volume", "zh": "背景音樂與音量"},
     {"en": "<p>Press <b>Music…</b> or double-click the Music row to add a song. Each song has its own start, "
            "end, volume and fade, and you can add several; only the last one loops to fill the video.</p>"
            "<p>Choose <b>Audio only (MP3)</b> as the export format to make a music medley.</p>",
      "zh": "<p>按<b>音樂…</b>或在音樂列雙擊即可新增歌曲。每首歌都有自己的起訖、音量與淡入淡出，可加入多首；"
            "只有最後一首會循環到影片結束。</p>"
            "<p>輸出格式選<b>僅音訊（MP3）</b>即可製作音樂串燒。</p>"}),
    ("captions_auto", "captions", "studio",
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
    ("captions_style", "captions", "studio",
     {"en": "Subtitle look and animation", "zh": "字幕外觀與動畫"},
     {"en": "<p>Select a subtitle and use its panel to change the font size, colour, box and position, "
            "or drag it right on the preview. <b>Own look</b> gives one line a different style from the rest.</p>"
            "<p>The animation list adds fade, pop, slide, typewriter, karaoke and word highlight. "
            "The ready-made text styles (title, lower third, quote) place a line for you.</p>",
      "zh": "<p>選取字幕後，可在面板調整字體大小、顏色、底框與位置，也可以直接在預覽中拖曳。"
            "<b>獨立外觀</b>可以讓單行字幕與其他行不同。</p>"
            "<p>動畫清單包含淡入淡出、彈出、滑入、打字機、卡拉 OK 與逐字亮起。"
            "現成的文字樣式（標題、下三分之一、引言）會自動擺好位置。</p>"}),
    ("effects", "captions", "studio",
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
    ("library", "more", "library",
     {"en": "Find and reuse your files", "zh": "尋找並重複使用你的檔案"},
     {"en": "<p>The <b>Library</b> page lists every video, song and picture in your download folder, newest "
            "first, with a picture for each video.</p>"
            "<ol><li>Search by name, or filter by <b>Videos</b>, <b>Music</b> or <b>Pictures</b>.</li>"
            "<li>Click a file, then <b>Send to Studio</b> to edit it, <b>Compress / convert…</b> to open it in "
            "Tools, or <b>Show in folder</b>.</li>"
            "<li>Double-click a file to play it. <b>Delete</b> always asks first.</li></ol>"
            "<p>It shows the folder chosen in Settings, one level of sub-folders included.</p>",
      "zh": "<p><b>媒體庫</b>列出下載資料夾中所有的影片、音樂與圖片，最新的在最上面，影片會顯示縮圖。</p>"
            "<ol><li>可依名稱搜尋，或以<b>影片</b>、<b>音樂</b>、<b>圖片</b>篩選。</li>"
            "<li>選取檔案後，按<b>傳送到 Studio</b>編輯、<b>壓縮／轉檔…</b>在工具中開啟，或<b>在資料夾中顯示</b>。</li>"
            "<li>雙擊檔案即可播放。<b>刪除</b>一律會先詢問。</li></ol>"
            "<p>顯示的是設定中選擇的資料夾，包含一層子資料夾。</p>"}),
    ("studio_more_tools", "studio", "studio",
     {"en": "Blur boxes, stickers, zoom keyframes, beat cuts and background removal", "zh": "模糊方塊、貼圖、縮放關鍵影格、對拍剪輯與移除背景"},
     {"en": "<ul><li><b>Hide a face or a plate:</b> <i>＋ Image…</i> → <b>Blur box</b> or <b>Pixelate box</b>. "
            "Drag it over the spot, pull its corner to resize, and set <i>Strength</i> and the time it is on. "
            "It sits in the Images row.</li>"
            "<li><b>Stickers:</b> <i>＋ Image…</i> → <b>Sticker</b> gives an arrow, ring, star, heart, speech bubble, "
            "check, cross or sparkle. They are ordinary pictures: move, resize, rotate and fade them.</li>"
            "<li><b>Zoom keyframes</b> (clip → Frame tab): move the playhead, press <b>Add keyframe here</b>, then set "
            "the zoom and where to aim. The picture glides between keyframes, for example a slow push-in on the "
            "punchline.</li>"
            "<li><b>Cut to the beat</b> (Music tab): with two or more clips and a song, trims each clip so every cut "
            "lands on a beat. Plain cuts only (no transitions).</li>"
            "<li><b>Remove background</b> (clip → Effects tab): cuts the person out without a green sheet and puts "
            "the background picture (or black) behind. It is done while rendering and takes about three times "
            "the clip's length.</li></ul>",
      "zh": "<ul><li><b>遮住臉或車牌：</b><i>＋ 圖片…</i> → <b>模糊方塊</b>或<b>馬賽克方塊</b>。把它拖到要遮的地方、"
            "拉角落調整大小，並設定<i>強度</i>與出現的時間。它會出現在圖片列。</li>"
            "<li><b>貼圖：</b><i>＋ 圖片…</i> → <b>貼圖</b>有箭頭、圓圈、星星、愛心、對話框、打勾、打叉與閃光。"
            "它們就是一般圖片：可以移動、縮放、旋轉與淡入淡出。</li>"
            "<li><b>縮放關鍵影格</b>（片段 → 畫面頁籤）：移動播放頭，按<b>在此加入關鍵影格</b>，再設定縮放與對準位置。"
            "畫面會在關鍵影格之間平順變化，例如在重點處緩緩推近。</li>"
            "<li><b>對拍剪輯</b>（音樂頁籤）：有兩個以上的片段和一首歌時，修剪每個片段，讓每個剪接點都落在節拍上。"
            "僅適用於一般剪接（無轉場）。</li>"
            "<li><b>移除背景</b>（片段 → 效果頁籤）：不用綠幕就能把人物摳出來，後面放背景圖片（或黑色）。"
            "在輸出時處理，大約需要片段長度的三倍時間。</li></ul>"}),
    ("tools_short", "more", "tools",
     {"en": "Make a Short in one click", "zh": "一鍵做成短影片"},
     {"en": "<ol><li>Open <b>Tools</b> and choose <b>Make a Short</b> (it is the first one).</li>"
            "<li>Choose a long video (or drop one on the window).</li>"
            "<li>Pick 15, 30 or 60 seconds. Shorts, Reels and TikTok stop at 60.</li>"
            "<li>Press <b>Start</b>. VidGrab listens for the liveliest part, makes it vertical (9:16), "
            "keeps the main face in the picture, adds word-by-word captions and evens out the sound.</li></ol>"
            "<p>Face tracking and captions can be switched off. Both use the speech add-on; the speech model "
            "downloads once. If one of them cannot run, you still get your Short without it. "
            "Want to change something? Open the result in the Studio. From a terminal: "
            "<code>vidgrab short FILE --seconds 30</code>.</p>",
      "zh": "<ol><li>開啟<b>工具</b>，選擇<b>做成短影片</b>（第一個）。</li>"
            "<li>選擇一支長影片（或把檔案拖到視窗上）。</li>"
            "<li>選擇 15、30 或 60 秒。Shorts、Reels 與 TikTok 最長 60 秒。</li>"
            "<li>按<b>開始</b>。VidGrab 會找出最精彩的片段、轉成直式（9:16）、讓主要人臉留在畫面中、"
            "加上逐字字幕並整平音量。</li></ol>"
            "<p>人臉追蹤與字幕可以關閉。兩者都需要語音附加元件；語音模型只會下載一次。"
            "若其中一項無法執行，仍會輸出沒有它的短影片。想再調整？在剪輯工作室開啟結果即可。"
            "終端機指令：<code>vidgrab short FILE --seconds 30</code>。</p>"}),
    ("tools_shrink", "more", "tools",
     {"en": "Make a video fit a size limit", "zh": "讓影片符合大小限制"},
     {"en": "<ol><li>Open <b>Tools</b> and choose <b>Shrink to a size</b>.</li>"
            "<li>Choose a file, then a size such as 8 MB (Discord) or 25 MB (e-mail), or your own.</li>"
            "<li>Leave <i>Lower the resolution when needed</i> on: a small size on a big picture looks blurry, "
            "so VidGrab also shrinks the picture.</li>"
            "<li>Press <b>Start</b>. The new file is saved next to the original, which is never changed.</li></ol>"
            "<p>The size is a target: the result lands close to it, usually a little under.</p>",
      "zh": "<ol><li>開啟<b>工具</b>，選擇<b>壓縮到指定大小</b>。</li>"
            "<li>選擇檔案，再選擇大小，例如 8 MB（Discord）、25 MB（電子郵件），或自行輸入。</li>"
            "<li>建議保持開啟「必要時降低解析度」：大畫面配很小的檔案會很模糊，所以 VidGrab 也會縮小畫面。</li>"
            "<li>按<b>開始</b>。新檔案會存在原檔旁邊，原檔不會被更動。</li></ol>"
            "<p>大小是目標值：結果會很接近，通常略小一點。</p>"}),
    ("tools_other", "more", "tools",
     {"en": "Convert, GIF, thumbnail and audio", "zh": "轉檔、GIF、縮圖與音訊"},
     {"en": "<ul><li><b>Convert</b> changes the format: MP4, MKV, WebM, or audio (MP3, M4A, Opus, WAV, FLAC).</li>"
            "<li><b>Make a GIF</b> turns a few seconds, from the time you choose, into a looping GIF.</li>"
            "<li><b>Thumbnail</b> saves one frame as a 1280×720 picture. Type a title and it is drawn on the "
            "picture, with a preview as you type.</li>"
            "<li><b>Extract audio</b> saves only the sound.</li></ul>"
            "<p>Each result is saved next to the original, with a note in its name such as “(gif)”.</p>",
      "zh": "<ul><li><b>轉檔</b>更換格式：MP4、MKV、WebM，或音訊（MP3、M4A、Opus、WAV、FLAC）。</li>"
            "<li><b>製作 GIF</b>把你選的起點之後的幾秒鐘變成循環播放的 GIF。</li>"
            "<li><b>縮圖</b>把一個畫面存成 1280×720 的圖片。輸入標題會畫在圖上，並即時預覽。</li>"
            "<li><b>擷取音訊</b>只儲存聲音。</li></ul>"
            "<p>結果會存在原檔旁邊，檔名會註明，例如「(gif)」。</p>"}),
    ("channels", "more", "subscriptions",
     {"en": "Follow channels and grab new videos", "zh": "追蹤頻道並抓取新影片"},
     {"en": "<ol><li>Open <b>Channels</b>, paste a channel or playlist link and press <b>Follow</b>.</li>"
            "<li>Its newest videos appear on the right. After the first look, videos that appeared since "
            "you last checked are marked with a dot.</li>"
            "<li>Press <b>Tick the new ones</b> (or tick any you like) and then <b>Download ticked</b>. They go "
            "into the normal Download queue.</li></ol>"
            "<p>Your list is stored on your computer. VidGrab only looks when you open the page or press "
            "Refresh.</p>",
      "zh": "<ol><li>開啟<b>頻道</b>，貼上頻道或播放清單連結，按<b>追蹤</b>。</li>"
            "<li>最新的影片會顯示在右側。第一次查看之後，上次之後新出現的影片會以圓點標示。</li>"
            "<li>按<b>勾選新影片</b>（或自行勾選），再按<b>下載已勾選的</b>。它們會進入一般的下載佇列。</li></ol>"
            "<p>追蹤清單只存在你的電腦。VidGrab 只會在你開啟此頁或按重新整理時查看。</p>"}),
    ("best_moment", "more", "studio",
     {"en": "Keep only the best moment", "zh": "只保留最精彩的片段"},
     {"en": "<p>Select a clip, open the <b>Trim</b> tab and press <b>Best moment…</b>, then pick 15, 30 or "
            "60 seconds. VidGrab listens to the clip and keeps the loudest, most active stretch of that length "
            "(speech, music, cheering) instead of a quiet intro.</p>"
            "<p>It is one undo step, and you can still drag the trim handles afterwards. It judges by sound only, "
            "so check the result.</p>",
      "zh": "<p>選取片段，開啟<b>裁切</b>分頁，按<b>最佳片段…</b>，再選擇 15、30 或 60 秒。"
            "VidGrab 會聆聽影片，保留該長度中聲音最大、最活躍的一段（說話、音樂、歡呼），而不是安靜的開頭。</p>"
            "<p>整個動作只算一次復原，之後仍可拖曳裁切把手。它只依聲音判斷，請確認結果。</p>"}),
    ("translate_captions", "captions", "studio",
     {"en": "Captions in English from any language", "zh": "把任何語言轉成英文字幕"},
     {"en": "<p>In the Auto captions window, set <b>Spoken language</b> to <b>Translate to English</b>. "
            "The speech engine listens in whatever language is spoken and writes the captions in English. "
            "Translations of small models are rougher than normal captions, so pick a larger model "
            "for important videos.</p>",
      "zh": "<p>在自動字幕視窗，把<b>口說語言</b>設為<b>翻譯成英文</b>。"
            "語音引擎會聽取任何語言，並以英文寫出字幕。小型模型的翻譯較粗略，重要影片請選擇較大的模型。</p>"}),
    ("faq_cli", "faq", None,
     {"en": "Use VidGrab from the command line", "zh": "從命令列使用 VidGrab"},
     {"en": "<p>These commands run without opening a window:</p>"
            "<ul><li><b>vidgrab get URL</b> (add <b>--mp3</b>, <b>--quality 720</b>, <b>--out FOLDER</b>)</li>"
            "<li><b>vidgrab shrink FILE --mb 25</b></li>"
            "<li><b>vidgrab convert FILE --to mp3</b></li>"
            "<li><b>vidgrab gif FILE --start 3 --length 4</b></li>"
            "<li><b>vidgrab best FILE --seconds 30</b> prints the start and end of the liveliest stretch</li></ul>"
            "<p><b>vidgrab --help</b> lists them all.</p>",
      "zh": "<p>以下指令不會開啟視窗：</p>"
            "<ul><li><b>vidgrab get 網址</b>（可加 <b>--mp3</b>、<b>--quality 720</b>、<b>--out 資料夾</b>）</li>"
            "<li><b>vidgrab shrink 檔案 --mb 25</b></li>"
            "<li><b>vidgrab convert 檔案 --to mp3</b></li>"
            "<li><b>vidgrab gif 檔案 --start 3 --length 4</b></li>"
            "<li><b>vidgrab best 檔案 --seconds 30</b> 會印出最精彩一段的起訖時間</li></ul>"
            "<p><b>vidgrab --help</b> 可查看全部指令。</p>"}),
    ("faq_ffmpeg", "faq", None,
     {"en": "It says ffmpeg is missing", "zh": "顯示找不到 ffmpeg"},
     {"en": "<p>The Windows and Linux downloads include ffmpeg. If you installed VidGrab with pip or on macOS, "
            "it offers to download ffmpeg once, and you can accept. After that trimming, MP3 and the "
            "Studio work.</p>",
      "zh": "<p>Windows 與 Linux 版本已內建 ffmpeg。若你是用 pip 或在 macOS 安裝，VidGrab 會詢問是否下載一次 ffmpeg，"
            "同意後裁切、MP3 與 Studio 都能正常使用。</p>"}),
    ("faq_403", "faq", "settings",
     {"en": "A download fails or is only 360p", "zh": "下載失敗或只有 360p"},
     {"en": "<p>YouTube changes often. In Settings → Downloads press <b>Update yt-dlp</b>; the new version "
            "applies the next time you start VidGrab. Using a different network or turning off a VPN also "
            "helps with “403” and “not a bot” messages.</p>"
            "<p>For videos that need an account, see “Age-restricted or members-only videos”.</p>",
      "zh": "<p>YouTube 經常改版。到 設定 → 下載 按<b>更新 yt-dlp</b>，下次啟動時生效。"
            "遇到「403」或「不是機器人」訊息時，換個網路或關閉 VPN 也有幫助。</p>"
            "<p>需要帳號的影片請見「年齡限制或會員限定影片」。</p>"}),
    ("faq_slow", "faq", "settings",
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
            "that you can turn off in Settings. While you type words in the Download box, YouTube's own "
            "suggestions are fetched (only the words, never links); that is a switch in Settings → Downloads.</p>",
      "zh": "<p>字幕在你的電腦上產生，不會上傳任何音訊。設定、歷史紀錄與復原檔存放在應用程式的設定資料夾。"
            "VidGrab 只會在下載、經你同意下載模型或 ffmpeg，以及安靜地檢查 yt-dlp 版本時連線，檢查可在設定中關閉。"
            "在下載欄輸入文字時，會取得 YouTube 的搜尋建議（只傳送文字，絕不傳送連結），可在 設定 → 下載 關閉。</p>"}),
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


_INDEX: dict[str, FuzzyIndex] = {}


def index(lang: str) -> FuzzyIndex:
    """The fuzzy index of one language (built once): a title weighs three times a body."""
    if lang not in _INDEX:
        ix = FuzzyIndex()
        for tid, _sec, _page, title, body in TOPICS:
            ix.add(tid, title[lang], (title[lang], 3.0), (text_of(body[lang]), 1.0))
        _INDEX[lang] = ix
    return _INDEX[lang]


def search(query: str, lang: str) -> list[str]:
    """Ids of the topics that match *query*, best match first (typos, half-typed
    words and Chinese included); every topic, in list order, for an empty query."""
    if not query.strip():
        return [t[0] for t in TOPICS]
    return [str(k) for k, _score in index(lang).search(query, limit=len(TOPICS))]


def did_you_mean(query: str, lang: str) -> str | None:
    return index(lang).did_you_mean(query)

"""Qt-free live search suggestions for the Download box (what YouTube itself offers
while you type). One small request per pause in typing, to Google's suggestion
service that YouTube's own search box uses; it sees only the words typed so far."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

URL = "https://suggestqueries.google.com/complete/search"


def youtube_suggestions(query: str, *, timeout: float = 3.0, proxy: str = "", lang: str = "") -> list[str]:
    """Up to ten completions of *query* ([] on any network problem: suggestions
    are a nicety, never an error)."""
    query = query.strip()
    if not query:
        return []
    params = {"client": "firefox", "ds": "yt", "q": query}
    if lang:
        params["hl"] = lang
    req = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) \
        if proxy else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return [s for s in data[1] if isinstance(s, str)][:10]
    except (OSError, ValueError, IndexError, TypeError):
        return []


def merge(local: list[str], online: list[str], limit: int = 8) -> list[str]:
    """Your own earlier searches first (they are what you are likely to repeat),
    then YouTube's, each text once (ignoring case)."""
    seen: set[str] = set()
    out: list[str] = []
    for text in [*local, *online]:
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            out.append(text)
    return out[:limit]

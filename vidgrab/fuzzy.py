"""Qt-free fuzzy search with best-match ranking.

`FuzzyIndex` keeps an inverted index (word -> documents) and a **trie** of every
word. A query word is looked up in the trie three ways, each worth less:
exact, prefix (so a half-typed last word already finds things), and *within a few
typos* (a bounded Levenshtein walk down the trie, pruned as soon as a row of the
edit table can no longer get under the limit). Chinese / Japanese text has no
spaces, so every character and every pair of neighbours is a word. A document must
match every query word; a phrase that appears whole, an early or title match score
extra. `suggest()` gives the best labels to offer while typing and `did_you_mean()`
the nearest known word for a query that found nothing."""
from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CJK = re.compile(r"[⺀-鿿가-힯぀-ヿ]")

EXACT, PREFIX, TYPO, LOOSE = 10.0, 7.0, 5.0, 2.5  # what a word match is worth
PHRASE_BONUS = 12.0
WHOLE_BONUS = 6.0
MAX_PREFIX_WORDS = 60  # words one query word may expand to


def normalize(text: str) -> str:
    """Lower case, width-folded, accent-free (so 'cafe' finds 'Café')."""
    t = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in t if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    """Words of *text*; each CJK character and each CJK pair is a word too."""
    out: list[str] = []
    for w in _WORD.findall(normalize(text)):
        if _CJK.search(w):
            chars = [c for c in w if _CJK.match(c)]
            out += chars + ["".join(p) for p in itertools.pairwise(chars)]
            out += [x for x in re.findall(r"[^⺀-鿿가-힯぀-ヿ]+", w)]
        else:
            out.append(w)
    return out


def allowed_typos(word: str) -> int:
    """Short words get no typos (too many false hits), long ones up to two."""
    n = len(word)
    return 0 if n <= 3 else 1 if n <= 6 else 2


class _Node:
    __slots__ = ("children", "end")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.end = False


class Trie:
    def __init__(self) -> None:
        self.root = _Node()
        self.size = 0

    def add(self, word: str) -> None:
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, _Node())
        if not node.end:
            node.end = True
            self.size += 1

    def __contains__(self, word: str) -> bool:
        node = self._walk(word)
        return bool(node and node.end)

    def _walk(self, prefix: str) -> _Node | None:
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def with_prefix(self, prefix: str, limit: int = MAX_PREFIX_WORDS) -> list[str]:
        """Words that start with *prefix*, shortest first (breadth first)."""
        start = self._walk(prefix)
        if start is None:
            return []
        out: list[str] = []
        level = [(prefix, start)]
        while level and len(out) < limit:
            nxt = []
            for text, node in level:
                if node.end:
                    out.append(text)
                nxt += [(text + ch, child) for ch, child in sorted(node.children.items())]
            level = nxt
        return out[:limit]

    def within(self, word: str, max_dist: int) -> list[tuple[str, int]]:
        """(known word, edit distance) for every word within *max_dist* edits
        (insert, delete, replace, or swap two neighbours)."""
        found: list[tuple[str, int]] = []
        first = list(range(len(word) + 1))

        def walk(node: _Node, text: str, prev: list[int], prev2: list[int] | None, last: str) -> None:
            for ch, child in node.children.items():
                row = [prev[0] + 1]
                for i in range(1, len(word) + 1):
                    cost = 0 if word[i - 1] == ch else 1
                    v = min(row[i - 1] + 1, prev[i] + 1, prev[i - 1] + cost)
                    if prev2 is not None and i > 1 and word[i - 1] == last and word[i - 2] == ch:
                        v = min(v, prev2[i - 2] + 1)  # two letters swapped
                    row.append(v)
                if child.end and row[-1] <= max_dist:
                    found.append((text + ch, row[-1]))
                if min(row) <= max_dist:
                    walk(child, text + ch, row, prev, ch)

        walk(self.root, "", first, None, "")
        return found

    def prefix_within(self, prefix: str, max_dist: int) -> list[str]:
        """Words that begin with something within *max_dist* edits of *prefix*
        (a half-typed, slightly wrong word)."""
        found: list[str] = []
        first = list(range(len(prefix) + 1))

        def walk(node: _Node, text: str, prev: list[int]) -> None:
            for ch, child in node.children.items():
                row = [prev[0] + 1]
                for i in range(1, len(prefix) + 1):
                    cost = 0 if prefix[i - 1] == ch else 1
                    row.append(min(row[i - 1] + 1, prev[i] + 1, prev[i - 1] + cost))
                if row[-1] <= max_dist:
                    found.extend(self.with_prefix(text + ch, 6))
                elif min(row) <= max_dist:
                    walk(child, text + ch, row)
                if len(found) >= MAX_PREFIX_WORDS:
                    return

        walk(self.root, "", first)
        return found


def subsequence(needle: str, hay: str) -> bool:
    """*needle*'s letters appear in *hay* in order ('shrnk' in 'shrink')."""
    it = iter(hay)
    return len(needle) >= 3 and all(c in it for c in needle)


@dataclass
class Doc:
    key: object
    label: str
    fields: list[tuple[str, float]]
    flat: str  # normalized text, for whole-phrase hits


class FuzzyIndex:
    """Add documents with `add()`, then `search()` / `suggest()` / `did_you_mean()`."""

    def __init__(self) -> None:
        self.docs: list[Doc] = []
        self.trie = Trie()
        self.postings: dict[str, dict[int, float]] = {}  # word -> {doc number: field weight}

    def add(self, key: object, label: str, *fields: tuple[str, float]) -> None:
        """*label* is what `suggest()` shows; *fields* are (text, weight) pairs
        that can match (a title weighs more than a body)."""
        fields = fields or ((label, 1.0),)
        n = len(self.docs)
        self.docs.append(Doc(key, label, list(fields), normalize(" ".join(t for t, _ in fields))))
        for text, weight in fields:
            for w in words(text):
                self.trie.add(w)
                slot = self.postings.setdefault(w, {})
                slot[n] = max(slot.get(n, 0.0), weight)

    # ── matching ───────────────────────────────────────────────────────

    def _expand(self, word: str, last: bool) -> dict[str, float]:
        """Known words a query word may mean, with what each match is worth."""
        out: dict[str, float] = {}
        if word in self.trie:
            out[word] = EXACT
        if last or len(word) >= 3:  # a half-typed word (any, but the last for a very short one)
            for w in self.trie.with_prefix(word):
                out.setdefault(w, PREFIX if len(word) > 1 else LOOSE)
        k = allowed_typos(word)
        if k:
            for w, d in self.trie.within(word, k):
                out.setdefault(w, TYPO - (d - 1))
            if last:
                for w in self.trie.prefix_within(word, k):
                    out.setdefault(w, LOOSE)
            for w in self.postings:
                if w not in out and abs(len(w) - len(word)) <= 2 and subsequence(word, w) and len(word) >= 4:
                    out[w] = LOOSE
        return out

    def _scores(self, query: str) -> dict[int, float]:
        q_words = words(query)
        if not q_words:
            return {}
        total: dict[int, float] | None = None
        for i, qw in enumerate(q_words):
            per_doc: dict[int, float] = {}
            for w, value in self._expand(qw, last=i == len(q_words) - 1).items():
                for n, weight in self.postings[w].items():
                    per_doc[n] = max(per_doc.get(n, 0.0), value * weight)
            if total is None:
                total = per_doc
            else:
                total = {n: total[n] + s for n, s in per_doc.items() if n in total}
            if not total:
                return {}
        assert total is not None
        flat = normalize(query).strip()
        for n in total:
            doc = self.docs[n]
            pos = doc.flat.find(flat)
            if pos >= 0:
                total[n] += PHRASE_BONUS + max(0.0, 4.0 - pos / 8)
                if re.search(rf"(?<!\w){re.escape(flat)}(?!\w)", doc.flat):
                    total[n] += WHOLE_BONUS  # the words as typed, not part of longer ones
            if normalize(doc.label).startswith(flat):
                total[n] += 3.0
        return total

    def search(self, query: str, limit: int = 20) -> list[tuple[object, float]]:
        """(key, score) best first; ties keep the order documents were added."""
        scores = self._scores(query)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(self.docs[n].key, round(s, 2)) for n, s in ranked[:limit]]

    def suggest(self, query: str, limit: int = 8) -> list[str]:
        """Labels to offer while the user types."""
        scores = self._scores(query)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        out: list[str] = []
        for n, _s in ranked:
            if self.docs[n].label not in out:
                out.append(self.docs[n].label)
            if len(out) >= limit:
                break
        return out

    def did_you_mean(self, query: str) -> str | None:
        """The query with each unknown word replaced by its nearest known word,
        or None when that changes nothing / finds nothing."""
        fixed, changed = [], False
        for w in words(query):
            if w in self.trie:
                fixed.append(w)
                continue
            options = self.trie.within(w, max(allowed_typos(w), 1))
            if not options:
                return None
            best = min(options, key=lambda wd: (wd[1], -len(self.postings.get(wd[0], ())), wd[0]))
            fixed.append(best[0])
            changed = True
        return " ".join(fixed) if changed else None

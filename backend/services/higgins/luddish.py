"""Higgins Luddish L1 on ApolloSG's server — the same plain wording the app gives (frontend src/domain/luddish).

Mirror of the app's luddishText: grammar.ts rewriteLine (plain-word swaps, the dictionary's exact plain names with
"a"/"an" put right, tidying, safe sentence splits), patterns.ts hold/restore (identifiers and quotes survive word for
word) and fidelity.ts differences (a line whose plain wording would change anything keeps Apollo's words). The words
come from content/luddish.json, generated from the app's own Luddish (frontend/scripts/exportLuddish.ts), and its parity
corpus pins the two sides together (tests/test_luddish_parity.py).

Used for words the server itself puts in front of the person — push notifications — so they read exactly as the same
words would in the app. Pure: no I/O beyond reading the data file once.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DATA = json.loads((Path(__file__).resolve().parents[2] / "content" / "luddish.json").read_text(encoding="utf-8"))

# ── patterns.ts ──
_END = r"[^\s<>\"'”)\].,;:!?]"
_IDENTIFIERS = (
    re.compile(r"“[^”\n]{1,500}”|\"[^\"\n]{1,500}\""),                                               # quoted words
    re.compile(rf"\bhttps?://[^\s<>\"'”)\]]*{_END}", re.I),                                          # links
    re.compile(r"\b[\w.%+-]+@[\w-]+(?:\.[\w-]+)+\b", re.A),                                         # email addresses
    re.compile(rf"\b(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+[a-z]{{2,24}}\b(?:/[^\s<>\"'”)\]]*{_END})?", re.I | re.A),  # domains
    re.compile(r"(?<![\w.])\+?\d[\d ()-]{6,}\d(?![\w.])", re.A),                                     # phone numbers
    re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d+)?"),                                                       # money
    re.compile(r"\b\d+(?:\.\d+)?%", re.A),                                                           # percentages
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?\b", re.A),                   # dates
    re.compile(r"\b\d{1,2}:\d{2}(?:\s?[ap]m)?\b", re.I | re.A),                                       # times
)
_ABBREVIATIONS = re.compile(r"\b(?:e\.g\.|i\.e\.|etc\.|vs\.|approx\.)(?=\s)", re.A)
_ABBREVIATION = re.compile(r"(?:e\.g\.|i\.e\.|etc\.|vs\.|approx\.)")
_MARK = re.compile(r"\x00(\d+)\x00")


def hold(text: str) -> tuple[str, list[str]]:
    held: list[str] = []

    def keep(m: re.Match) -> str:
        held.append(m.group(0))
        return f"\x00{len(held) - 1}\x00"
    for pattern in (*_IDENTIFIERS, _ABBREVIATIONS):
        text = pattern.sub(keep, text)
    return text, held


def restore(text: str, held: list[str]) -> str:
    for _ in range(4):
        if not _MARK.search(text):
            break
        text = _MARK.sub(lambda m: held[int(m.group(1))] if int(m.group(1)) < len(held) else "", text)
    return text


def identifiers(text: str) -> set[str]:
    return {h for h in hold(text)[1] if not _ABBREVIATION.fullmatch(h)}


def words(text: str) -> list[str]:
    low = re.sub(r"[^a-z0-9'§\s-]", " ", text.lower().replace("’", "'").replace("‘", "'"))
    return [w for w in (re.sub(r"^[-']+|[-']+$", "", w) for w in low.split()) if w]


# ── grammar.ts ──
_SWAPPED = "\x01"
_SWAPS = [(re.compile(rf"(?<![\w'-]){re.escape(formal)}(?![\w'-])", re.I | re.A), plain, bool(re.search(r"n't\b", plain)))
          for formal, plain in sorted(_DATA["plainSwaps"], key=lambda s: -len(s[0]))]
_TERMS = [(re.compile(rf"(?<![\w-])(?:{t['match']})(?![\w-])", re.A | (0 if t["exactCase"] else re.I)), t["one"], t["many"])
          for t in _DATA["plainTerms"]]
_INSTRUCTION_BEFORE = re.compile(r"(?:^|[.!?:;,(—–]\s*|\b(?:and|or|then|please|but|so|just|also)\s+)\Z", re.I | re.A)
_CAPITALISED = re.compile(r"[A-Z](?:[a-z]|\Z|[^A-Za-z])")
_ARTICLE = re.compile(rf"\b(an?|An?) {_SWAPPED}([A-Za-z])", re.A)


def _full_not(plain: str) -> str:
    return re.sub(r"n't\b", " not", re.sub(r"\bwon't\b", "will not", re.sub(r"\bcan't\b", "cannot", plain, count=1), count=1), count=1)


def _keeps_full_not(match: str, before: str, strong: bool) -> bool:
    return strong or "NOT" in match or (bool(re.fullmatch(r"do not", match, re.I)) and bool(_INSTRUCTION_BEFORE.search(before)))


def _cased(original: str, plain: str) -> str:
    return plain[0].upper() + plain[1:] if _CAPITALISED.match(original) else plain


def _swap_held(text: str, strong: bool = False) -> str:
    out = text
    for rx, plain, shortens in _SWAPS:
        def swap_one(m: re.Match, plain: str = plain, shortens: bool = shortens) -> str:
            word = m.group(0)
            if not shortens or not _keeps_full_not(word, m.string[: m.start()], strong):
                return _SWAPPED + _cased(word, plain)
            return word if re.search("not", word, re.I) else _SWAPPED + _cased(word, _full_not(plain))
        out = rx.sub(swap_one, out)
    for rx, one, many in _TERMS:
        out = rx.sub(lambda m, one=one, many=many: _SWAPPED + _cased(m.group(0), many if many and m.group(0)[-1:].lower() == "s" else one), out)

    def article(m: re.Match) -> str:
        fixed = "an" if m.group(2).lower() in "aeiou" else "a"
        return f"{fixed[0].upper() + fixed[1:] if m.group(1)[0] == 'A' else fixed} {m.group(2)}"
    return _ARTICLE.sub(article, out).replace(_SWAPPED, "")


def swap(text: str) -> str:
    held, kept = hold(text)
    return restore(_swap_held(held), kept)


_SMALL_DOUBLES = re.compile(r"\b(the|a|an|to|of|and|is|in|it|on|for)\s+\1\b", re.I | re.A)
_CODE_WORD = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b", re.A)


def _tidy(line: str) -> str:
    out = _CODE_WORD.sub(lambda m: m.group(0).replace("_", " "), line)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])(?=\s|\Z|[A-Z])", r"\1", out)
    out = re.sub(r"([a-z])([.!?])(?=[A-Z][a-z])", r"\1\2 ", out)
    out = re.sub(r",{2,}", ",", out)
    out = re.sub(r"(?<!\.)\.\.(?!\.)", ".", out)
    out = re.sub(r"([!?]){2,}", r"\1", out)
    out = _SMALL_DOUBLES.sub(r"\1", out)
    out = re.sub(r"(^|[.!?]\s+)However,\s+", r"\1But ", out)
    out = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    return out.strip()


_SPLIT_OVER, _MIN_PART = 20, 5
_NO_SPLIT_AFTER = re.compile(r"(?:not|only|also|that|as|too|then|far|much|many|on)\b", re.I | re.A)
_DASH_STARTS = re.compile(r"(?:it|it's|this|that's|they|they're|you|you're|we|apollo|apollosg|higgins|there|don't|do|go|call|contact|check"
                          r"|delete|never|hang|open|report)\b", re.I | re.A)
_PREFIX = re.compile(r"(\s*(?:[-*•]|\d+[.)])\s+)?")


def _count_words(text: str) -> int:
    return len(text.split())


def _split(sentence: str) -> list[str]:
    if _count_words(sentence) <= _SPLIT_OVER:
        return [sentence]
    joints = ["; ", ", but ", ", so ", " — "] if len(sentence.split(" — ")) == 2 else ["; ", ", but ", ", so "]
    for joint in joints:
        start = 0
        while True:
            at = sentence.find(joint, start)
            if at < 0:
                break
            start = at + len(joint)
            left, rest = sentence[:at].strip(), sentence[at + len(joint):]
            word = re.sub(r"[;,—]", "", joint).strip()
            right = (f"{word} {rest}" if word else rest).strip()
            if _count_words(left) < _MIN_PART or _count_words(right) < _MIN_PART or _NO_SPLIT_AFTER.match(rest):
                continue
            if joint == " — " and not _DASH_STARTS.match(rest):
                continue
            end = left if re.search(r"[.!?]\Z", left) else f"{left}."
            return [*_split(end), *_split(right[0].upper() + right[1:])]
    return [sentence]


def rewrite_line(line: str, strong: bool = False) -> str:
    if not line.strip():
        return line
    prefix = _PREFIX.match(line).group(0)
    held, kept = hold(line[len(prefix):])
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", _tidy(_swap_held(held, strong))) if s.strip()]
    out = [piece for part in parts for piece in _split(part)]
    if len(out) > len(parts) and re.search(r"[A-Za-z0-9_\x00]\Z", out[-1]):
        out[-1] += "."
    return prefix + restore(" ".join(out), kept)


# ── fidelity.ts differences ──
_STOP = set(("a an the this that these those it its is are was were be been being so to of on in at or and but with for by as from your you "
             "there here what which who how would will can could has have had do does did if then than also just into about").split())
_NEGATIONS = {"not", "no", "never", "nothing", "none", "nobody", "nowhere", "neither", "nor", "without"}
_CAUSAL = re.compile(r"\b(because|so|therefore|as a result|which means|that's why|that is why|hence|thus|since)\b", re.I | re.A)
_QUOTE = re.compile(r"“[^”\n]{1,500}”|\"[^\"\n]{1,500}\"")


def _stem(word: str) -> str:
    return re.sub(r"(?<=[a-z]{3})(?:ing|ed|es|s)$", "", word)


def _canon(text: str) -> list[str]:
    out: list[str] = []
    for raw in words(swap(text)):
        if raw in ("can't", "cannot"):
            out += ["can", "not"]
        elif raw == "won't":
            out += ["will", "not"]
        elif raw.endswith("n't"):
            out += [raw[:-3], "not"]
        else:
            w = re.sub(r"'(s|re|ve|ll|d|m)$", "", raw).replace("'", "")
            if w and w not in _STOP:
                out.append(w if w in _NEGATIONS else _stem(w))
    return [w for w in out if w and w not in _STOP]


def _count(text: str, phrase: str) -> int:
    return len(re.findall(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", text.lower().replace("’", "'").replace("‘", "'"), re.A))


def _digits(ws: list[str]) -> str:
    return " ".join(sorted(w for w in ws if re.search(r"\d", w)))


def differences(original: str, rendered: str) -> list[str]:
    """What changed between Apollo's wording and the plain wording: nothing (empty) when it's the same point."""
    if original == rendered:
        return []
    out: list[str] = []
    before, after = identifiers(original), identifiers(rendered)
    out += ["QUOTE_ALTERED" if re.match(r"[\"“]", i) else "IDENTIFIER_DROPPED" for i in before if i not in after]
    out += ["IDENTIFIER_ADDED" for i in after if i not in before]
    out += ["QUOTE_ALTERED" for q in _QUOTE.findall(original) if q not in rendered]
    a, b = _canon(original), _canon(rendered)
    sa, sb = set(a), set(b)
    if sa and (len(sa & sb) / len(sa) < 0.85 or (sb and len(sb - sa) / len(sb) > 0.25)):
        out.append("MEANING_CHANGED")
    if sum(w in _NEGATIONS for w in a) != sum(w in _NEGATIONS for w in b):
        out.append("NEGATION_CHANGED")
    if _digits(words(original)) != _digits(words(rendered)):
        out.append("NUMBER_CHANGED")
    if _CAUSAL.search(original) and not _CAUSAL.search(rendered):
        out.append("CAUSAL_DROPPED")
    out += [code for code, phrases in _DATA["tone"].items() if any(_count(rendered, p) > _count(original, p) for p in phrases)]
    return list(dict.fromkeys(out))


def luddish_text(text: str, strong: bool = False) -> str:
    """The app's luddishText: each line in plain words, unless the plain wording would change anything. `strong`: a
    headline or a step of what to do, which keeps every "not" in full."""
    lines = []
    for line in (text or "").split("\n"):
        plain = rewrite_line(line, strong)
        lines.append(line if differences(line, plain) else plain)
    return "\n".join(lines)

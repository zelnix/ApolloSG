"""ApolloSG User Guide — how a person actually uses ApolloSG, in plain English.

The guide lives in ``user_guide.json`` and is the same text the app's User Guide screen shows
(``frontend/src/guide/userGuide.json`` is an exact copy, checked by ``tests/test_user_guide.py``;
after editing, run ``python scripts/sync_user_guide.py``).

Higgins uses it for "how do I…" / "where is…" questions: he picks the one topic that answers the
question and gives its direct answer and steps first — never a whole section, and never a scam
article in place of a product answer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

GUIDE_PATH = Path(__file__).with_name("user_guide.json")


@dataclass(frozen=True)
class GuideTopic:
    id: str
    title: str
    section: str
    answer: str                    # the direct answer — one or two sentences
    steps: tuple[str, ...]         # ordered steps, when the task has them
    notes: tuple[str, ...]         # honest limitations (platform, "can't be undone")
    routes: tuple[str, ...]        # screens the answer links to
    questions: tuple[str, ...]     # common ways people ask for it
    keywords: tuple[str, ...]


def _load() -> tuple[str, list[tuple[str, list[GuideTopic]]]]:
    data = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    sections = []
    for section in data["sections"]:
        topics = [GuideTopic(
            id=t["id"], title=t["title"], section=section["title"], answer=t["answer"],
            steps=tuple(t.get("steps") or ()), notes=tuple(t.get("notes") or ()),
            routes=tuple(link["route"] for link in t.get("links") or ()),
            questions=tuple(t.get("questions") or ()), keywords=tuple(t.get("keywords") or ()),
        ) for t in section["topics"]]
        sections.append((section["title"], topics))
    return data["reviewed"], sections


REVIEWED, SECTIONS = _load()
TOPICS: list[GuideTopic] = [topic for _title, topics in SECTIONS for topic in topics]
TOPIC_BY_ID: dict[str, GuideTopic] = {t.id: t for t in TOPICS}

# ── Matching a question to a topic ───────────────────────────────────────────

_STOP = frozenset("""
a an the to my me i im ive is are am was be been can could would should do does did doing how what where
which who when why in on of for it its this that these those with from into at by you your there if and or so
just please want need go has have had any some get
""".split())
_ALIAS = {"apollosg": "apollo", "url": "link", "sms": "text", "wifi": "wi-fi"}


def _words(text: str) -> set[str]:
    out = set()
    for word in re.findall(r"[a-z0-9]+", (text or "").lower().replace("'", "").replace("’", "")):
        word = _ALIAS.get(word, word)
        if word in _STOP:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return out


_PHRASINGS: dict[str, list[set[str]]] = {t.id: [_words(q) for q in (t.title, *t.questions)] for t in TOPICS}
_VOCAB: dict[str, set[str]] = {t.id: set().union(*_PHRASINGS[t.id], *(_words(k) for k in t.keywords)) for t in TOPICS}
_THRESHOLD = 0.5


def _score(query: set[str], topic: GuideTopic) -> float:
    phrase = max((len(query & p) / len(query | p) for p in _PHRASINGS[topic.id] if p), default=0.0)
    cover = len(query & _VOCAB[topic.id]) / len(query)
    return max(phrase, cover * (0.75 if len(query) > 1 else 0.5))


def find_topics(question: str, limit: int = 3) -> list[GuideTopic]:
    """The topics that answer the question, best first; empty when none answers it well enough."""
    query = _words(question)
    if not query:
        return []
    scored = sorted(((_score(query, t), i, t) for i, t in enumerate(TOPICS)), key=lambda item: (-item[0], item[1]))
    return [t for score, _i, t in scored[:limit] if score >= _THRESHOLD]


def topic_answer(topic: GuideTopic) -> str:
    """Direct answer first, then the steps, then any honest limitation."""
    parts = [topic.answer]
    if topic.steps:
        parts.append("\n".join(f"{i}. {step}" for i, step in enumerate(topic.steps, 1)))
    if topic.notes:
        parts.append("\n".join(f"Note: {note}" for note in topic.notes))
    return "\n\n".join(parts)


def topic_reply(topic: GuideTopic) -> dict:
    return {"answer": topic_answer(topic), "navigate": list(topic.routes[:2]), "limitation": False, "topic_id": topic.id}


def guide_answer(question: str) -> dict | None:
    """Higgins' reply from the one guide topic that answers the question, or None."""
    found = find_topics(question, limit=1)
    return topic_reply(found[0]) if found else None

"""The ApolloSG User Guide: genuine (every step names a real screen or button), shared with the app,
and what Higgins answers "how do I…" questions from — direct answer first, never a scam article."""
import asyncio
import json
import re
from pathlib import Path

import pytest

from services.higgins import app_knowledge, chat, context_tools, presenter, user_guide

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
GUIDE = json.loads(user_guide.GUIDE_PATH.read_text(encoding="utf-8"))
ALL_TOPICS = [t for s in GUIDE["sections"] for t in s["topics"]]


def _frontend_source() -> str:
    text = "".join(p.read_text(errors="ignore") for folder in ("app", "src") for p in (FRONTEND / folder).rglob("*.ts*")
                   if "/src/guide/" not in str(p))
    return text.replace("\\u2014", "—").replace("\\u2026", "…").replace("&apos;", "'")


# ── The guide itself ─────────────────────────────────────────────────────────

def test_app_bundles_an_exact_copy_of_the_guide():
    copy = FRONTEND / "src/guide/userGuide.json"
    assert copy.read_bytes() == user_guide.GUIDE_PATH.read_bytes(), "run: cd backend && python scripts/sync_user_guide.py"


def test_every_topic_is_complete_and_unique():
    ids = [t["id"] for t in ALL_TOPICS]
    assert len(ids) == len(set(ids))
    assert len(GUIDE["sections"]) >= 10
    for t in ALL_TOPICS:
        assert t["title"] and t["answer"], t["id"]
        assert len(t["answer"]) <= 330, f"{t['id']}: the direct answer must stay short"
        assert len(t.get("questions") or []) >= 3, f"{t['id']} needs common phrasings for Higgins"


def test_every_link_opens_a_real_screen_higgins_and_the_app_both_allow():
    app_map = (FRONTEND / "src/higgins/appMap.ts").read_text()
    for t in ALL_TOPICS:
        for link in t.get("links") or []:
            route = link["route"]
            assert app_knowledge.valid_route(route), f"{t['id']}: {route} missing from NAV_ROUTES"
            assert f'"{route}"' in app_map, f"{t['id']}: {route} missing from APOLLO_DESTINATIONS"
            path = route.lstrip("/")
            assert (FRONTEND / f"app/{path}.tsx").exists() or (FRONTEND / f"app/{path}/index.tsx").exists(), route


ALLOWED_EXAMPLES = {"Is this a scam?", "I want to check a link", "my phone is acting strangely", "was this you?", "Looks like a link"}


def test_every_quoted_button_or_label_exists_in_the_app():
    """A quoted “label” is something the person will look for — it must be on screen (or be another guide topic)."""
    source = _frontend_source()
    titles = {t["title"] for t in ALL_TOPICS}
    missing = []
    for t in ALL_TOPICS:
        texts = [t["answer"], *(t.get("steps") or []), *(t.get("notes") or []),
                 *(d["heading"] for d in t.get("details") or []), *(d["text"] for d in t.get("details") or [])]
        for text in texts:
            for label in re.findall(r"“([^”]+)”", text):
                core = label.split("…")[0].strip()
                if label in titles or label in ALLOWED_EXAMPLES or core in source:
                    continue
                missing.append((t["id"], label))
    assert not missing, missing


def test_guide_never_sends_people_to_hidden_screens():
    for t in ALL_TOPICS:
        prose = " ".join([t["answer"], *(t.get("steps") or []), *(d["text"] for d in t.get("details") or [])])
        assert "Check It" not in prose, t["id"]
        for link in t.get("links") or []:
            assert link["route"] not in ("/(tabs)/check-it", "/(tabs)/guard"), t["id"]


# ── Higgins: finding the topic ───────────────────────────────────────────────

@pytest.mark.parametrize("question,topic", [
    ("How do I share something into ApolloSG?", "share-into"),
    ("ApolloSG isn't in my share menu", "share-missing"),
    ("How do I check a message?", "check-message"),
    ("Where do I check a message?", "check-message"),
    ("How do I check a phone number?", "check-number"),
    ("How do I check a link?", "check-link"),
    ("How do I check if a link is safe?", "check-link"),
    ("How do I check a file?", "check-app-file"),
    ("How do I check a screenshot?", "check-screenshot"),
    ("How do I check my wifi?", "check-device"),
    ("What can I ask Higgins?", "ask-higgins"),
    ("Where are settings?", "settings"),
    ("What are sample checks?", "sample-checks"),
    ("Where do I see my past threats?", "threats-list"),
    ("How do I delete a case?", "delete-cases"),
    ("How do I delete my data?", "delete-data"),
    ("Where is patrol history?", "patrol-history"),
    ("How do I export my history?", "patrol-history"),
    ("How do I connect Gmail?", "connect-gmail"),
    ("How do I set up family sharing?", "family"),
    ("How do I turn on call screening?", "call-screening"),
    ("Can Apollo screen my calls?", "call-screening"),
    ("How do I search my cases?", "search-cases"),
    ("How do I trust a link?", "trusted-links"),
    ("What does barking mean?", "apollo-states"),
    ("how do i turn on notifications", "notifications"),
    ("What does ApolloSG keep about me?", "privacy"),
    ("how do I get help", "get-help"),
    ("What is ApolloSG?", "what-is-apollosg"),
])
def test_product_questions_find_the_right_topic(question, topic):
    found = user_guide.find_topics(question, limit=1)
    assert found and found[0].id == topic, (question, [t.id for t in user_guide.find_topics(question)])


@pytest.mark.parametrize("question", [
    "How do I spot a phishing email?",
    "How do I know if an email is really from my bank?",
    "What should I do if I've been scammed?",
    "How do phishing scams work?",
    "How do I report a scam?",
    "How do I protect myself from scams?",
    "Someone called claiming to be my bank",
    "I clicked a link I shouldn't have",
    "What scams are going around right now?",
    "Is my device protected?",
    "Which protections aren't on yet?",
    "What has Apollo found this week?",
    "How do I use the quantum teleporter feature?",
])
def test_scam_and_state_questions_are_not_answered_from_the_guide(question):
    assert user_guide.find_topics(question) == [], question


@pytest.mark.parametrize("question,expected", [
    ("How do I share something into ApolloSG?", True),
    ("Where is patrol history?", True),
    ("I can't find settings", True),
    ("How do I spot a fake delivery text?", False),
    ("How do I report a scam?", False),
    ("Is this Wi-Fi safe to use?", False),
])
def test_procedural_questions_are_recognised(question, expected):
    assert context_tools.procedural(question) is expected


# ── Higgins: the answer ──────────────────────────────────────────────────────

def test_answer_is_direct_first_then_numbered_steps_then_limits():
    reply = user_guide.guide_answer("How do I delete a case?")
    topic = user_guide.TOPIC_BY_ID["delete-cases"]
    paragraphs = reply["answer"].split("\n\n")
    assert paragraphs[0] == topic.answer
    assert paragraphs[1].startswith("1. Open Threats")
    assert paragraphs[-1].startswith("Note: Deleting needs a connection")
    assert reply["navigate"] == ["/(tabs)/patrol"]


def test_sharing_answer_is_the_procedure_not_a_dump():
    reply = presenter.sharing_help("How do I share something into ApolloSG?")
    assert reply["answer"].startswith("In the app where you see it, tap Share and choose ApolloSG.")
    assert "1. Open the message" in reply["answer"]
    assert len(reply["answer"]) < 900
    for unrelated in ("phishing", "Scamwatch", "privacy", "Magnum"):
        assert unrelated not in reply["answer"]
    assert reply["navigate"] == ["/(tabs)/ask"]


def test_sharing_trouble_gets_the_troubleshooting_topic():
    reply = presenter.sharing_help("ApolloSG isn't in my share menu")
    assert reply["answer"].startswith("Not every app offers Share")


def _from_apollo(message: str):
    plan = context_tools.classify_context(message)
    return asyncio.run(chat._from_apollo("guide-test-device", message, plan, None))


@pytest.mark.parametrize("question,topic", [
    ("How do I share something into ApolloSG?", "share-into"),
    ("How do I check a phone number?", "check-number"),
    ("How do I turn on call screening?", "call-screening"),
    ("Where is patrol history?", "patrol-history"),
])
def test_chat_answers_how_to_questions_from_the_guide_before_anything_else(question, topic):
    result = _from_apollo(question)
    assert result is not None
    reply, label, provenance = result
    assert label == "user_guide" and provenance == ["apollosg_user_guide"]
    assert reply["topic_id"] == topic
    assert reply["answer"].split("\n\n")[0] == user_guide.TOPIC_BY_ID[topic].answer


@pytest.mark.parametrize("question", [
    "How do I check a phone number?",
    "How do I check a suspicious email?",
    "Where do I check a message someone sent me?",
])
def test_how_to_questions_are_never_submitted_as_checks(question):
    assert chat._items_to_check(question) == []


def test_a_how_to_question_holding_a_real_link_or_number_is_still_checked():
    assert chat._items_to_check("How do I check this link https://bit.ly/x1y2z3?") == [{"kind": "url", "value": "https://bit.ly/x1y2z3"}]
    assert chat._items_to_check("Can you check this text: your parcel is held, pay the fee at our site now")[0]["kind"] == "text"

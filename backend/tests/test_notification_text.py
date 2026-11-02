"""Push notification text: entities decoded once at the push boundary, a purpose-built short summary, and the
authoritative event left untouched.

Run: cd /app/backend && python -m pytest tests/test_notification_text.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import PatrolEvent
from routers import push
from services.notification_text import decode_entities, owner_alert_summary, present_push

AT = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)


def _event(**extra) -> PatrolEvent:
    return PatrolEvent.model_validate({
        "event_id": "evt-12345678", "device_id": "device-12345678", "category": "link", "state": "growling", "status": "active",
        "headline": "This link to &quot;instagram.com-verify.top&quot; copies Instagram&#39;s login &amp; asks for your password",
        "what_happened": "Higgins&#39; full explanation: the page imitates Instagram &lt;login&gt; and was registered 3 days ago.",
        "why": ["It uses Instagram&#39;s logo &amp; colours."], "what_to_do": "Don&#39;t enter your password.",
        "indicator_host": "instagram.com-verify.top", "adapter_label": "device", "occurred_at": AT, "claimed_brand": "Instagram",
        "created_at": AT, "updated_at": AT, **extra})


@pytest.mark.parametrize("raw, shown", [
    ("&quot;instagram.com&quot;", '"instagram.com"'),
    ("AT&amp;T &amp; Telstra", "AT&T & Telstra"),
    ("Instagram&#39;s, Apollo&apos;s, it&#x27;s", "Instagram's, Apollo's, it's"),
    ("&lt;script&gt;", "<script>"),
    ("a&nbsp;b &ndash; c &mdash; d&hellip;", "a\xa0b – c — d…"),
    ("&#128680;", "🚨"),
    ("&amp;quot;paypal.com&amp;quot;", "&quot;paypal.com&quot;"),  # decoded once, never twice
    ("Tom & Jerry; &unknown;", "Tom & Jerry; &unknown;"),
])
def test_entities_decode_once(raw, shown):
    assert decode_entities(raw) == shown


def test_present_push_decodes_tidies_and_words_in_luddish_without_cutting_or_touching_the_input():
    data = {"title": "Apollo is growling at &quot;instagram.com&quot;", "message": "It&#39;s   from\n&lt;billing@x.co&gt;",
            "subtext": "Don&#39;t reply", "action_url": "/patrol/1?x=1&amp;y=2", "channel_id": "apollo_alerts"}
    before = dict(data)
    shown = present_push(data)
    assert shown["title"] == 'Apollo is growling at "instagram.com"'
    assert shown["message"] == "It's from <billing@x.co>"
    assert shown["subtext"] == "Don't reply"
    assert shown["action_url"] == data["action_url"], "only the text people read is presented"
    assert data == before
    long = present_push({"title": "Apollo is barking at " + "x" * 90, "message": "word " * 60})
    assert long["title"] == "Apollo is barking at " + "x" * 90 and long["message"].lower() == ("word " * 60).strip(), "nothing is cut short"
    # Whoever composed it, every notification reaches the phone in Higgins Luddish (the app's words).
    plain = present_push({"title": "t", "message": "The URL in the SMS message is malicious. Do not utilise the hyperlink."})
    assert plain["message"] == "The web address in the text message is harmful. Do not use the link."


def test_owner_alert_names_the_first_concrete_finding():
    assert owner_alert_summary(_event()) == ("Higgins: The Instagram link you sent has a warning sign: it uses Instagram's logo "
                                             "& colours. Open ApolloSG to see what I found.")
    assert owner_alert_summary(_event(category="message", background=True, state="barking")).startswith(
        "Higgins: The Instagram text you received looks like a scam: it uses Instagram")
    assert owner_alert_summary(_event(claimed_brand=None, why=[])).startswith("Higgins: The instagram.com-verify.top link you sent has signs")
    # A line about how the record was kept is never given as the reason.
    kept = owner_alert_summary(_event(why=["ApolloSG's servers keep only this privacy-protected summary, not the content that was checked."]))
    assert kept == "Higgins: The Instagram link you sent has signs that need checking. Open ApolloSG to see what I found."
    limited = owner_alert_summary(_event(state="ears_up", why=[], triage_investigation={"outcome": "LIMITED_UNABLE_TO_DETERMINE"}))
    assert limited.startswith("Higgins: I couldn't fully check the Instagram link you sent. Treat it with caution")
    assert "safe" not in limited.lower()
    assert present_push({"title": "t", "message": owner_alert_summary(_event(claimed_brand="AT&amp;T", category="email", background=True, why=[]))})[
        "message"] == "Higgins: The AT&T email you received has signs that need checking. Open ApolloSG to see what I found."
    sender = owner_alert_summary(_event(claimed_brand=None, category="email", background=True, why=[]), source={"sender": "billing@acme.co"})
    assert sender.startswith("Higgins: The email from billing@acme.co has signs")
    # A reason that starts with a name keeps its capital inside the sentence.
    listed = owner_alert_summary(_event(state="barking", why=["PhishTank lists this exact address."]))
    assert listed.startswith("Higgins: The Instagram link you sent looks like a scam: PhishTank lists this exact address.")


@pytest.mark.anyio
async def test_the_owner_push_carries_the_summary_and_the_event_keeps_the_full_explanation(monkeypatch):
    sent: list[dict] = []

    async def fake_send(recipients, data, idempotency_key=None, owner_id=None):
        sent.append(present_push(data))
        return []

    async def allow(*_args):
        return True

    async def no_quiet(*_args):
        return None

    monkeypatch.setattr(push, "send_push", fake_send)
    monkeypatch.setattr(push, "should_send_category", allow)
    monkeypatch.setattr(push, "device_quiet_until", no_quiet)
    event = _event(state="barking")
    before = event.model_dump()
    await push.push_owner_alert(event)
    assert sent and sent[0]["message"].startswith("Higgins: The Instagram link you sent looks like a scam: it uses Instagram's logo")
    assert "subtext" not in sent[0], "no second line of explanation in the notification"
    assert "registered 3 days ago" not in repr(sent[0]) and "&#39;" not in repr(sent[0])
    assert event.model_dump() == before
    assert event.what_happened.startswith("Higgins&#39; full explanation")

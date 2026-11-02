"""Higgins Plain-English Renderer and Fidelity Check (services/higgins/explain).

- The renderer explains a validated TC FlyBy or Magnum DI result in plain words, Apollo's wording only, and never
  changes the structured result.
- The Fidelity Check fails a draft that loses, adds or changes anything; the failing part is put back in Apollo's own
  wording and checked again; if it still fails the person sees Apollo's own wording only ("literal").
- The admin portal shows PASS/FAIL, what was shown, why, and both texts while the case is held.

Run: cd /app/backend && python -m pytest tests/test_plain_english.py -q
"""
from dataclasses import replace

import pytest

from services.higgins import explain
from services.higgins.contracts import ActionProposal, Finding, HigginsResponse
from services.higgins.explain import facts as facts_mod
from services.higgins.explain import fidelity, render
from services.higgins.explain import words as W

EXPLANATION = (
    "**What was found**\n- The link anz-secure-login.co was registered 3 days ago.\n\n"
    "**What it means**\nThe message uses ANZ's name, but the link does not go to ANZ's domain (anz.com.au). "
    "In order to protect your account, do not enter anything on it.\n\n"
    "**What Apollo's knowledge base adds** (general knowledge, not evidence about what you sent)\n"
    "- Scamwatch: “Bank impersonation scams” — https://www.scamwatch.gov.au/types-of-scams/phishing\n\n"
    "**How ApolloSG checked**\nTC FlyBy checked the submitted material using official source checks. "
    "Magnum DI's deeper analysis wasn't needed, because it couldn't change the outcome or what to do."
)


def _response(**over) -> HigginsResponse:
    base = dict(
        revision=1, overview="This uses ANZ's name, but its link goes to anz-secure-login.co, which isn't ANZ's domain. Don't use the link.",
        explanation_markdown=EXPLANATION, assessment="concern_found", outcome="concerning", attention="action_needed",
        attention_reason="Anything typed into that link goes to whoever runs anz-secure-login.co, not ANZ.",
        findings=[
            Finding(id="f1", text="The link anz-secure-login.co was registered 3 days ago.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="It asks you to pay $4.20 within 24 hours: “Pay now to avoid suspension”.", basis="observation",
                    confidence="medium", evidence_ids=["e1"]),
            Finding(id="f3", text="The sender is probably not ANZ, although the logo looks real.", basis="inference", confidence="low"),
        ],
        uncertainties=["Apollo is unable to confirm who actually sent this."],
        scope="TC FlyBy checked the submitted material using official source checks. Nothing was opened or fetched from the destination.",
        source_ids=["s1"],
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't use the link", instruction="Do not open anz-secure-login.co and do not enter anything on it."),
                 ActionProposal(id="a2", kind="instruction", label="Contact ANZ yourself", instruction="Contact ANZ using the number on your card.")],
        recommended_action_id="a1", completion="complete")
    base.update(over)
    return HigginsResponse(**base)


SOURCES = [{"id": "s1", "url": "https://www.scamwatch.gov.au/types-of-scams/phishing", "title": "Phishing scams", "authority": "official",
            "retrieval": "fetched"}]
ROUTING = {"tc_flyby": {"checks": [{"kind": "link", "route": "official_source", "status": "resolved"}]}}


def _facts(response=None, by="tc_flyby_official"):
    return facts_mod.build(response or _response(), answered_by=by, routing=ROUTING, sources=SOURCES)


def _codes(result) -> set[str]:
    return {f.code for f in result.failures}


# ── The renderer ─────────────────────────────────────────────────────────────
def test_a_tc_flyby_result_is_explained_in_plain_words_and_passes():
    plain = explain.explain(_response(), answered_by="tc_flyby_official", routing=ROUTING, sources=SOURCES)
    assert plain.mode == "plain" and plain.fidelity.status == "PASS" and plain.attempts == 1
    assert plain.result.startswith("Concerning.")
    assert plain.severity == W.SEVERITY["action_needed"]
    # Every finding, in order, with who established it and how firmly.
    assert [i.finding_id for i in plain.established] == ["f1", "f2", "f3"]
    assert plain.established[0].detail == "Seen directly by TC FlyBy · High confidence"
    assert plain.established[2].detail == "TC FlyBy's reading of the evidence, not seen directly · Low confidence"
    # Jargon is explained once, in Apollo's fixed words, beside the finding — never inside it.
    assert plain.established[0].explain in W.GLOSSARY_TEXTS
    # Plain words: formal phrases swapped, quotes and identifiers untouched.
    means = " ".join(plain.means)
    assert "In order to" not in means and "To protect your account, don't enter anything on it." in means
    assert "“Pay now to avoid suspension”" in plain.established[1].text and "$4.20" in plain.established[1].text
    assert "can't confirm" in plain.uncertain[0]
    # The knowledge-base caveat stays with what it labels.
    assert any(m.startswith("What Apollo's knowledge base adds (general knowledge, not evidence about what you sent):") for m in plain.means)
    # Each point once: the scope's repeat of the method sentence isn't said twice.
    assert sum("checked the submitted material" in h for h in plain.how) == 1
    # Every step is kept, one for one.
    assert plain.todo == ["Don't open anz-secure-login.co and don't enter anything on it.", "Contact ANZ using the number on your card."]


def test_the_structured_result_is_never_changed():
    response = _response()
    before = response.model_dump(exclude={"plain_english"})
    explain.explain(response, answered_by="tc_flyby_official", routing=ROUTING, sources=SOURCES)
    assert response.model_dump(exclude={"plain_english"}) == before


def test_a_magnum_di_result_credits_magnum_di():
    plain = explain.explain(_response(explanation_markdown="**What it means**\nThe request goes to an address nobody verified."),
                            answered_by="magnum_di", routing={}, sources=[])
    assert plain.mode == "plain"
    assert plain.established[0].detail.startswith("Seen directly by Magnum DI")


def test_a_general_question_has_nothing_to_explain():
    response = _response(outcome=None, assessment="no_concern_found_within_scope", attention="none", attention_reason=None, findings=[],
                         actions=[], recommended_action_id=None)
    assert explain.explain(response, answered_by="tc_flyby_kb", routing={}, sources=[]) is None


# ── The Fidelity Check catches every kind of change ──────────────────────────
@pytest.fixture
def setup():
    f = _facts()
    draft = render.render(f)
    assert fidelity.check(f, draft).status == "PASS"
    return f, draft


def _with_finding(draft, i, **over):
    established = list(draft.established)
    established[i] = replace(established[i], **over)
    return replace(draft, established=established)


@pytest.mark.parametrize("change, code", [
    (lambda d: replace(d, result=replace(d.result, text=d.result.text.replace("Concerning.", "Likely scam."))), "OUTCOME_CHANGED"),
    (lambda d: replace(d, severity=W.SEVERITY["review"]), "SEVERITY_CHANGED"),
    (lambda d: replace(d, established=d.established[:2]), "FINDING_DROPPED"),
    (lambda d: replace(d, established=list(reversed(d.established))), "FINDING_ORDER"),
    (lambda d: _with_finding(d, 0, text="The link anz-secure-login.co was registered 30 days ago."), "FINDING_ALTERED"),
    (lambda d: _with_finding(d, 2, text="The sender is probably ANZ, although the logo looks real."), "FINDING_ALTERED"),
    (lambda d: _with_finding(d, 0, detail="Seen directly by TC FlyBy · Medium confidence"), "CONFIDENCE_CHANGED"),
    (lambda d: _with_finding(d, 0, detail="Seen directly by Magnum DI · High confidence"), "BASIS_CHANGED"),
    (lambda d: _with_finding(d, 0, explain="This domain is new, so it's a scam."), "EXPLANATION_NOT_APOLLO"),
    (lambda d: _with_finding(d, 1, text="It asks you to pay $4.20 within 24 hours: “Pay now”."), "QUOTE_ALTERED"),
    (lambda d: replace(d, uncertain=[]), "STATEMENT_"),  # dropped, or nearest left altered
    (lambda d: replace(d, means=[*d.means, render.Item(ref="means:9", text="Your bank account has already been emptied.")]), "UNSUPPORTED_STATEMENT"),
    (lambda d: replace(d, todo=d.todo[:1]), "ACTION_DROPPED"),
    (lambda d: replace(d, todo=[replace(d.todo[0], text="Open anz-secure-login.co and check it."), d.todo[1]]), "ACTION_ALTERED"),
    (lambda d: replace(d, result=replace(d.result, text=d.result.text.replace("anz-secure-login.co", "the link"))), "STATEMENT_ALTERED"),
    (lambda d: replace(d, how=[*d.how, render.Item(ref="how:9", text="See https://evil.example.net for details.")]), "ENTITY_INVENTED"),
    (lambda d: _with_finding(d, 2, text="The sender is probably not ANZ, and the logo looks real."), "CONTRADICTION_DROPPED"),
    (lambda d: replace(d, matters=[replace(d.matters[0], text=d.matters[0].text + " This is definitely a scam.")]), "CERTAINTY_ADDED"),
    (lambda d: replace(d, uncertain=[replace(d.uncertain[0], text=d.uncertain[0].text + " It's probably harmless.")]), "SAFETY_CLAIM_ADDED"),
    (lambda d: replace(d, how=[*d.how, render.Item(ref="how:9", text="Magnum DI checked the submitted material.")]), "ATTRIBUTION_CHANGED"),
])
def test_the_fidelity_check_fails_a_changed_draft(setup, change, code):
    f, draft = setup
    result = fidelity.check(f, change(draft))
    assert result.status == "FAIL" and any(c.startswith(code) for c in _codes(result)), _codes(result)


def test_an_identifier_left_out_fails(setup):
    f, draft = setup
    changed = replace(draft, todo=[replace(draft.todo[1], text="Contact them using the number on your card."), draft.todo[0]][::-1])
    changed = replace(changed, means=[replace(m, text=m.text.replace("(anz.com.au)", "")) for m in changed.means])
    assert "ENTITY_DROPPED" in _codes(fidelity.check(f, changed))


def test_failure_details_carry_no_case_content(setup):
    f, draft = setup
    changed = replace(draft, how=[*draft.how, render.Item(ref="how:9", text="See https://evil.example.net for details.")])
    for failure in fidelity.check(f, changed).failures:
        assert "evil" not in failure.detail and "anz" not in failure.detail.lower()


# ── On FAIL: Apollo's own wording ────────────────────────────────────────────
def test_a_failed_part_is_repaired_in_apollos_own_wording(monkeypatch):
    real = render.plain
    monkeypatch.setattr(render, "plain", lambda text: real(text).replace("isn't", "is"))  # a renderer that drops a "not"
    plain = explain.explain(_response(), answered_by="tc_flyby_official", routing=ROUTING, sources=SOURCES)
    assert plain.mode == "repaired" and plain.fidelity.status == "PASS" and plain.attempts == 2
    assert plain.attempt_failures[0] and not plain.attempt_failures[1]
    assert "isn't ANZ's domain" in plain.result, "the failed part is shown in Apollo's own wording"


def test_still_failing_shows_apollos_wording_only(monkeypatch):
    real = render.render
    monkeypatch.setattr(render, "render", lambda f, literal=frozenset(): replace(real(f, literal), severity="How serious: nothing needs doing."))
    plain = explain.explain(_response(), answered_by="tc_flyby_official", routing=ROUTING, sources=SOURCES)
    assert plain.mode == "literal" and plain.fidelity.status == "FAIL"
    summary = explain.summary(plain, by="TC FlyBy", revision=1)
    assert summary["status"] == "FAIL" and summary["mode"] == "literal"
    assert summary["attemptFailures"][-1][0]["code"] == "SEVERITY_CHANGED"


def test_every_plain_swap_keeps_the_meaning():
    for formal, plain_words in W.PLAIN_SWAPS:
        sentence = f"Apollo {formal} the evidence about the link."
        assert fidelity.faithful(sentence, W.swap(sentence)), formal
    assert fidelity.canon("Apollo is unable to check it") == fidelity.canon("Apollo can't check it")


def test_every_severity_line_is_fixed_text_for_its_attention_level():
    assert set(W.SEVERITY) == {"none", "review", "action_needed", "urgent"}
    for text in [*W.SEVERITY.values(), *W.GLOSSARY_TEXTS]:
        assert not facts_mod.entities(text), "Apollo's fixed text adds no identifier"


# ── End to end: every committed result carries its checked plain English; the admin portal shows the check ──


@pytest.mark.anyio
async def test_a_committed_result_carries_checked_plain_english_and_the_portal_shows_it(monkeypatch):
    from starlette.requests import Request

    from routers import admin_portal
    from tests.test_tc_flyby_routing import _case, _gateway, _lookups

    _gateway(monkeypatch)
    _lookups(monkeypatch, verdict="malicious", threats=["SOCIAL_ENGINEERING"])
    _owner, case, response, _ = await _case([("text", "Your ANZ account is locked. Verify now: https://anz-verify.co/login")])
    plain = response["plainEnglish"]
    assert plain["mode"] == "plain" and plain["fidelity"]["status"] == "PASS"
    assert plain["result"].startswith("Confirmed scam or threat.")
    assert [i["findingId"] for i in plain["established"]] == [f["id"] for f in response["findings"]]
    fid = case["routing"]["fidelity"]
    assert fid["status"] == "PASS" and fid["mode"] == "plain" and fid["by"] == "TC FlyBy" and fid["revision"] == 1
    assert "anz" not in str(fid["attemptFailures"]).lower(), "the routing record holds no case content"

    async def admin(_request):
        return {"email": "owner@example.com", "name": "Owner"}

    async def no_audit(*_a, **_k):
        return None

    monkeypatch.setattr(admin_portal, "_admin", admin)
    monkeypatch.setattr(admin_portal, "_audit_log", no_audit)
    request = Request({"type": "http", "method": "GET", "path": "/api/admin/investigations-cost", "query_string": b"period=all", "headers": []})
    page = await admin_portal.investigations_cost_report(request)
    assert 'data-testid="fidelity-heading"' in page and "<th>Plain English</th>" in page and 'data-testid="fidelity-pass"' in page
    drill = await admin_portal.investigation_drilldown(request, case["case_id"])
    assert 'data-testid="fidelity-drilldown"' in drill and 'data-testid="fidelity-mode">Plain English shown<' in drill
    assert "data-testid='fidelity-apollo-text'" in drill and "data-testid='fidelity-plain-text'" in drill
    assert "Seen directly by TC FlyBy" in drill


@pytest.mark.anyio
async def test_the_portal_says_when_the_texts_have_left_the_server():
    from routers import admin_portal
    html = admin_portal._fidelity_drilldown_html({"routing": {"fidelity": {
        "status": "FAIL", "mode": "literal", "attempts": 2, "by": "Magnum DI", "revision": 1,
        "attemptFailures": [[{"code": "FINDING_ALTERED", "ref": "finding:0", "detail": ""}], [{"code": "SEVERITY_CHANGED", "ref": "severity", "detail": ""}]]}}})
    assert 'data-testid="fidelity-fail"' in html and "Apollo&#x27;s wording shown" in html
    assert "FINDING_ALTERED" in html and fidelity.describe("SEVERITY_CHANGED") in html.replace("&#x27;", "'")
    assert 'data-testid="fidelity-texts-gone"' in html

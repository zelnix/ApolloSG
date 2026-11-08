"""Higgins explanation quality & edge-case validation (ApolloSG PRD v2.3 - Higgins Luddish).

Covers the four primary edge-case scenarios (A-D) and the seven additional regression cases from the
developer instructions. Every case is run through the real, shared explanation pathway
(services.higgins.explain: facts.build -> render.render -> fidelity.check) with synthetic, locked
findings - never through a second engine, never with the verdict/score recomputed here.

Two mandatory evaluation categories, both deterministic (no LLM calls in this file - see
scripts/explanation_quality_evaluator.py for the optional, offline-only AI-assisted review):
  A. Evidence Fidelity - the Fidelity Check itself (status == "PASS") plus targeted extra checks for
     verdict/finding/entity/uncertainty/contradiction/action integrity.
  B. Explanation Quality - structural, deterministic checks for: leading with the conclusion,
     connecting related findings, explaining why evidence matters, distinguishing evidence types,
     handling uncertainty without implying suspicion or safety, avoiding repetition, and surfacing
     guidance when the locked result provides it.

Run: cd /app/backend && python -m pytest tests/test_higgins_explanation_narrative.py -q
"""
from services.higgins import explain
from services.higgins.contracts import ActionProposal, Finding, HigginsResponse
from services.higgins.explain import words as W

ROUTING = {"tc_flyby": {"checks": []}}


def _response(findings, overview, explanation_markdown, *, outcome, assessment, attention, attention_reason=None,
              uncertainties=None, actions=None, recommended_action_id=None) -> HigginsResponse:
    return HigginsResponse(
        revision=1, overview=overview, explanation_markdown=explanation_markdown, assessment=assessment,
        outcome=outcome, attention=attention, attention_reason=attention_reason, findings=findings,
        uncertainties=uncertainties or [], scope="TC Hawkeye checked the submitted material using official source checks.",
        source_ids=[], actions=actions or [], recommended_action_id=recommended_action_id, completion="complete")


def _explain(response: HigginsResponse):
    plain = explain.explain(response, answered_by="tc_flyby_official", routing=ROUTING, sources=[])
    assert plain is not None
    return plain


def _without_verdict_label(result: str) -> str:
    """`result`'s first sentence is always one of the four fixed outcome labels (e.g. "This is unlikely a
    scam."), which legitimately contains the word "scam" — strip it before scanning the rest for anything
    invented, so "unlikely a scam" can never be mistaken for an invented "likely a scam"."""
    return result.split(". ", 1)[1] if ". " in result else result


# ── Scenario A: SMS impersonation and shortened URLs ─────────────────────────
def _scenario_a():
    return _response(
        findings=[
            Finding(id="f1", text="The message claims to be from Australia Post.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="The shortened link expands to au-post-tracking.cc, which isn't Australia Post's domain (auspost.com.au).",
                    basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f3", text="au-post-tracking.cc was registered 12 hours ago.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f4", text="The investigation identified a credential-harvesting pattern.", basis="inference", confidence="medium", evidence_ids=["e1"]),
        ],
        overview="This claims to be from Australia Post, but the link goes to au-post-tracking.cc, which isn't Australia Post's domain. Don't use the link.",
        explanation_markdown=("**What it means**\nThe message claims to be from Australia Post, but the link does not go to "
                              "Australia Post's own domain.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted "
                              "material using official source checks."),
        outcome="concerning", assessment="concern_found", attention="action_needed",
        attention_reason="Anything typed into that link goes to whoever runs au-post-tracking.cc, not Australia Post.",
        uncertainties=["Apollo is unable to confirm who actually sent this."],
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't use the link",
                                 instruction="Do not open au-post-tracking.cc and do not enter anything on it."),
                 ActionProposal(id="a2", kind="instruction", label="Contact Australia Post yourself",
                                 instruction="Contact Australia Post using the number on their official website.")],
        recommended_action_id="a1")


def test_scenario_a_connects_the_mismatch_domain_age_and_pattern_to_one_concern():
    plain = _explain(_scenario_a())
    assert plain.fidelity.status == "PASS"
    assert plain.result.startswith("This is likely a scam.")
    connecting = next((m for m in plain.means if "Together" in m), None)
    assert connecting is not None, plain.means
    assert "organisation's name" in connecting and "set up shortly before" in connecting and "credential-harvesting" in connecting
    assert "verified" not in plain.result.lower() and "confirmed" not in plain.result.lower()
    assert not any("verified" in f.text.lower() for f in plain.established)
    assert "Don't open au-post-tracking.cc" in plain.todo[0]


# ── Scenario B: suspicious password-protected attachment ────────────────────
def _scenario_b():
    return _response(
        findings=[
            Finding(id="f1", text="The archive is a password-protected ZIP.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="The extracted filename ends in \".pdf.exe\".", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f3", text="The file produced suspicious YARA matches.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f4", text="Sandbox execution launches PowerShell and attempts an external connection.",
                    basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="This file is disguised as a PDF but is really a program, and it behaves like malware when run. Delete it.",
        explanation_markdown=("**What it means**\nThe apparent PDF is actually a program, and it behaves like malware once "
                              "run.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="scam", assessment="concern_found", attention="urgent",
        attention_reason="Opening this file runs a program that tries to reach outside your device.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Delete the file", instruction="Delete the attachment without opening it.")],
        recommended_action_id="a1")


def test_scenario_b_distinguishes_disguise_from_confirmed_control():
    plain = _explain(_scenario_b())
    assert plain.fidelity.status == "PASS"
    assert "really a program" in plain.result or "actually a program" in plain.result or "program" in plain.result
    connecting = next((m for m in plain.means if "Together" in m), None)
    assert connecting is not None and "disguise" in connecting and "run" in connecting
    full_text = " ".join([plain.result, *[f.text for f in plain.established], *plain.means])
    assert "command-and-control" not in full_text.lower() and "c2 server" not in full_text.lower()
    assert "confirmed communication with" not in full_text.lower()
    assert plain.todo == ["Delete the attachment without opening it."]


# ── Scenario C: Business Email Compromise ────────────────────────────────────
def _scenario_c():
    return _response(
        findings=[
            Finding(id="f1", text="SPF, DKIM and DMARC all pass for this message.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="The sender appears to be a company executive.", basis="inference", confidence="medium", evidence_ids=["e1"]),
            Finding(id="f3", text="The message requests an urgent wire transfer.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f4", text="The payment instructions bypass the established company procedure.",
                    basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="This message passes authentication but asks for an urgent wire transfer that bypasses normal "
                 "approval. Verify independently before paying.",
        explanation_markdown=("**What it means**\nPassing authentication doesn't establish that the executive personally "
                              "sent or authorised this request.\n\n**How ApolloSG checked**\nTC Hawkeye checked the "
                              "submitted material."),
        outcome="likely_scam", assessment="concern_found", attention="action_needed",
        attention_reason="Wire transfers that skip normal approval are a common way genuine-looking emails redirect money.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Verify independently",
                                 instruction="Confirm the request by phone, using a number you already have on file — not one from this message.")],
        recommended_action_id="a1")


def test_scenario_c_separates_passing_authentication_from_personal_authorisation():
    plain = _explain(_scenario_c())
    assert plain.fidelity.status == "PASS"
    joined_means = " ".join(plain.means)
    # Apollo's own authored reason ("doesn't establish ... personally authorised") and the added fixed
    # connecting sentence ("technical path" / "approval") both land in "what it means" — together, not as
    # a caption on one finding.
    assert "doesn't establish that the executive personally" in joined_means
    assert "technical path" in joined_means and "approval" in joined_means
    full_text = " ".join([plain.result, *[f.text for f in plain.established], *plain.means])
    assert "account was compromised" not in full_text.lower() and "account has been compromised" not in full_text.lower()
    assert "Confirm the request by phone" in plain.todo[0] and "not one from this message" in plain.todo[0]


# ── Scenario D: incomplete delivery notification ─────────────────────────────
def _scenario_d():
    return _response(
        findings=[Finding(id="f1", text="The message is a short delivery notification with no extractable link.",
                          basis="observation", confidence="low", evidence_ids=[])],
        overview="There is not enough information in this short message to reach a reliable conclusion.",
        explanation_markdown=("**What it means**\nThere is not enough information here to check anything meaningful.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material using official source checks."),
        outcome="unlikely_scam", assessment="uncertain", attention="review",
        attention_reason="Too little was provided to check anything meaningful.",
        uncertainties=["Apollo could not find a link, sender information or any other identifying detail to check."])


def test_scenario_d_states_limitations_without_inventing_suspicion():
    plain = _explain(_scenario_d())
    assert plain.fidelity.status == "PASS"
    assert "enough information" in plain.result.lower()
    full_text = " ".join([_without_verdict_label(plain.result), *[f.text for f in plain.established], *plain.means])
    for word in ("suspicious", "malicious", "dangerous", "scam pattern", "phishing"):
        assert word not in full_text.lower(), word
    assert plain.uncertain and "identifying detail" in plain.uncertain[0]
    from services.higgins import outcomes
    assert plain.result.startswith(tuple(outcomes.LABELS.values()))


# ── Additional regression cases (developer instructions §4) ─────────────────
def test_a_legitimate_organisation_with_compromised_website_content_keeps_both_sides_visible():
    """A real organisation's own, official domain — but the content found there is concerning. Favourable
    (official domain) and concerning (malicious content) evidence must both stay visible, and the official
    domain must not be read as proof the content is safe."""
    resp = _response(
        findings=[
            Finding(id="f1", text="example-bank.com.au is the organisation's official domain.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="Google Safe Browsing lists a page on example-bank.com.au as malicious.", basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="This is the organisation's own domain, but one of its pages is currently listed as malicious — likely compromised.",
        explanation_markdown=("**What it means**\nA genuine domain can still be compromised and used to host malicious "
                              "content.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="likely_scam", assessment="concern_found", attention="action_needed",
        attention_reason="A listed page can be used to deliver malware or collect details even on a genuine domain.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Avoid the page", instruction="Don't open that page until the organisation confirms it's been fixed.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    texts = [f.text for f in plain.established]
    assert any("official domain" in t for t in texts) and any("malicious" in t for t in texts)
    assert "compromised" in " ".join(plain.means).lower() or "compromised" in plain.result.lower()


def test_a_threat_intelligence_no_match_is_not_read_as_proof_of_safety():
    resp = _response(
        findings=[Finding(id="f1", text="No scam warnings were found for this number.", basis="observation", confidence="medium", evidence_ids=["e1"])],
        overview="Apollo found no existing scam reports for this number, but that alone doesn't establish it's safe.",
        explanation_markdown=("**What it means**\nNo match in ApolloSG's sources doesn't establish the number is safe — only "
                              "that nothing has been reported yet.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted "
                              "material using official source checks."),
        outcome="unlikely_scam", assessment="no_concern_found_within_scope", attention="none")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    full_text = plain.result.lower()
    assert "doesn't establish" in full_text or "does not establish" in full_text or "doesn't mean" in full_text


def test_conflicting_authoritative_findings_are_both_kept_not_collapsed():
    resp = _response(
        findings=[
            Finding(id="f1", text="example-shop.test is not listed by Google Safe Browsing.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="ASIC's investor alert list names example-shop.test as a known scam.", basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="One source finds nothing against this site, but ASIC's own alert list names it directly — the direct, specific listing carries more weight.",
        explanation_markdown=("**What it means**\nOne source clearing a site doesn't outweigh another, more specific source naming "
                              "it directly.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="scam", assessment="concern_found", attention="urgent",
        attention_reason="ASIC's own alert list is a direct, specific identification of this site as a scam.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Stay away from this site", instruction="Don't enter any details or make any payment on example-shop.test.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"  # Fidelity itself fails CONTRADICTION_DROPPED if either side vanished.
    texts = [f.text for f in plain.established]
    assert any("isn't listed" in t for t in texts) and any("ASIC" in t and "known scam" in t for t in texts)


def test_a_technically_authenticated_email_with_deceptive_instructions_standalone():
    resp = _response(
        findings=[
            Finding(id="f1", text="SPF, DKIM and DMARC all pass for this message.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="The message asks you to update your billing details at a link that isn't the organisation's domain.",
                    basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="This message passes authentication, but the link it gives for billing details isn't the organisation's own domain.",
        explanation_markdown=("**What it means**\nPassing authentication confirms the technical path, not what the message is "
                              "really asking you to do.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="likely_scam", assessment="concern_found", attention="action_needed",
        attention_reason="The billing link doesn't go to the organisation's own domain.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't use that link", instruction="Go to the organisation's own website directly instead of using the link.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    assert "passes" in plain.result.lower() or "pass" in plain.result.lower()
    assert "isn't the organisation's own domain" in plain.result


def test_a_benign_message_with_no_scam_indicators_reads_plainly():
    resp = _response(
        findings=[Finding(id="f1", text="This is a routine appointment reminder with no link, request or urgency.",
                          basis="observation", confidence="high", evidence_ids=["e1"])],
        overview="This looks like a routine appointment reminder, with no link, request or urgency.",
        explanation_markdown=("**What it means**\nNothing here asks for money, details or urgent action.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="unlikely_scam", assessment="no_concern_found_within_scope", attention="none")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    full_text = " ".join([_without_verdict_label(plain.result), *[f.text for f in plain.established], *plain.means]).lower()
    for word in ("scam", "suspicious", "malicious", "fraud"):
        assert word not in full_text, word


def test_an_unavailable_critical_check_is_not_read_as_suspicious():
    resp = _response(
        findings=[Finding(id="f1", text="Google Safe Browsing was unavailable for this link.", basis="observation", confidence="medium", evidence_ids=["e1"])],
        overview="A key check couldn't be completed, so Apollo can't give a full answer on this link.",
        explanation_markdown=("**What it means**\nA check that couldn't run isn't the same as a check that found something "
                              "wrong.\n\n**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="unlikely_scam", assessment="uncertain", attention="review",
        attention_reason="Without this check, Apollo can't rule out a problem with this link.",
        uncertainties=["Apollo could not complete the reputation check for this link."])
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    full_text = " ".join([_without_verdict_label(plain.result), *[f.text for f in plain.established], *plain.means]).lower()
    assert "isn't the same as a check that found something wrong" in full_text or "unavailable" in full_text
    for word in ("suspicious", "malicious", "likely a scam", "this is a scam"):
        assert word not in full_text, word


def test_several_independent_findings_reinforcing_the_same_conclusion_are_all_kept():
    resp = _response(
        findings=[
            Finding(id="f1", text="This isn't the organisation's official domain.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="Google Safe Browsing lists this domain as a phishing site.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f3", text="example-fake.test was registered 2 days ago.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f4", text="The investigation identified a credential-harvesting pattern.", basis="inference", confidence="medium", evidence_ids=["e1"]),
        ],
        overview="Four independent checks all point the same way: this is not the organisation's site, and it's built to collect logins.",
        explanation_markdown=("**What it means**\nFour independent signs all point the same way.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material."),
        outcome="scam", assessment="concern_found", attention="urgent",
        attention_reason="Every one of these checks points the same way: this collects logins for someone else.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't use this site", instruction="Don't enter any details on example-fake.test.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    assert len(plain.established) == 4
    connecting = [m for m in plain.means if "Together" in m or m in W.SIGNIFICANCE.values()]
    # Avoids unnecessary repetition: at most one connecting/significance sentence is added, never one per finding.
    assert len(connecting) <= 1
    assert connecting, plain.means

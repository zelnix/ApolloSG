"""Higgins explanation quality & edge-case validation (ApolloSG PRD v2.3 - Higgins Luddish).

Covers the four primary edge-case scenarios (A-D), the seven additional regression cases from the
developer instructions, and the ABC News newsletter taken through five evidence states (legitimate,
lookalike sender, confirmed scam, contradictory, incomplete). Every case is run through the real, shared explanation pathway
(services.higgins.explain: facts.build -> render.render -> fidelity.check) with synthetic, locked
findings - never through a second engine, never with the verdict/score recomputed here.

Two mandatory evaluation categories, both deterministic (no LLM calls in this file - see
tests/explanation_quality_evaluator.py for the optional, offline-only AI-assisted review):
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


# ── The ABC News newsletter (ApolloSG PRD v2.3 edge case): favourable evidence synthesised gracefully ──
# The same real-world subject taken through five evidence states. The one line of reasoning Higgins adds must
# read like a knowledgeable person explaining the investigation whichever way the evidence went — never a list
# of captions, never two syntheses at once, and never a check that couldn't run read as a warning sign.
SYNTHESES = (W.GENERIC_CONCERN_SYNTHESIS, W.GENERIC_CLEAR_SYNTHESIS, *W.SIGNIFICANCE.values(), *(s for _, s in W.CONNECTIONS))


def _one_synthesis_at_most(plain) -> list[str]:
    added = [m for m in plain.means if m in SYNTHESES]
    assert len(added) <= 1, plain.means
    return added


def _abc_official_sender():
    return Finding(id="f1", text="The sender address newsletter@abc.net.au uses abc.net.au, which is the ABC's official domain.",
                   basis="observation", confidence="high", evidence_ids=["e1"])


def _abc_authenticated():
    return Finding(id="f2", text="SPF, DKIM and DMARC all pass for this message.", basis="observation", confidence="high", evidence_ids=["e1"])


def test_abc_newsletter_legitimate_favourable_evidence_is_synthesised_not_listed():
    resp = _response(
        findings=[
            _abc_official_sender(), _abc_authenticated(),
            Finding(id="f3", text="Every link in the email goes to abc.net.au.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f4", text="abc.net.au isn't listed by Google Safe Browsing, PhishTank or Apollo's blocklist.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f5", text="The email asks for nothing: no login, no payment and no urgent action.", basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="This is the ABC's own newsletter: it was sent from the ABC's official domain, its links go there too, and it asks for nothing.",
        explanation_markdown=("**What it means**\nNothing here points away from the ABC: the sender, the links and the message itself all line up.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material using official source checks."),
        outcome="not_scam", assessment="no_concern_found_within_scope", attention="none")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    assert plain.result.startswith("This is not a scam.")
    assert len(plain.established) == 5  # every favourable finding stays visible, none collapsed into the verdict
    # Three favourable checks (official domain, authentication, clean listing) share a direction but form no named
    # combination: the one generic "these agree" sentence connects them, instead of a caption per finding.
    assert _one_synthesis_at_most(plain) == [W.GENERIC_CLEAR_SYNTHESIS]
    assert W.UNAVAILABLE_CAVEAT not in plain.means
    full_text = " ".join([_without_verdict_label(plain.result), *[f.text for f in plain.established], *plain.means]).lower()
    for word in ("suspicious", "malicious", "likely a scam", "warning sign:"):
        assert word not in full_text, word
    assert plain.todo == []


def test_abc_newsletter_lookalike_sender_connects_the_name_and_the_new_address():
    resp = _response(
        findings=[
            Finding(id="f1", text="The sender address news@abc-newsletters.info uses abc-newsletters.info, which isn't the ABC's domain (abc.net.au).",
                    basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="abc-newsletters.info was registered 9 days ago.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f3", text="The email asks you to confirm your subscription by signing in through its link.", basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="This carries the ABC's name, but it wasn't sent from the ABC's domain, and the address it uses was set up 9 days ago. Don't sign in through its link.",
        explanation_markdown=("**What it means**\nThe ABC's name is on the message, but nothing about where it came from is the ABC's.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material using official source checks."),
        outcome="likely_scam", assessment="concern_found", attention="action_needed",
        attention_reason="Anything typed into that sign-in page goes to whoever runs abc-newsletters.info, not the ABC.",
        uncertainties=["Apollo is unable to confirm who actually sent this."],
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't sign in through the link", instruction="Do not sign in through the link in this email."),
                 ActionProposal(id="a2", kind="instruction", label="Go to the ABC yourself", instruction="Manage your subscription by typing abc.net.au into your browser yourself.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    assert plain.result.startswith("This is likely a scam.")
    assert "isn't ABC's" in plain.subject  # the ABC is only named — never called the owner of a lookalike
    [connecting] = _one_synthesis_at_most(plain)
    assert "Together" in connecting and "organisation's name" in connecting and "set up shortly before" in connecting
    assert "confirmed" not in plain.result.lower() and "verified" not in plain.result.lower()
    assert plain.uncertain == ["Apollo can't confirm who actually sent this."]
    assert plain.todo[0] == "Don't sign in through the link in this email."


def test_abc_newsletter_confirmed_scam_leads_with_the_listing_and_keeps_the_inference_marked():
    resp = _response(
        findings=[
            Finding(id="f1", text="The sender address news@abc-newsletters.info uses abc-newsletters.info, which isn't the ABC's domain (abc.net.au).",
                    basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f2", text="Google Safe Browsing lists abc-newsletters.info as a phishing site.", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f3", text="The investigation identified a credential-harvesting pattern.", basis="inference", confidence="medium", evidence_ids=["e1"]),
        ],
        overview="This is a scam: it carries the ABC's name, but the address behind it is already listed as a phishing site. Don't use the link.",
        explanation_markdown=("**What it means**\nA site already listed as phishing, sent under a name that isn't its own, is built to collect logins.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material using official source checks."),
        outcome="scam", assessment="concern_found", attention="urgent",
        attention_reason="Anything entered on abc-newsletters.info goes to whoever runs that phishing site.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't use the link", instruction="Do not open abc-newsletters.info and do not enter anything on it.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    assert plain.result.startswith("This is a scam.")
    texts = [f.text for f in plain.established]
    assert any("lists abc-newsletters.info as a phishing site" in t for t in texts)
    # Evidence types stay distinguishable: the pattern match is marked as TC Hawkeye's reading, not a direct observation.
    pattern = next(f for f in plain.established if "credential-harvesting" in f.text)
    assert "reading of the evidence" in pattern.detail and "Medium confidence" in pattern.detail
    [connecting] = _one_synthesis_at_most(plain)
    assert "Together" in connecting and "credential-harvesting" in connecting
    assert plain.todo == ["Don't open abc-newsletters.info and don't enter anything on it."]


def test_abc_newsletter_contradictory_evidence_keeps_both_sides_and_the_concern_drives_the_reasoning():
    resp = _response(
        findings=[
            _abc_official_sender(), _abc_authenticated(),
            Finding(id="f3", text="One link in the email goes to abc-prizes.top, which isn't the ABC's domain (abc.net.au).", basis="observation", confidence="high", evidence_ids=["e1"]),
            Finding(id="f4", text="abc-prizes.top was registered 4 days ago.", basis="observation", confidence="high", evidence_ids=["e1"]),
        ],
        overview="The email itself came from the ABC's domain, but one of its links goes to abc-prizes.top, which isn't the ABC's and was set up 4 days ago. Don't use that link.",
        explanation_markdown=("**What it means**\nA message can come from a real sender and still carry a link that isn't theirs; the sender checks and the link checks point different ways here.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material using official source checks."),
        outcome="likely_scam", assessment="concern_found", attention="action_needed",
        attention_reason="Anything entered at abc-prizes.top goes to whoever runs it, not the ABC.",
        uncertainties=["Apollo is unable to say whether the ABC's own sending account was misused or the link was added another way."],
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't use that link", instruction="Do not open abc-prizes.top.")],
        recommended_action_id="a1")
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"  # CONTRADICTION_DROPPED would fail this if either side vanished
    assert plain.result.startswith("This is likely a scam.")
    texts = [f.text for f in plain.established]
    assert any("is the ABC's official domain" in t for t in texts) and any("SPF, DKIM and DMARC all pass" in t for t in texts)
    assert any("isn't the ABC's domain" in t for t in texts) and any("registered 4 days ago" in t for t in texts)
    assert any("point different ways" in m for m in plain.means)  # Apollo's own reading of the conflict is kept
    # The favourable sender checks never produce a second, favourable synthesis beside the concern: one line of reasoning.
    [connecting] = _one_synthesis_at_most(plain)
    assert "Together" in connecting and "set up shortly before" in connecting
    assert W.GENERIC_CLEAR_SYNTHESIS not in plain.means
    assert any("misused" in u for u in plain.uncertain)


def test_abc_newsletter_incomplete_checks_are_a_caveat_beside_the_favourable_evidence_not_a_warning():
    resp = _response(
        findings=[
            _abc_official_sender(),
            Finding(id="f2", text="Google Safe Browsing was unavailable for the links in this email.", basis="observation", confidence="medium", evidence_ids=["e1"]),
            Finding(id="f3", text="The email's registration record couldn't be read.", basis="observation", confidence="medium", evidence_ids=["e1"]),
        ],
        overview="The sender is the ABC's official domain, but two of Apollo's checks on the links couldn't be completed, so this isn't a full answer.",
        explanation_markdown=("**What it means**\nWhat could be checked points to the ABC; what couldn't be checked is simply unknown, not a warning sign.\n\n"
                              "**How ApolloSG checked**\nTC Hawkeye checked the submitted material using official source checks."),
        outcome="unlikely_scam", assessment="uncertain", attention="review",
        attention_reason="Without the link checks, Apollo can't rule out a problem with the links.",
        uncertainties=["Apollo could not complete the reputation check for the links in this email."])
    plain = _explain(resp)
    assert plain.fidelity.status == "PASS"
    assert len(plain.established) == 3
    # The two additions are independent (PER-11): why the one completed check matters, and that the two that
    # couldn't run are not warning signs. Both appear; neither is a caption on a finding.
    assert _one_synthesis_at_most(plain) == [W.SIGNIFICANCE[("official_domain", "OFFICIAL")]]
    assert W.UNAVAILABLE_CAVEAT in plain.means
    assert not any(f.explain and f.explain in SYNTHESES for f in plain.established)
    full_text = " ".join([_without_verdict_label(plain.result), *[f.text for f in plain.established], *plain.means]).lower()
    for word in ("suspicious", "malicious", "likely a scam", "this is a scam"):
        assert word not in full_text, word
    assert plain.uncertain == ["Apollo couldn't complete the reputation check for the links in this email."]

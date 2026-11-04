"""Higgins says exactly what the evidence establishes, and nothing broader (the seven wording corrections in
memory/higgins_wording_review.md). EXPLAIN-layer wording only: each test also shows the outcome, attention and
settlement are what they were.

Run: cd /app/backend && python -m pytest tests/test_higgins_wording.py -q
"""
from services.higgins import presenter
from services.higgins.explain import words
from services.higgins.tc_flyby import decide, report, triage
from services.higgins.tc_flyby.official import fact

MATERIAL = {"item-0": ""}


def _plan(material: str, question: str = "Is this real?") -> triage.Plan:
    plan = triage.plan(question, [material])
    MATERIAL["item-0"] = material
    return plan


def _check(plan: triage.Plan, kind: str) -> triage.Check:
    return next(c for c in plan.checks if c.kind == kind)


def _resolve(check: triage.Check, *facts: dict) -> None:
    check.facts += list(facts)
    check.status = "resolved"


def _listed_clean(host: str) -> dict:
    return fact(f"{host} is not listed by Google Safe Browsing or Apollo's blocklist.", "clear", topic="listing")


def _registered(domain: str, young: bool) -> dict:
    return fact(f"{domain} was registered on {'2026-10-20' if young else '2015-01-01'}.", "weak" if young else "neutral", topic="registration")


def _means(result: dict) -> str:
    return result["explanationMarkdown"].split("**What it means**\n", 1)[1].split("\n\n", 1)[0]


# 1. A verified official domain settles who the address belongs to — that check only.
def test_a_verified_official_domain_settles_only_that_check():
    plan = _plan("https://www.ato.gov.au/individuals", "Is this link safe?")
    _resolve(_check(plan, "link"), fact("ato.gov.au is the Australian Taxation Office's official domain.", "clear", decisive=True, topic="official_domain"))
    _resolve(_check(plan, "impersonation"), fact("Every link and address in the material uses ato.gov.au, the ATO's official domain.", "clear",
                                                 topic="official_domains"))
    decision, issues = decide.evaluate(plan, MATERIAL, final=True)
    assert issues == [] and decision.outcome == "no_scam_indicators", "settlement unchanged"
    result = report.compose(decision, plan, MATERIAL, "flyby-1")
    assert result["overview"] == ("ato.gov.au is the Australian Taxation Office's official domain. That settles who the address belongs to, "
                                  "and none of Apollo's other checks found a warning sign.")
    assert "nothing here needs action" not in result["explanationMarkdown"] + result["overview"]
    assert result["attention"] == "none" and result["actions"] == [] and result["outcome"] == "no_scam_indicators"
    # With no other check, it says only what the one check settled.
    plan.checks = [_check(plan, "link")]
    alone = report.clear(plan, plan.checks, MATERIAL, "flyby-1", "tc_flyby_official")
    assert alone["overview"] == "ato.gov.au is the Australian Taxation Office's official domain. That settles who the address belongs to."


# 2. "Apollo checked …" names only the checks that ran.
def test_a_clear_message_names_only_what_was_checked():
    plan = _plan("Hi, it's Dan. The slides are at https://slides-deck.net/deck and you can call me on 0412 345 678.")
    _resolve(_check(plan, "link"), _listed_clean("slides-deck.net"), _registered("slides-deck.net", young=False))
    _resolve(_check(plan, "phone"), fact("IPQualityScore gives 0412 345 678 a fraud score of 10/100 (carrier: Telstra).", "neutral"))
    _resolve(_check(plan, "scam_alerts"))
    result = report.clear(plan, plan.checks, MATERIAL, "flyby-1", "tc_flyby_official")
    assert _means(result).startswith("Apollo checked the link and the phone number in it, and compared it with the official scam alerts "
                                     "ApolloSG holds. Checks like these can't confirm who sent it")
    assert "addresses and names" not in result["explanationMarkdown"]

    nothing = _plan("Hey, are we still on for dinner on Friday? Let me know what time suits.")
    _resolve(_check(nothing, "scam_alerts"))
    assert _means(report.clear(nothing, nothing.checks, MATERIAL, "flyby-1", "tc_flyby_kb")).startswith(
        "Apollo found no links, numbers, addresses or names in it to look up, so it compared it with the official scam alerts ApolloSG holds.")
    # A check that didn't run (not needed, unavailable) is never named as checked.
    _check(plan, "phone").status = "unavailable"
    assert "phone number" not in _means(report.clear(plan, plan.checks, MATERIAL, "flyby-1", "tc_flyby_official"))


# 3. Corroborated impersonation says what was established about the address, not a general claim.
def _impersonation_plan() -> triage.Plan:
    plan = _plan("CommBank: please read the notice about your account changes at https://commbank-notice.net/info")
    impersonation = _check(plan, "impersonation")
    impersonation.facts.append(fact("commbank-notice.net carries CommBank's name, but it is not CommBank's domain (commbank.com.au) — the name has other words added to it.", "anomaly",
                                    topic="lookalike") | {"place": "commbank-notice.net"})
    impersonation.status = "needs_reasoning"
    _resolve(_check(plan, "link"), _listed_clean("commbank-notice.net"), _registered("commbank-notice.net", young=True))
    return plan


def test_corroborated_impersonation_says_only_what_was_established():
    plan = _impersonation_plan()
    found = decide.provisional(plan)
    assert (found.outcome, found.basis) == ("concerning", "impersonation"), "settlement unchanged"
    result = report.compose(found, plan, MATERIAL, "flyby-1")
    assert _means(result) == ("commbank-notice.net isn't one of CommBank's published domains, and a separate check on that address backs up "
                              "the concern. That's enough to treat it as concerning without weighing up the wording.")
    assert result["attentionReason"] == ("Anything typed into that link goes to whoever runs commbank-notice.net, which isn't one of CommBank's "
                                         "published domains.")
    assert "no reason to send you" not in result["explanationMarkdown"] and ", not CommBank." not in result["attentionReason"]
    assert result["outcome"] == "concerning" and result["attention"] == "action_needed" and result["actions"][0]["label"] == "Don't use the link"


# 4. Weak signals listed beside warning signs are never called warning signs.
def _signals_plan(weak: int, claims: int = 1) -> triage.Plan:
    plan = _plan("Apex Growth offers guaranteed returns of 12% per month. Join at https://apex-growth.io/join")
    claim = _check(plan, "claim")
    for n in range(claims):
        claim.facts.append(fact(f"The material promises guaranteed returns ({n + 1}). Scamwatch lists over-the-top promises as a warning sign.",
                                "anomaly", topic="claim"))
    claim.status = "resolved"
    link = _check(plan, "link")
    _resolve(link, _listed_clean("apex-growth.io"), _registered("apex-growth.io", young=weak > 0))
    for n in range(weak - 1):
        link.facts.append(fact(f"The link redirects to another site ({n + 1}).", "weak", topic="redirect"))
    return plan


def test_weak_signals_are_never_called_warning_signs():
    plan = _signals_plan(weak=0)
    assert decide.provisional(plan).basis == "signals", "settlement unchanged"
    assert _means(report.compose(decide.provisional(plan), plan, MATERIAL, "flyby-1")).startswith(
        "Apollo's checks established the warning sign above. That's reason to be careful")

    plan = _signals_plan(weak=1)
    result = report.compose(decide.provisional(plan), plan, MATERIAL, "flyby-1")
    assert result["findings"][0]["text"].startswith("The material promises") and "registered on" in result["findings"][1]["text"]
    assert _means(result) == ("Apollo's checks established the first finding above as a warning sign. The other finding is recorded too, but "
                              "doesn't count as a warning sign on its own. That's reason to be careful, but not enough to call it a scam.")
    assert result["outcome"] == "concerning" and result["attention"] == "review"

    plan = _signals_plan(weak=2, claims=2)
    assert _means(report.compose(decide.provisional(plan), plan, MATERIAL, "flyby-1")).startswith(
        "Apollo's checks established the first two findings above as warning signs. The other findings are recorded too, but don't count "
        "as warning signs on their own.")


# 5. "Unable to determine" says why: a gap only when something wasn't checked, weak signals when they were found.
def _bare_link(*facts: dict, unavailable: bool = False) -> triage.Plan:
    plan = _plan("https://fresh-deals.shop/promo", "Is this link safe?")
    link = _check(plan, "link")
    link.facts += list(facts)
    link.status = "unavailable" if unavailable else "resolved"
    return plan


def _undetermined(plan: triage.Plan) -> dict:
    decision, issues = decide.evaluate(plan, MATERIAL, final=True)
    assert issues == [] and decision.outcome == "unable_to_determine", "settlement unchanged"
    result = report.compose(decision, plan, MATERIAL, "flyby-1")
    assert result["attention"] == "review" and result["outcome"] == "unable_to_determine"
    return result


def test_unable_to_determine_with_only_weak_signals_names_no_gap():
    result = _undetermined(_bare_link(_listed_clean("fresh-deals.shop"), _registered("fresh-deals.shop", young=True)))
    assert result["overview"].startswith("ApolloSG couldn't establish enough about fresh-deals.shop to say either way. It found no warning "
                                         "signs, only a weak signal that isn't a concern on its own, but that isn't the same as it being safe")
    assert _means(result) == "A weak signal can't settle it either way, so the available evidence can't establish more."
    assert result["attentionReason"] == "What ApolloSG found can't show whether it's safe or not."
    assert "couldn't be checked" not in result["explanationMarkdown"] and "Nothing it found raises a concern" not in result["overview"]


def test_unable_to_determine_names_the_gap_when_something_couldnt_be_checked():
    result = _undetermined(_bare_link(fact("Google Safe Browsing could not be checked for fresh-deals.shop.", "missing", topic="listing")))
    assert "It found no warning signs, but that isn't the same as it being safe" in result["overview"]
    assert _means(result) == "Some of what would settle this couldn't be checked, so the available evidence can't establish more."
    assert result["attentionReason"] == "Something ApolloSG couldn't fully check may still be unsafe."

    both = _undetermined(_bare_link(fact("Google Safe Browsing could not be checked for fresh-deals.shop.", "missing", topic="listing"),
                                    _registered("fresh-deals.shop", young=True),
                                    fact("The link redirects to another site.", "weak", topic="redirect")))
    assert "only weak signals that aren't a concern on their own" in both["overview"]
    assert _means(both) == ("Some of what would settle this couldn't be checked and weak signals can't settle it either way, so the available "
                            "evidence can't establish more.")
    assert both["attentionReason"] == "Something ApolloSG couldn't fully check may still be unsafe."


# 6. A quiet Patrol state is never "all clear".
def test_a_quiet_patrol_state_is_never_all_clear():
    assert presenter.STATE_TEXT["resting"] == "no concern found within the checks that completed"
    record = presenter.patrol_record({"headline": "Link checked", "effectiveState": "resting"})
    findings = presenter.patrol_findings([{"headline": "Link checked", "effectiveState": "resting"}])
    for text in (record["answer"], findings["answer"]):
        assert "Link checked — no concern found within the checks that completed." in text and "all clear" not in text


# 7. The severity line for attention "none" covers only what Apollo found.
def test_the_none_severity_line_covers_only_what_apollo_found():
    assert words.SEVERITY["none"] == "How serious: nothing Apollo found needs action."
    assert not any("nothing needs doing" in line for line in words.SEVERITY.values())

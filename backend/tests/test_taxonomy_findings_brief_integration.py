"""End-to-end: report.compose() attaches a Master Scam Taxonomy classification and a Findings
Brief to a real TC Hawkeye result, and both survive the same ModelResponse/HigginsResponse
validation every other field goes through (Apollo PRD v2.2 Phases 2 and 5).

Reuses the exact plan/decision scenarios already proven in test_higgins_wording.py (corroborated
impersonation -> likely_scam, verified official domain -> not_scam) rather than inventing new
evidence setups, so this only exercises the new taxonomy/findingsBrief wiring.
"""
from services.higgins import validation
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


def _validate(result: dict):
    evidence_ids = set(MATERIAL) | {"flyby-1"}
    source_ids = set(result.get("sourceIds") or [])
    return validation.validate(result, revision=1, evidence_ids=evidence_ids, source_ids=source_ids,
                               capability_ids=set(), pending_question=None, provider_complete=True)


def _impersonation_plan() -> triage.Plan:
    plan = _plan("CommBank: please read the notice about your account changes at https://commbank-notice.net/info")
    impersonation = _check(plan, "impersonation")
    impersonation.facts.append(fact("commbank-notice.net carries CommBank's name, but it is not CommBank's domain (commbank.com.au) — the name has other words added to it.", "anomaly",
                                    topic="lookalike") | {"place": "commbank-notice.net"})
    impersonation.status = "needs_reasoning"
    _resolve(_check(plan, "link"), _listed_clean("commbank-notice.net"), _registered("commbank-notice.net", young=True))
    return plan


def test_a_corroborated_impersonation_result_carries_a_brand_impersonation_taxonomy_and_a_findings_brief():
    plan = _impersonation_plan()
    found = decide.provisional(plan)
    assert (found.outcome, found.basis) == ("likely_scam", "impersonation")
    result = report.compose(found, plan, MATERIAL, "flyby-1")

    assert result["findingsRating"] == result["findingsRatingBreakdown"]["rating"]
    assert result["taxonomy"] is not None
    assert result["taxonomy"]["primary"]["domainCode"] == 2  # Brand & Corporate Impersonation
    assert 126 <= int(result["taxonomy"]["primary"]["variantCode"]) <= 275

    brief = result["findingsBrief"]
    for header in ("finding", "findingsRating", "whatApolloFound", "whyThisMatters", "whatWasVerified", "recommendedAction"):
        assert header in brief
    assert brief["finding"] == "This is likely a scam"
    assert brief["findingsRating"] == result["findingsRating"]
    assert brief["taxonomy"] == result["taxonomy"]
    assert brief["whatApolloFound"], "the actual finding text should be listed"
    assert brief["recommendedAction"]["primary"]["label"] == "Don't use the link"

    model, errors = _validate(result)
    assert errors == [] and model is not None
    assert model.taxonomy == result["taxonomy"]
    assert model.findings_brief == result["findingsBrief"]


def test_a_verified_official_domain_result_has_no_taxonomy_and_a_not_scam_findings_brief():
    plan = _plan("https://www.ato.gov.au/individuals", "Is this link safe?")
    _resolve(_check(plan, "link"), fact("ato.gov.au is the Australian Taxation Office's official domain.", "clear", decisive=True, topic="official_domain"))
    _resolve(_check(plan, "impersonation"), fact("Every link and address in the material uses ato.gov.au, the ATO's official domain.", "clear",
                                                 topic="official_domains"))
    decision, issues = decide.evaluate(plan, MATERIAL, final=True)
    result = report.compose(decision, plan, MATERIAL, "flyby-1")
    assert result["outcome"] == "not_scam"
    assert result["taxonomy"] is None
    assert result["findingsBrief"]["finding"] == "This is not a scam"
    assert result["findingsBrief"]["taxonomy"] is None

    model, errors = _validate(result)
    assert errors == [] and model is not None

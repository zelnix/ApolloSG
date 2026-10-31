"""Brand and domain verification: an address that isn't an organisation's main domain is not, by itself, evidence
of impersonation. Only real lookalike signs and shared link services count as warning signs; an organisation's own
country sites and sub-sites are genuine; anything else can't be confirmed until something independent backs it up.

Run: cd /app/backend && python -m pytest tests/test_brand_domains.py -q
"""
import pytest

from services.higgins import brand_domains as bd
from services.higgins.indicators import read_indicators
from services.higgins.tc_flyby import official, triage
from services.higgins.tc_flyby.decide import corroborated_impersonation, provisional, signals


@pytest.mark.parametrize("place,kind", [
    ("ebay.com", "official"), ("www.ebay.com.au", "official"), ("pages.ebay.com.au", "official"), ("ebay.co.uk", "official"),
    ("ebaystatic.com", "official"), ("ebay.com.br", "country_site"), ("ebay.vn", "country_site"),
    ("ebay.onelink.me", "shared_service"), ("ebay-deals.web.app", "shared_service"),
    ("signin-ebay.com.au", "lookalike"), ("ebay-secure.net", "lookalike"), ("ebaysupport.com", "lookalike"),
    ("ebay.com.secure-login.example", "lookalike"), ("ebay.co", "lookalike"), ("ebay.xyz", "lookalike"),
    ("abc.net.au", "unrelated"), ("someone.onelink.me", "unrelated"),
])
def test_ebay_addresses_are_classified_by_real_signs_not_by_the_main_domain(place, kind):
    assert bd.classify("eBay", place)[0] == kind


def test_each_lookalike_says_which_sign_it_shows():
    assert bd.classify("eBay", "signin-ebay.com.au") == ("lookalike", "added_words")
    assert bd.classify("PayPal", "paypa1.com") == ("lookalike", "misspelt")
    assert bd.classify("Microsoft", "micr0soft-login.com") == ("lookalike", "misspelt")
    assert bd.classify("Netflix", "netfliix.com") == ("lookalike", "misspelt")
    assert bd.classify("eBay", "ebay.com.secure-login.example") == ("lookalike", "inside")
    assert bd.classify("CommBank", "commbank.co") == ("lookalike", "other_ending")
    assert bd.classify("CommBank", "commbank-notice.net") == ("lookalike", "added_words")


def test_country_sites_only_for_global_organisations_and_real_country_endings():
    assert bd.classify("Amazon", "amazon.com.mx")[0] == "country_site"
    assert bd.classify("Amazon", "amazon.co.jp")[0] == "official"
    assert bd.classify("CommBank", "commbank.co.nz")[0] == "lookalike", "an Australian bank's name on another country's ending isn't its site"
    assert bd.classify("eBay", "ebay.me")[0] == "lookalike", ".me is sold to anyone"
    assert bd.classify("Linkt", "linkt.com.au")[0] == "official"


def test_short_names_only_match_as_whole_words():
    assert bd.classify("ING", "trading.example.com")[0] == "unrelated"
    assert bd.classify("ANZ", "anz-verify.com")[0] == "lookalike"
    assert bd.classify("ANZ", "anz.co.nz")[0] == "official"


def test_same_organisation_and_owner():
    assert bd.owner("pages.ebay.com.au") == "eBay" and bd.owner("ebay.onelink.me") is None
    assert bd.same_organisation("www.ebay.com.au", "ebay.com") and bd.same_organisation("a.example.com", "b.example.com")
    assert not bd.same_organisation("ebay.com.au", "ebay.onelink.me")


EBAY_EMAIL = ("eBay: Sell your item fast. Start at https://www.ebay.com.au/sl/sell?mkevt=1&mkpid=2 or see "
              "https://pages.ebay.com.au/help/sell and download the app https://ebay.onelink.me/abc123")


async def _run_stage_one(text: str, pregathered: dict | None = None):
    plan = triage.plan("Is this real?", [text])

    async def clean(_u):
        return {"verdict": "clean", "threatTypes": [], "coverage": "full", "sources": [], "checkedAt": "2026-10-26T00:00:00+00:00"}

    async def old(_d):
        return {"registeredAt": "1995-08-01T00:00:00+00:00", "ageDays": 11000, "registrar": "x", "newlyRegistered": False}

    original = official.lookup_url, official.lookup_domain
    official.lookup_url, official.lookup_domain = clean, old
    try:
        await official.run(plan, pregathered, text)
    finally:
        official.lookup_url, official.lookup_domain = original
    return plan


@pytest.mark.anyio
async def test_ebays_own_country_site_and_sub_site_are_never_called_impersonation():
    plan = await _run_stage_one(EBAY_EMAIL, {"redirects": {"urls": {"https://www.ebay.com.au/sl/sell?mkevt=1&mkpid=2": {
        "chain": ["https://www.ebay.com.au/sl/sell?mkevt=1&mkpid=2", "https://www.ebay.com.au/splashui/challenge?ap=1&ru=https%3A%2F%2Fwww.ebay.com.au"]}}}})
    facts = [f for c in plan.checks for f in c.facts]
    texts = " ".join(f["text"] for f in facts)
    assert "ebay.com.au carries" not in texts and "is not eBay's domain" not in texts
    links = {c.subject: c for c in plan.checks if c.kind == "link"}
    assert any(f["decisive"] and f["signal"] == "clear" and "eBay's official domain" in f["text"] for f in links["ebay.com.au"].facts)
    redirect = next(f for f in links["ebay.com.au"].facts if f.get("topic") == "redirect")
    assert redirect["signal"] == "neutral" and redirect["text"].endswith("on the same site."), "a redirect within eBay's site isn't a warning sign"
    shared = [f for f in facts if f.get("topic") == "shared_service"]
    assert len(shared) == 1 and shared[0]["place"] == "ebay.onelink.me" and shared[0]["signal"] == "anomaly"
    assert "onelink.me, a link or website service anyone can use" in shared[0]["text"]
    assert [f["place"] for _, f in signals(plan) if f.get("place")] == ["ebay.onelink.me"], "the shared link service is the only warning sign"


@pytest.mark.anyio
async def test_only_ebays_own_addresses_raise_no_brand_warning():
    plan = await _run_stage_one("eBay: your listing is live at https://www.ebay.com.au/itm/1234 — manage it at https://pages.ebay.com.au/help")
    assert not [f for f in signals(plan)] and not corroborated_impersonation(plan) and provisional(plan) is None
    check = next(c for c in plan.checks if c.kind == "impersonation")
    assert check.status == "resolved" and "eBay's own domains (ebay.com.au)" in check.facts[0]["text"]


@pytest.mark.anyio
async def test_a_mismatch_without_a_lookalike_sign_is_not_a_warning_on_its_own():
    plan = await _run_stage_one("ING news: read about the rate change at https://www.abc.net.au/news/business")
    assert [f.get("topic") for c in plan.checks if c.kind == "impersonation" for f in c.facts] == ["impersonation"]
    assert not signals(plan) and provisional(plan) is None, "the main domain differing is not enough"


@pytest.mark.anyio
async def test_a_real_lookalike_is_still_a_warning_sign():
    plan = await _run_stage_one("eBay: confirm your account at https://signin-ebay.com.au/verify")
    found = [f for _, f in signals(plan)]
    assert any(f.get("topic") == "lookalike" and "the name has other words added to it" in f["text"] for f in found)
    assert provisional(plan).outcome == "concerning"


def test_preview_analysis_and_triage_engine_use_the_same_rule():
    ind = read_indicators(EBAY_EMAIL)
    assert [host for _, _, host in ind.mismatched] == ["ebay.onelink.me"]
    from services.triage_engine import _rule_evidence
    same = _rule_evidence({"sender_domain": "members.ebay.com", "link_domains": ["ebay.com.au", "pages.ebay.com.au"]}, [], {})
    assert same["brand_mismatch"] is False, "eBay's sender linking to eBay's country site is the same organisation"
    other = _rule_evidence({"sender_domain": "members.ebay.com", "link_domains": ["ebay-verify.example"]}, [], {})
    assert other["brand_mismatch"] is True

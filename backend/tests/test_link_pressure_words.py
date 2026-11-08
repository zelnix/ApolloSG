"""Urgency Tactics in a web address (owner, 2026-11-08): the words of an address itself that press the reader to act.

Read from the address alone, never from the page, no AI (services/higgins/tc_flyby/official.py PRESSURE_WORDS):
counted in the host's own name always, in the path only when the host carries an organisation's name, never on an
official domain. A weak signal like any other: alone or together never a scam, only the corroboration an
impersonation or another warning sign needs — and, through the explain layer, one connected line of reasoning
with the lookalike finding rather than a second caption.

Run: cd /app/backend && python -m pytest tests/test_link_pressure_words.py -q
"""
import pytest

from services.higgins.explain import facts, words as W
from services.higgins.tc_flyby import official
from services.higgins.tc_flyby.decide import corroborated_impersonation, provisional
from tests.test_brand_domains import _run_stage_one


def _pressure(plan):
    return [f for c in plan.checks if c.kind == "link" for f in c.facts if f.get("topic") == "pressure_words"]


@pytest.mark.parametrize("host,urls,branded,expected,shown", [
    ("commbank-cancel.co", ["http://commbank-cancel.co/stop"], True, ["cancel", "stop"], "commbank-cancel.co/stop"),
    ("commbank-cancel.co", ["http://commbank-cancel.co/stop"], False, ["cancel"], "commbank-cancel.co"),
    ("secure-verify-account.com", ["https://secure-verify-account.com/"], False, ["verify"], "secure-verify-account.com"),
    ("news-site.com", ["https://news-site.com/stop-press/2026"], False, [], "news-site.com"),
    ("example-shop.test", ["https://example-shop.test/cancellation-policy"], False, [], "example-shop.test"),
    ("anz-locked.net", ["https://anz-locked.net/verify/verify"], True, ["locked", "verify"], "anz-locked.net/verify/verify"),
])
def test_the_words_are_read_from_the_address_alone(host, urls, branded, expected, shown):
    assert official._pressure_words(host, urls, branded) == (expected, shown)


@pytest.mark.anyio
async def test_a_lookalike_address_with_pressure_words_records_one_weak_signal_that_corroborates_the_lookalike():
    plan = await _run_stage_one("http://commbank-cancel.co/stop")
    [found] = _pressure(plan)
    assert found["signal"] == "weak" and not found["decisive"]
    assert found["text"] == 'The web address itself uses the words “cancel” and “stop” (commbank-cancel.co/stop) — wording that presses you to act.'
    # It backs up the lookalike (the same link), so both reach the result's findings; the Finding stays what the
    # lookalike alone earns — a weak signal never makes something a scam.
    texts = [f["text"] for f in corroborated_impersonation(plan)]
    assert any("carries CommBank's name" in t for t in texts) and found["text"] in texts
    assert provisional(plan).outcome == "likely_scam"


@pytest.mark.anyio
async def test_an_official_domain_never_gets_the_signal_however_its_path_reads():
    plan = await _run_stage_one("Your CommBank card: https://www.commbank.com.au/support/cancel-a-card.html")
    assert _pressure(plan) == []


@pytest.mark.anyio
async def test_a_plain_address_counts_only_its_own_name_not_its_path():
    plan = await _run_stage_one("Read the article at https://news-site.com/stop-press/2026")
    assert _pressure(plan) == []


def test_the_explain_layer_reads_the_signal_as_a_concern_and_connects_it_to_the_lookalike():
    text = 'The web address itself uses the words “cancel” and “stop” (commbank-cancel.co/stop) — wording that presses you to act.'
    assert facts.classify(text) == ("pressure_words", "PRESSURE")
    lookalike = "commbank-cancel.co carries CommBank's name, but it is not CommBank's domain (commbank.com.au)."
    assert facts.classify(lookalike) == ("impersonation", "NOT_OFFICIAL")
    connection = W.pick_connection(frozenset({("impersonation", "NOT_OFFICIAL"), ("pressure_words", "PRESSURE")}))
    assert connection and "presses you to act" in connection and "organisation's name" in connection
    assert ("pressure_words", "PRESSURE") in W.SIGNIFICANCE

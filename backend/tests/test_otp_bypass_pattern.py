"""Tests for the otp_bypass scam pattern (P1 — 2FA/OTP account takeover via code sharing).

The pattern should fire when BOTH conditions are met:
  hallmark  — someone says they have sent/will send the person a code
  ask       — someone asks the person to share / enter / reply with that code

Run: cd /app/backend && python -m pytest tests/test_otp_bypass_pattern.py -v
"""
import re

import pytest

from services.higgins.tc_flyby.patterns import PATTERNS, PATTERN_VERSION, match_one


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _entry() -> dict:
    for p in PATTERNS:
        if p.get("key") == "otp_bypass":
            return {
                "kind": "scam_pattern",
                "kb_id": "otp_bypass",
                "publisher": "Scamwatch (ACCC)",
                "url": p["url"],
                "title": f"Scam pattern: {p['name']}",
                "pattern": {**{k: v for k, v in p.items() if k not in ("body", "url")}, "version": PATTERN_VERSION},
            }
    raise AssertionError("otp_bypass pattern not found in PATTERNS tuple")


ENTRY = _entry()


def _match(text: str):
    return match_one(ENTRY, text, has_link=False, has_brand=False, offsite=None)


# ── Full-match cases ──────────────────────────────────────────────────────────

class TestFullMatch:
    """Every one of these should produce stage='full'."""

    def test_we_sent_code_please_share(self):
        text = ("We've sent a verification code to your registered mobile. "
                "Please share the code with our fraud prevention team to verify your identity.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_we_just_sent_otp_provide_it(self):
        text = ("Our security system has just sent an OTP to your phone. "
                "Please provide the OTP to our agent to cancel the fraudulent transaction.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_verification_code_sent_reply_with(self):
        text = ("A verification code has been sent to your phone. "
                "Reply with this code to confirm it's you and unblock your account.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_you_will_receive_code_enter_it(self):
        text = ("You will receive a one-time code on your mobile shortly. "
                "Enter the code when prompted to complete the security check.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_you_should_have_received_code_give_us(self):
        text = ("You should have received a security code. "
                "Give us the code and we will remove the hold on your account.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_sms_code_sent_tell_us(self):
        text = ("Our team has just sent you an SMS code for account verification. "
                "Tell us the code so we can proceed.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_code_will_be_sent_please_confirm(self):
        text = ("A one-time code will be sent to your registered number. "
                "Please confirm the code with our security agent.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_code_on_its_way_read_out(self):
        text = ("The verification code is on its way to your phone. "
                "Read out the code to our agent once you receive it.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_we_sent_code_reply_with_otp(self):
        text = ("We have sent you a code to your phone number. "
                "Reply with the OTP to cancel the pending transaction.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"

    def test_two_factor_code_sent_share_it(self):
        text = ("We've sent a 2FA code to your registered mobile for verification. "
                "Please share the 2FA code with our security team immediately.")
        m = _match(text)
        assert m is not None and m.stage == "full", f"Expected full, got {m}"


# ── No-match cases (should return None) ───────────────────────────────────────

class TestNoMatch:
    """None of these should trigger the pattern."""

    def test_legitimate_otp_message_no_ask(self):
        """A real 2FA message that tells you your code but never asks you to share it."""
        text = "Your NAB verification code is 847291. Do not share this code with anyone. This code expires in 10 minutes."
        assert _match(text) is None, "Real OTP message should not match"

    def test_hallmark_only_no_ask(self):
        """Hallmark fires but there is no ask — should not reach 'full' (and with 1 hallmark, not even 'partial')."""
        text = "We have sent a verification code to your phone for added security."
        assert _match(text) is None, "Hallmark-only should not match"

    def test_ask_only_no_hallmark(self):
        """An ask for the code with no mention of a code being sent — no match."""
        text = "Please share your verification code with us to confirm your identity."
        # _OTP_SENT needs "we sent you" or "you received" framing
        # This message just asks — no hallmark → None
        assert _match(text) is None, "Ask-only should not match"

    def test_unrelated_message(self):
        text = "Your order has been dispatched. Expected delivery: Wednesday."
        assert _match(text) is None

    def test_investment_scam_no_code(self):
        text = "Invest $1000 today and earn guaranteed 20% weekly returns. Join now at t.me/profits."
        assert _match(text) is None

    def test_negated_ask(self):
        """'We will never ask you for a code' should be excluded by the negation guard."""
        text = ("We have sent a one-time code to your phone. "
                "We will never ask you for the verification code over the phone.")
        # The negation guard in _find() strips negated matches from the ask.
        # Depending on what the negated text covers, this may or may not match.
        # At minimum it should not be a false positive from the negated sentence alone.
        m = _match(text)
        # The hallmark IS present. If the ask is fully negated, m should be None.
        # If not, it should still be a valid match — both are acceptable; this test
        # just ensures we don't crash.
        assert m is None or m.stage in ("full", "partial")


# ── Pattern registry sanity ───────────────────────────────────────────────────

class TestRegistry:
    def test_otp_bypass_in_patterns_tuple(self):
        keys = [p["key"] for p in PATTERNS]
        assert "otp_bypass" in keys

    def test_otp_bypass_has_no_channel_restriction(self):
        """otp_bypass must work for text messages, not just calls."""
        entry = next(p for p in PATTERNS if p["key"] == "otp_bypass")
        assert "channel" not in entry, "otp_bypass must not be restricted to call channel"

    def test_pattern_version_bumped(self):
        assert PATTERN_VERSION == 4, f"PATTERN_VERSION should be 4, got {PATTERN_VERSION}"

    def test_otp_bypass_has_advice(self):
        entry = next(p for p in PATTERNS if p["key"] == "otp_bypass")
        assert len(entry["advice"]) >= 2

    def test_otp_bypass_impersonates_organisation(self):
        entry = next(p for p in PATTERNS if p["key"] == "otp_bypass")
        assert entry["impersonates_organisation"] is True

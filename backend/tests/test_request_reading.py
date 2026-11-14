"""Requests are read from what a sentence does, not from the words it contains (services/triage/requests.py)."""
import pytest

from services.triage import requests as rq

SAFE = [
    ("code delivery", "Your Microsoft verification code is 482913. Don't share this code with anyone."),
    ("code delivery with use", "Use 482913 to sign in to your Google Account. Google will never ask you for this code."),
    ("password changed notice", "Your password was changed on 3 May. If this was you, no action is needed. If you didn't make this change, reset your password at account.live.com."),
    ("new sign-in notice", "New sign-in to your account from Chrome on Windows. If it was you, you can ignore this message."),
    ("never share", "Reminder: we will never ask for your password, PIN or one-time code by email or phone. Never share your password."),
    ("discussion", "Five tips for creating a strong password, and why password managers help."),
    ("newsletter", "Read this week's stories. Manage your preferences or unsubscribe at any time."),
    ("no one will ask", "No one from CommBank will ever ask you to send your password or NetCode."),
    ("never, under any circumstances", "Never, under any circumstances, share your password with anyone."),
    ("never be asked", "You should never be asked to read out your verification code."),
]
SUSPICIOUS = [
    ("password disclosure", "Your mailbox is full. Reply with your email password so IT can increase your quota.", "secret_request"),
    ("enter password", "Verify your account by entering your password on the secure page below.", "secret_request"),
    ("send code", "We just sent you a 6-digit code. Please send the code back to us to confirm your booking.", "code_request"),
    ("read out code", "Hi, it's Telstra. Read me the verification code we texted you so I can fix your account.", "code_request"),
    ("code then read it back", "I've sent you a six-digit security code, read it back to me so I can fix your account.", "code_request"),
    ("card details", "Your parcel is held. Reply with your card number and CVV to pay the customs fee.", "card_request"),
    # A negation that belongs to something else never cancels the ask after it.
    ("unrelated negation first", "Do not delay, send me your password.", "secret_request"),
    ("negated event first", "Your password was not changed, send me your current password.", "secret_request"),
    ("don't worry", "Don't worry, just reply with the verification code we sent.", "code_request"),
    ("negated ask, then a real one", "Don't share it with anyone else, but send me your password now.", "secret_request"),
]


@pytest.mark.parametrize("name,text", SAFE)
def test_ordinary_security_mail_is_not_a_request_to_disclose(name, text):
    assert not rq.disclosure(rq.read(text)), name


@pytest.mark.parametrize("name,text,kind", SUSPICIOUS)
def test_a_real_request_to_disclose_is_read(name, text, kind):
    found = rq.read(text)
    assert found[kind], name
    assert found["quotes"][kind]


def test_kinds_are_told_apart():
    assert rq.read(SAFE[0][1])["code_delivery"] and rq.read(SAFE[0][1])["negated_advice"]
    assert rq.read(SAFE[2][1])["security_notice"] and rq.read(SAFE[2][1])["sign_in_request"]
    assert rq.read("Log in to view your statement.")["sign_in_request"]
    assert rq.read("Log in within 24 hours or your account will be suspended.")["sign_in_request"]
    assert not rq.disclosure(rq.read("Log in to view your statement."))
    assert rq.read("Your payment was declined. Update your payment method to keep watching.")["payment_detail_update"]


def test_account_access_notice_is_not_a_sign_in_request():
    text = ("You allowed account-tools.example access to your Google Account data person@gmail.com. "
            "If you didn't allow access, check your account activity and secure your account.")
    result = rq.read(text)
    assert result["security_notice"]
    assert not result["sign_in_request"]
    assert not rq.disclosure(result)
    assert rq.read(text + " Reply with your password now.")["secret_request"]
    assert rq.read(text + " Send me the verification code we texted you.")["code_request"]
    assert rq.read("Please sign in to verify your account at https://evil.example/login")["sign_in_request"]

"""Email triage reads the email itself: what it asks, who it presents itself as and where its links really go.

Run offline: no provider lookups (provider_evidence is supplied), no AI call.
"""
import pytest

from services.triage import Outcome, evaluate
from services.triage_engine import _extract_evidence_from_email, _rule_evidence

PASS = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}


def judge(sender, subject, body, links=(), *, auth=PASS, reply_to="", findings=(), provider_evidence=None):
    message = {"from": sender, "subject": subject, "body": body, "links": [{"text": t, "href": h} for t, h in links],
               "reply_to": reply_to, "attachment_names": [], "auth_results": auth}
    evidence = _extract_evidence_from_email(message)
    return evaluate(_rule_evidence(evidence, list(findings), provider_evidence or {}))


GENUINE = [
    ("code delivery", "Microsoft account team <account-security-noreply@accountprotection.microsoft.com>", "Your security code",
     "Please use the following security code for the Microsoft account. Security code: 482913. If you didn't request this code, you can safely ignore this email. Never share this code.", []),
    ("password changed", "Google <no-reply@accounts.google.com>", "Your password was changed",
     "Your Google Account password was changed. If this was you, you don't need to do anything. If you didn't make this change, reset your password now.",
     [("Check activity", "https://myaccount.google.com/notifications")]),
    ("never share", "CommBank <NetBankNotification@cba.com.au>", "Keeping you safe",
     "We'll never ask you for your NetBank password or a NetCode by email or SMS. Never share your password with anyone.", [("Learn more", "https://www.commbank.com.au/security")]),
    ("retailer mentions Apple", "JB Hi-Fi <news@email.jbhifi.com.au>", "The new iPhone is here",
     "Shop the new Apple iPhone 16 and Apple Watch. Sign in to your JB Hi-Fi account to see member prices.",
     [("Shop now", "https://click.mailchimp.com/track/abc"), ("Sign in", "https://www.jbhifi.com.au/account")]),
    ("newsletter", "The Conversation <newsletter@theconversation.com>", "This week's top stories",
     "Read our latest stories. Manage your preferences or unsubscribe at any time.",
     [("Read more", "https://theconversation.com/au/story"), ("Unsubscribe", "https://sendgrid.net/unsub/123")]),
    ("third-party links", "Qantas <qantas@e.qantas.com>", "Your trip to Sydney",
     "Your booking is confirmed. Book a hotel with our partner or hire a car for your trip.",
     [("Book a hotel", "https://www.booking.com/qantas"), ("Hire a car", "https://www.hertz.com.au/qantas")]),
]


@pytest.mark.parametrize("name,sender,subject,body,links", GENUINE)
def test_genuine_mail_is_not_a_possible_threat(name, sender, subject, body, links):
    found = judge(sender, subject, body, links, findings=["The sender's email address and link destinations use different domains."])
    assert found.outcome is not Outcome.POSSIBLE_THREAT, (name, [r.rule_id for r in found.met_rules])


def test_different_sender_and_link_domains_alone_establish_nothing():
    found = judge("Acme News <news@acme-mail.com>", "Updates", "Here's what's new this month.", [("Read", "https://blog.example.org/post")])
    assert found.met_rules == []


def test_credential_theft_is_caught():
    found = judge("IT Helpdesk <helpdesk@mailbox-upgrade.top>", "Mailbox full",
                  "Your mailbox is full. Reply with your email password so we can increase your storage today.")
    assert found.outcome is Outcome.POSSIBLE_THREAT
    assert "EMAIL-04" in [r.rule_id for r in found.met_rules]


def test_request_to_send_a_code_is_caught():
    found = judge("Bookings <reservations@fast-stay-confirm.com>", "Confirm your booking",
                  "We just sent you a 6-digit code. Please reply with the code to confirm your booking.")
    assert "EMAIL-05" in [r.rule_id for r in found.met_rules]


def test_deceptive_brand_claim_is_caught():
    found = judge("PayPal Security <service@paypa1-support.com>", "Your account has been limited",
                  "We noticed unusual activity. Your account has been limited. Log in now to restore access within 24 hours.",
                  [("Log in now", "https://paypa1-support.com/login")], auth={"spf": "softfail", "dkim": "none", "dmarc": "fail"})
    met = [r.rule_id for r in found.met_rules]
    assert found.outcome is Outcome.POSSIBLE_THREAT
    assert "EMAIL-01" in met and "EMAIL-03" in met


def test_confirmed_malicious_url_is_caught():
    url = "https://evil.example.net/login"
    pe = {"safe_browsing": {"urls": {url: {"verdict": "malicious", "threat_types": ["SOCIAL_ENGINEERING"], "status": "ok", "coverage": "full",
                                           "sources": [{"name": "google_safe_browsing", "status": "match"}]}}}}
    found = judge("Someone <a@b.com>", "Hi", "Have a look at this.", [("here", url)], provider_evidence=pe)
    assert "LINK-01" in [r.rule_id for r in found.met_rules]


def test_observation_wording_is_not_source_evidence():
    found = judge("Shop <hello@shop.com.au>", "Sale", "Our sale starts today.",
                  findings=["Credential request: password, log in, verification code, bank details changed, CEO wire transfer"])
    assert found.met_rules == []

"""Recognised email-sending infrastructure: the click-tracking and delivery domains bulk-email services put in front of
a sender's own links.

A link through one of these says only which service delivered the email. It is never evidence either way:
  - it is not a sender/link mismatch, so on its own it can't make an email a Possible Threat or send it to a paid
    investigation (the destination behind it, when Apollo followed the redirect, is judged instead);
  - it is never proof the email is safe: anyone can buy these services, so a recognised name settles nothing, and
    every other rule (authentication, requests, listings, attachments) still applies to the email.
"""
from __future__ import annotations

from services.higgins.brand_domains import registrable

# Registrable domains used only for bulk-email click tracking, open tracking or delivery.
TRACKING_DOMAINS = frozenset({
    "list-manage.com", "mailchimp.com", "mailchi.mp", "mcusercontent.com", "mcsv.net",           # Mailchimp
    "sendgrid.net", "sendgrid.com",                                                             # SendGrid
    "mandrillapp.com",                                                                          # Mandrill
    "exct.net", "exacttarget.com", "sfmc-content.com", "mc.salesforce.com",                     # Salesforce Marketing Cloud
    "hubspotlinks.com", "hubspotemail.net", "hs-sites.com", "hubspotstarter.net",               # HubSpot
    "mktossl.com", "mktoweb.com", "mkto-sj.com", "marketo.com",                                 # Marketo
    "klclick.com", "klclick1.com", "klclick2.com", "klclick3.com", "klaviyomail.com",           # Klaviyo
    "rs6.net", "constantcontact.com",                                                           # Constant Contact
    "createsend.com", "createsend1.com", "cmail19.com", "cmail20.com",                          # Campaign Monitor
    "mailgun.org", "mailgun.net",                                                               # Mailgun
    "sparkpostmail.com", "sparkpostmail1.com",                                                  # SparkPost
    "awstrack.me",                                                                              # Amazon SES
    "mailjet.com", "mjt.lu",                                                                    # Mailjet
    "sendibt2.com", "sendibt3.com", "sendibm1.com", "brevo.com", "sendinblue.com",              # Brevo
    "customeriomail.com", "customer.io",                                                        # Customer.io
    "iterable.com",                                                                             # Iterable
    "braze.com", "braze.eu",                                                                    # Braze
    "omnisend.com", "omnisrv.com",                                                              # Omnisend
    "activehosted.com", "acems1.com", "acemsd1.com",                                            # ActiveCampaign
    "emlnk.com", "emltrk.com",                                                                  # Litmus
    "ccsend.com",                                                                               # Constant Contact
    "pstmrk.it", "postmarkapp.com",                                                             # Postmark
})


def is_tracking(host: str) -> bool:
    """The host belongs to recognised email-sending infrastructure (never a verdict about the email)."""
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    domain = registrable(host)
    return domain in TRACKING_DOMAINS or any(host == d or host.endswith("." + d) for d in TRACKING_DOMAINS)

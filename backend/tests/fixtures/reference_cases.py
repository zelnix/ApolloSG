"""ApolloSG PRD v2.3 §5 — Expanded Reference Investigation Library (synthetic fixtures).

These 55 cases are the PRD's own §5.2 illustrative-target table, IDs 001-015, 026-030, 061-090,
101-105. Every message/call-transcript below is a SYNTHETIC fixture written for this test suite —
never a real user's data, never copied from a real investigation, and kept out of production KB
content, calibration tables and live investigation history (PRD §5.3/§5.4).

Each case carries:
    id             the PRD's own case ID.
    scenario       the PRD's own scenario name.
    category       "confirmed_scam" | "suspicious" | "benign" | "verified_legitimate" —
                   loosely: PRD §5.1's "confirmed scams" / "suspicious cases" /
                   "ordinary legitimate messages" / "verified legitimate communications".
    target_score   the PRD's illustrative target rating (0-100) — a calibration *reference point*,
                   not a literal pass/fail threshold (see test_calibration_reference_library.py for
                   why the test asserts the Finding tier, and reports the score delta as advisory).
    target_finding one of the four Finding keys (scam | likely_scam | unlikely_scam | not_scam).
    question       what's actually being asked of ApolloSG.
    material       the synthetic message/call-transcript text.
    ground_truth   optional list of (check_kind, subject_contains, fact_kwargs) — the independently-
                   verified result a *real* reputation/registry lookup would have returned for this
                   synthetic scenario (never invented to force a score: each one matches what the
                   scenario itself already describes, e.g. a "confirmed fake portal" case gets the
                   lookalike-domain fact a real RDAP+brand check would have found for a domain like
                   that). Applied to the matching Check objects before decide.evaluate() runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReferenceCase:
    id: str
    scenario: str
    category: str
    target_score: int
    target_finding: str
    question: str
    material: str
    ground_truth: list[tuple[str, str, dict]] = field(default_factory=list)


def gt(check_kind: str, subject_contains: str, **fact_kwargs) -> tuple[str, str, dict]:
    return (check_kind, subject_contains, fact_kwargs)


# ── 001-005 — Account Takeover & Authentication Exploitation ────────────────
CASES: list[ReferenceCase] = [
    ReferenceCase(
        id="001", scenario="Confirmed OTP refund hijack", category="confirmed_scam", target_score=98, target_finding="scam",
        question="Is this a scam?",
        material=("ANZ Bank: We detected an unauthorised refund of $649.00 to your account. To reverse this and stop it being "
                  "withdrawn, reply with the 6-digit one-time code we just texted you within 10 minutes."),
    ),
    ReferenceCase(
        id="002", scenario="Confirmed fake account verification portal", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Netflix: Your payment failed and your account will be suspended today. Update your billing details now at "
                  "https://netflix-billing-update.cc/verify to keep your account active."),
        ground_truth=[gt("impersonation", "Netflix", text="netflix-billing-update.cc carries Netflix's name, but it is not Netflix's domain (netflix.com).",
                          signal="anomaly", topic="lookalike", place="netflix-billing-update.cc"),
                      gt("link", "netflix-billing-update.cc", text="netflix-billing-update.cc was registered 4 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="003", scenario="Confirmed password-reset credential theft", category="confirmed_scam", target_score=97, target_finding="scam",
        question="Is this a scam?",
        material=("Microsoft account alert: unusual sign-in activity detected from a new device. If this wasn't you, reply with "
                  "the verification code sent to your phone to secure your account immediately, or your account will be locked."),
    ),
    ReferenceCase(
        id="004", scenario="Confirmed malicious OAuth consent request", category="confirmed_scam", target_score=93, target_finding="scam",
        question="Is this a scam?",
        material=("Google security alert: An app named \"Docs Viewer Pro\" is requesting full access to your Google account, "
                  "including your contacts, email and Drive files. Approve the request at https://accounts-google-verify.app/consent "
                  "within 15 minutes or your account access will be revoked."),
        ground_truth=[gt("impersonation", "Google", text="accounts-google-verify.app carries Google's name, but it is not Google's domain (google.com).",
                          signal="anomaly", topic="lookalike", place="accounts-google-verify.app"),
                      gt("link", "accounts-google-verify.app", text="accounts-google-verify.app was registered 2 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="005", scenario="Suspicious account recovery with substantial indicators", category="suspicious", target_score=79, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Hi, this is IT Support. We noticed repeated failed logins on your work account. For urgent account recovery, "
                  "please call us back on 1300 558 214 and read out the 6-digit code you'll receive, so we can lock the "
                  "intruder out before they get in."),
    ),

    # ── 006-010 — Retail, E-Commerce & Employment (courier/delivery) ────────
    ReferenceCase(
        id="006", scenario="Confirmed courier delivery-fee phishing", category="confirmed_scam", target_score=95, target_finding="scam",
        question="Is this a scam?",
        material=("AusPost: Your parcel is held at the depot due to an unpaid customs fee of $3.20. Pay now at "
                  "https://auspost-redeliver.top/pay to avoid your parcel being returned to sender today."),
        ground_truth=[gt("impersonation", "AusPost", text="auspost-redeliver.top carries Australia Post's name, but it is not Australia Post's domain (auspost.com.au).",
                          signal="anomaly", topic="lookalike", place="auspost-redeliver.top"),
                      gt("link", "auspost-redeliver.top", text="auspost-redeliver.top was registered 6 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="007", scenario="Confirmed fake courier tracking portal", category="confirmed_scam", target_score=94, target_finding="scam",
        question="Is this a scam?",
        material=("DHL Express: We attempted delivery of your parcel but nobody was home. Reschedule and pay the redelivery fee "
                  "of $2.99 at https://dhl-trackparcel.xyz/redeliver within 24 hours or it will be destroyed."),
        ground_truth=[gt("link", "dhl-trackparcel.xyz", text="dhl-trackparcel.xyz carries DHL's name, but it is not DHL's domain (dhl.com).",
                          signal="anomaly", topic="lookalike", place="dhl-trackparcel.xyz"),
                      gt("link", "dhl-trackparcel.xyz", text="dhl-trackparcel.xyz was registered 1 day ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="008", scenario="Confirmed delivery redirection credential theft", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Your StarTrack parcel couldn't be delivered. To redirect it to a pickup point, log in with your email and "
                  "password at https://startrack-redirect.info/login to confirm the new address."),
        ground_truth=[gt("impersonation", "startrack", text="startrack-redirect.info carries StarTrack's name, but it is not StarTrack's own domain (startrack.com.au).",
                          signal="anomaly", topic="lookalike", place="startrack-redirect.info"),
                      gt("link", "startrack-redirect.info", text="startrack-redirect.info carries StarTrack's name, but it is not StarTrack's domain (startrack.com.au).",
                          signal="anomaly", topic="lookalike", place="startrack-redirect.info"),
                      gt("link", "startrack-redirect.info", text="startrack-redirect.info was registered 3 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        # Corrected per ApolloSG Developer Instructions ("Correct Benign Baseline Invocation") — an
        # ordinary message with nothing to check and nothing wrong is not_scam/0, not the PRD's original
        # illustrative unlikely_scam/28: that depended on the since-removed "absence of verification"
        # Benign trigger. See services/higgins/tc_flyby/scoring.py::benign_trigger.
        id="009", scenario="Ordinary unverified parcel arrival notice", category="benign", target_score=0, target_finding="not_scam",
        question="Is this a scam?",
        material="Your parcel from Kmart has arrived at the Auspost locker at Westfield Hornsby. It will be held for 48 hours.",
    ),
    ReferenceCase(
        id="010", scenario="Delivery message with suspicious payment link", category="suspicious", target_score=77, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Parcel notice: a small redelivery fee of $1.95 is outstanding. Pay securely here: http://bit.ly/parcel-fee-au "
                  "to avoid your item being returned."),
        ground_truth=[gt("link", "bit.ly", text="bit.ly/parcel-fee-au redirects to a newly registered domain unrelated to any known courier.",
                          signal="weak", topic="redirect")],
    ),

    # ── 011-015 — Brand & Corporate Impersonation (banking) ─────────────────
    ReferenceCase(
        id="011", scenario="Confirmed bank security impersonation", category="confirmed_scam", target_score=97, target_finding="scam",
        question="Is this a scam?",
        material=("Commonwealth Bank Security: suspicious activity has been detected on your NetBank account. Verify your "
                  "identity now at https://commbank-secure-verify.net/id or your account will be suspended within the hour."),
        ground_truth=[gt("impersonation", "CommBank", text="commbank-secure-verify.net carries CommBank's name, but it is not CommBank's domain (commbank.com.au).",
                          signal="anomaly", topic="lookalike", place="commbank-secure-verify.net"),
                      gt("link", "commbank-secure-verify.net", text="commbank-secure-verify.net was registered 5 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="012", scenario="Confirmed fraudulent bank transfer instructions", category="confirmed_scam", target_score=98, target_finding="scam",
        question="Is this a scam?",
        material=("This is Westpac Fraud Prevention calling. We've blocked a $4,200 transfer from your account. To release your "
                  "funds and secure your account, please read out the one-time passcode you're about to receive."),
    ),
    ReferenceCase(
        id="013", scenario="Suspicious bank callback request", category="suspicious", target_score=81, target_finding="likely_scam",
        question="Is this a scam?",
        material=("NAB Alert: A new payee was added to your account. If this wasn't you, call us back urgently on 1300 442 097 "
                  "to stop the transfer before it processes."),
    ),
    ReferenceCase(
        # Corrected per ApolloSG Developer Instructions ("Correct Benign Baseline Invocation") — see note on case 009.
        id="014", scenario="Ordinary unverified banking reminder", category="benign", target_score=0, target_finding="not_scam",
        question="Is this a scam?",
        material="Reminder: your ANZ credit card payment of $120.00 is due in 3 days. Log in to the ANZ app to view your statement.",
    ),
    ReferenceCase(
        id="015", scenario="Confirmed fraudulent invoice redirection", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Hi, following up on invoice #4471 — our bank details have changed since last time. Please update your records "
                  "and send the $8,750 payment to our new BSB and account number before Friday: reply with confirmation once sent."),
    ),

    # ── 026-030 — Social Engineering & Relationship (family) ────────────────
    ReferenceCase(
        id="026", scenario="Hi Mum impersonation with substantial indicators", category="suspicious", target_score=82, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Hi Mum, it's me, I dropped my phone in the toilet and this is a borrowed number. I urgently need you to "
                  "transfer $450 to pay for a new phone today, I can't access my bank app right now."),
    ),
    ReferenceCase(
        id="027", scenario="Confirmed family emergency payment fraud", category="confirmed_scam", target_score=94, target_finding="scam",
        question="Is this a scam?",
        material=("Dad it's me, I'm in hospital after an accident and they need payment for treatment before they'll help me. "
                  "Please wire $1,200 to this account right now, I'll explain everything later, please don't call the old number."),
    ),
    ReferenceCase(
        id="028", scenario="Suspicious emergency money request", category="suspicious", target_score=73, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Hey it's your cousin, lost my wallet and phone while travelling, stuck at the airport and need $300 to get "
                  "home tonight, can you send it to this account? I'll pay you back as soon as I land."),
    ),
    ReferenceCase(
        id="029", scenario="Confirmed impersonated relative requesting transfer", category="confirmed_scam", target_score=95, target_finding="scam",
        question="Is this a scam?",
        material=("Hi mum it's me, I lost my phone yesterday so this is my new number, please save it. I need you to transfer "
                  "$900 urgently for an emergency bill, I can't talk right now just send it to this account and I'll call you "
                  "once it's sorted, please don't tell anyone else about this."),
    ),
    ReferenceCase(
        # Corrected per ApolloSG Developer Instructions ("Correct Benign Baseline Invocation") — see note on case 009.
        id="030", scenario="Unverified ordinary family message", category="benign", target_score=0, target_finding="not_scam",
        question="Is this a scam?",
        material="Hey, running 10 minutes late to dinner, see you soon! Can you grab some bread on the way?",
    ),

    # ── 061-070 — Social Engineering (romance) & Financial/Crypto Fraud ─────
    ReferenceCase(
        # Corrected per ApolloSG Developer Instructions ("Correct Benign Baseline Invocation") — see note on case 009.
        id="061", scenario="Ordinary golf invitation", category="benign", target_score=0, target_finding="not_scam",
        question="Is this a scam?",
        material="Keen for golf Saturday morning? Tee off at 7am, I'll book us in at the usual course.",
    ),
    ReferenceCase(
        id="062", scenario="Romance grooming with financial redirection", category="suspicious", target_score=78, target_finding="likely_scam",
        question="Is this a scam?",
        material=("I know we only matched on the dating app two weeks ago but I already feel so close to you, like we're "
                  "meant to be together. I'm currently working on an oil rig overseas so I can't video call, but I've found an "
                  "amazing crypto investment and I want us to grow our future together — can you send $500 to get started?"),
    ),
    ReferenceCase(
        id="063", scenario="Confirmed romance investment fraud", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("My love, I have missed you so much since we started talking last month. I'm deployed overseas right now and "
                  "my camera is broken so we still haven't video called, but I need you to urgently wire $3,000 to this crypto "
                  "wallet address for an emergency customs fee so I can finally come home to you."),
    ),
    ReferenceCase(
        id="064", scenario="Wrong-number conversation to investment solicitation", category="suspicious", target_score=80, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Hi Sarah, so good catching up again! Since you mentioned wanting better returns, I want a serious relationship "
                  "with you, I mean professionally — my trading mentor is guaranteed returns of 40% a month on crypto, want me "
                  "to send you the link to get started today?"),
    ),
    ReferenceCase(
        id="065", scenario="Confirmed emotional emergency payment fraud", category="confirmed_scam", target_score=93, target_finding="scam",
        question="Is this a scam?",
        material=("Darling, I love you so much already and I can't wait to finally meet you in person. I'm stuck in customs at "
                  "the airport right now and they won't release my luggage until I pay a $2,500 fee — please send the money "
                  "urgently, I'm so scared and I need you, I'll pay you back the moment I land."),
    ),
    ReferenceCase(
        id="066", scenario="Confirmed guaranteed-return investment fraud", category="confirmed_scam", target_score=97, target_finding="scam",
        question="Is this a scam?",
        material=("Our exclusive trading program guarantees a 35% return every single week with zero risk, verified by thousands "
                  "of investors. Spots are limited — transfer your first deposit of $1,000 to this crypto wallet today to lock "
                  "in your guaranteed profits before the offer closes tonight."),
    ),
    ReferenceCase(
        id="067", scenario="Investment with unverifiable licence and suspicious returns", category="suspicious", target_score=83, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Our fund manager holds Australian financial services licence 487213 and consistently delivers 15% monthly "
                  "returns for clients. Minimum investment is $2,000, paid by bank transfer — reply to receive our account "
                  "details and get started this week."),
        ground_truth=[gt("licence", "487213", text="No entity holds Australian financial services licence 487213 on ASIC's professional register.",
                          signal="missing", topic="licence_unverifiable")],
    ),
    ReferenceCase(
        id="068", scenario="Confirmed cryptocurrency wallet-draining request", category="confirmed_scam", target_score=99, target_finding="scam",
        question="Is this a scam?",
        material=("Urgent security alert from your crypto wallet provider: suspicious withdrawal attempts detected. To secure "
                  "your funds immediately, enter your 12-word recovery phrase at the verification page we've sent you, or your "
                  "wallet will be drained within the hour."),
    ),
    ReferenceCase(
        # Corrected per ApolloSG Developer Instructions ("Correct Benign Baseline Invocation") — see note on case 009.
        id="069", scenario="Ordinary unverified investment seminar invitation", category="benign", target_score=0, target_finding="not_scam",
        question="Is this a scam?",
        material="You're invited to a free investment seminar at the local library next Thursday 6pm, covering super and shares basics. All welcome.",
    ),
    ReferenceCase(
        id="070", scenario="Confirmed fraudulent withdrawal-fee demand", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Congratulations, your investment account balance has grown to $48,000! To withdraw your funds, you must first "
                  "pay a refundable release fee of $1,500 in cryptocurrency. Send it today and your withdrawal will be processed "
                  "within 24 hours."),
    ),

    # ── 071-075 — Retail, E-Commerce & Employment ───────────────────────────
    ReferenceCase(
        id="071", scenario="Confirmed fake online store", category="confirmed_scam", target_score=94, target_finding="scam",
        question="Is this a scam?",
        material=("MASSIVE CLEARANCE: designer handbags 90% off, today only! Pay now at https://designer-outlet-sale.shop/checkout "
                  "with your card details — stock is almost gone."),
        ground_truth=[gt("link", "designer-outlet-sale.shop", text="designer-outlet-sale.shop was registered 5 days ago and is not listed as an authorised retailer.",
                          signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="072", scenario="Suspicious marketplace advance-payment request", category="suspicious", target_score=76, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Hi, still interested in the PS5 I listed? I can hold it for you but I've had a few people flake, so I'll need "
                  "a $100 deposit via bank transfer first to secure it before we arrange pickup."),
    ),
    ReferenceCase(
        id="073", scenario="Confirmed task-based employment fraud", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Earn $300 a day working from home! Simply complete simple product-rating tasks on our app. To unlock "
                  "withdrawals after your first task set, deposit a refundable $150 activation fee in cryptocurrency to get started."),
    ),
    ReferenceCase(
        # Corrected per ApolloSG Developer Instructions ("Correct Benign Baseline Invocation") — see note on case 009.
        id="074", scenario="Ordinary unverified job interview invitation", category="benign", target_score=0, target_finding="not_scam",
        question="Is this a scam?",
        material="Hi, thanks for applying — we'd like to invite you for an interview Tuesday at 10am at our office. Please confirm if that time works.",
    ),
    ReferenceCase(
        id="075", scenario="Confirmed money mule recruitment", category="confirmed_scam", target_score=95, target_finding="scam",
        question="Is this a scam?",
        material=("We're hiring a payment processing agent, no experience needed! You'll receive funds into your personal bank "
                  "account and forward them on via cryptocurrency, keeping a 10% commission on each transfer. Reply with your "
                  "account details to get started today."),
    ),

    # ── 076-080 — Cyber Extortion & Threats ──────────────────────────────────
    ReferenceCase(
        id="076", scenario="Confirmed sextortion demand", category="confirmed_scam", target_score=98, target_finding="scam",
        question="Is this a scam?",
        material=("I have access to your webcam and recorded footage of you from a compromised site, along with your entire "
                  "contact list. Pay $800 in bitcoin within 24 hours or I will send it to everyone you know. Do not contact the "
                  "police or I will release it immediately."),
    ),
    ReferenceCase(
        id="077", scenario="Confirmed ransomware payment demand", category="confirmed_scam", target_score=99, target_finding="scam",
        question="Is this a scam?",
        material=("Your files have been encrypted. To receive the decryption key and restore access, you must pay 0.5 bitcoin "
                  "to the wallet address below within 48 hours, or your files will be permanently deleted and leaked online."),
    ),
    ReferenceCase(
        id="078", scenario="Suspicious fabricated hacking claim", category="suspicious", target_score=81, target_finding="likely_scam",
        question="Is this a scam?",
        material=("I installed malware on your device weeks ago and recorded everything through your camera while you visited "
                  "adult sites. I have your browsing history and contact list. Pay $500 in bitcoin to this wallet within 3 days "
                  "or everyone finds out."),
    ),
    ReferenceCase(
        id="079", scenario="Confirmed data exposure blackmail", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("We have obtained your private photos and personal documents from a data breach. Unless you transfer $1,000 "
                  "in cryptocurrency within 24 hours, we will publish everything to your family, employer and social media contacts."),
    ),
    ReferenceCase(
        id="080", scenario="Confirmed malicious remote-access extortion", category="confirmed_scam", target_score=97, target_finding="scam",
        question="Is this a scam?",
        material=("This is Microsoft Support. Your computer has been compromised and is sending out viruses to your contacts. "
                  "Install AnyDesk now and give us remote access, or pay a $400 removal fee in gift cards, or we will report "
                  "this to the authorities and lock you out permanently."),
    ),

    # ── 081-085 — Government, Tax & Legal Impersonation ─────────────────────
    ReferenceCase(
        id="081", scenario="Confirmed tax refund credential phishing", category="confirmed_scam", target_score=97, target_finding="scam",
        question="Is this a scam?",
        material=("ATO: You are eligible for a refund of $482.17. To claim it, verify your identity and bank details now at "
                  "https://ato-gov-refund.cc/claim before your refund expires today."),
        ground_truth=[gt("impersonation", "the ATO", text="ato-gov-refund.cc carries the ATO's name, but it is not the ATO's domain (ato.gov.au).",
                          signal="anomaly", topic="lookalike", place="ato-gov-refund.cc"),
                      gt("link", "ato-gov-refund.cc", text="ato-gov-refund.cc was registered 2 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="082", scenario="Suspicious government payment notice", category="suspicious", target_score=79, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Centrelink: your payment has been suspended due to a compliance review. To reinstate it, call us urgently "
                  "on 1300 884 210 and confirm your Medicare and bank details before your next payment date."),
    ),
    ReferenceCase(
        id="083", scenario="Confirmed fake court payment demand", category="confirmed_scam", target_score=95, target_finding="scam",
        question="Is this a scam?",
        material=("This is the Local Court Enforcement Division. A warrant has been issued for your arrest due to an unpaid "
                  "fine. To avoid arrest today, you must pay $650 immediately via gift card and read out the codes over the phone."),
    ),
    ReferenceCase(
        id="084", scenario="Confirmed toll payment phishing", category="confirmed_scam", target_score=94, target_finding="scam",
        question="Is this a scam?",
        material=("Linkt: you have an unpaid toll of $4.85. To avoid a late fee and legal action, pay immediately at "
                  "https://linkt-au-payment.top/pay."),
        ground_truth=[gt("impersonation", "Linkt", text="linkt-au-payment.top carries Linkt's name, but it is not Linkt's domain (linkt.com.au).",
                          signal="anomaly", topic="lookalike", place="linkt-au-payment.top"),
                      gt("link", "linkt-au-payment.top", text="linkt-au-payment.top was registered 4 days ago.", signal="weak", topic="registration")],
    ),
    ReferenceCase(
        id="085", scenario="Confirmed government benefits impersonation", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Services Australia: you are entitled to a one-off cost of living payment of $750. Claim now by entering your "
                  "myGov password and bank details at https://mygov-payment-claim.net/claim within 24 hours."),
        ground_truth=[gt("impersonation", "myGov", text="mygov-payment-claim.net carries myGov's name, but it is not myGov's domain (my.gov.au).",
                          signal="anomaly", topic="lookalike", place="mygov-payment-claim.net"),
                      gt("link", "mygov-payment-claim.net", text="mygov-payment-claim.net was registered 3 days ago.", signal="weak", topic="registration")],
    ),

    # ── 086-090 — Real Estate, Rental & Credit Fraud ─────────────────────────
    ReferenceCase(
        id="086", scenario="Confirmed rental deposit fraud", category="confirmed_scam", target_score=96, target_finding="scam",
        question="Is this a scam?",
        material=("Great news, the 2-bedroom apartment is still available! I'm currently overseas for work so I can't show it "
                  "in person, but if you transfer the $1,800 bond and first month's rent today, I'll courier you the keys "
                  "straight away, no inspection needed."),
    ),
    ReferenceCase(
        id="087", scenario="Suspicious property listing with payment pressure", category="suspicious", target_score=80, target_finding="likely_scam",
        question="Is this a scam?",
        material=("Hi, lots of interest in this rental already so I need a decision fast. I can't do an inspection this week, "
                  "but if you wire the $600 holding deposit today I'll take it off the market for you."),
    ),
    ReferenceCase(
        id="088", scenario="Confirmed conveyancing payment redirection", category="confirmed_scam", target_score=99, target_finding="scam",
        question="Is this a scam?",
        material=("Hi, this is your conveyancer's office — please note our trust account details have changed since our last "
                  "email. Please send your $45,000 settlement deposit to the new BSB and account number below before Friday's "
                  "settlement date."),
    ),
    ReferenceCase(
        id="089", scenario="Confirmed fraudulent credit repair scheme", category="confirmed_scam", target_score=93, target_finding="scam",
        question="Is this a scam?",
        material=("Struggling with bad credit? We guarantee to wipe your credit file clean within 7 days using an insider "
                  "process. Pay our $900 upfront processing fee via gift card today and your credit score will be reset immediately."),
    ),
    ReferenceCase(
        id="090", scenario="Confirmed property settlement impersonation", category="confirmed_scam", target_score=98, target_finding="scam",
        question="Is this a scam?",
        material=("This is your real estate agent's office calling about tomorrow's settlement. Our bank account was compromised "
                  "so we've set up a new trust account — please confirm you'll transfer the full settlement amount to the new "
                  "details we're about to text you, and don't call the office number to check, our lines are affected too."),
    ),

    # ── 101-105 — Verified legitimate communications (control group) ────────
    ReferenceCase(
        id="101", scenario="Verified legitimate Uber arrival notification", category="verified_legitimate", target_score=5, target_finding="not_scam",
        question="Is this legitimate?",
        material="Your Uber is arriving now. Toyota Camry, plate ABC123, driven by Sam. No payment or link in this message.",
        ground_truth=[gt("impersonation", "uber", text="Every link and address in the material uses uber.com, Uber's official domain.",
                          signal="clear", topic="official_domains", decisive=True)],
    ),
    ReferenceCase(
        id="102", scenario="Verified legitimate courier notification", category="verified_legitimate", target_score=7, target_finding="not_scam",
        question="Is this legitimate?",
        material="Australia Post: your parcel is out for delivery today between 9am-5pm. Track it in the Auspost app. No action needed.",
        # check_kind/subject must match the Check Higgins Triage actually creates for this brand mention
        # ("AusPost", from entity extraction) — "australia post" never matched it, so this fact was
        # silently dropped and the case never got credited with its own positive verification evidence.
        ground_truth=[gt("impersonation", "auspost", text="Every link and address in the material uses auspost.com.au, Australia Post's official domain.",
                          signal="clear", topic="official_domains", decisive=True)],
    ),
    ReferenceCase(
        id="103", scenario="Verified legitimate bank app notification", category="verified_legitimate", target_score=4, target_finding="not_scam",
        question="Is this legitimate?",
        material="CommBank app notification: your weekly spending summary is ready to view in the app. Open the CommBank app to see it.",
        ground_truth=[gt("impersonation", "commbank", text="Every link and address in the material uses commbank.com.au, CommBank's official domain.",
                          signal="clear", topic="official_domains", decisive=True)],
    ),
    ReferenceCase(
        id="104", scenario="Verified legitimate employer interview confirmation", category="verified_legitimate", target_score=6, target_finding="not_scam",
        question="Is this legitimate?",
        material="Confirming our interview tomorrow at 2pm at our office on Level 4, 123 George St. Please bring a copy of your resume. No payment is required at any stage of our process.",
    ),
    ReferenceCase(
        id="105", scenario="Verified legitimate government service notification", category="verified_legitimate", target_score=5, target_finding="not_scam",
        question="Is this legitimate?",
        material="myGov: you have a new message in your myGov inbox from the ATO. Log in to myGov directly to view it — this message contains no links and does not ask for any information.",
        ground_truth=[gt("impersonation", "mygov", text="Every link and address in the material uses my.gov.au, myGov's official domain.",
                          signal="clear", topic="official_domains", decisive=True)],
    ),
]

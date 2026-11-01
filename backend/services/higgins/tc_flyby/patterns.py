"""Apollo KB — established scam patterns, as official sources describe them.

Each pattern is an official source's description of a known scam, reduced to what defines it: the
hallmarks (who the message claims to be and the story it tells) and the ask (what it wants the person to
do). They are Apollo knowledge-base entries (kind "scam_pattern") like any other, with publisher, link and
authority tier, and TC FlyBy reads the markers from the KB entry itself.

TC FlyBy compares the submitted material with them deterministically — no AI, no cost:
  full     every defining indicator and the ask are present           → supports "Likely scam"
  opening  every defining indicator, no ask yet (family pattern only) → supports "Concerning"
  partial  some of it                                                 → not established on its own
Each indicator is a phrase-level construction (a request bound to what it asks for, a claim bound to its
subject), never a lone keyword, and a negated one ("we will never ask for your password") doesn't count.
Impersonation patterns also need the evidence-based indicator TC FlyBy established: the link isn't the
organisation's own. A match supports Apollo's assessment. It is general knowledge applied to the material,
never proof of the identity or intent of this particular sender.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from core.db import db
from services.triage.requests import negated_before
from services.kb_sources import TIER_1

log = logging.getLogger("apollo.tc_flyby.patterns")

KIND = "scam_pattern"
SCAMWATCH = "Scamwatch (ACCC)"
_PAY = r"\b(?:pay|payment|fee|fees|charge|settle|card details|bank details)\b|\$\s?\d"

# ── Phone calls, as the person describes them (channel "call": only for a call check) ──
_PHONE_URL = "https://www.scamwatch.gov.au/types-of-scams/phone-scams"
_PHONE_INTRO = ("Scamwatch: “Scammers call, claiming to be from well-known organisations. This includes government organisations, law "
                "enforcement, investment and law firms, banks, telecommunication providers.” ")
_PHONE_CHECK = (" What to do: “If you are not sure if a caller is who they say they are, it's ok to hang up.” “Call the organisation or "
                "person back on a phone number you have found yourself (on their website).”")
# Who the caller said they were: "said they were from my bank", "claimed to be the ATO", "from tech support" …
_CLAIMED = (r"(?:from|with|calling\s+from|on\s+behalf\s+of|claim(?:ed|s|ing)?\s+to\s+be(?:\s+from)?|pretend(?:ed|s|ing)?\s+to\s+be(?:\s+from)?"
            r"|said\s+(?:they|he|she|it)\s+(?:were|was|is|are)(?:\s+from)?|says\s+(?:they|he|she|it)(?:'re|'s|\s+(?:are|is))(?:\s+from)?)"
            r"\s+(?:my|your|the|our|a|an)?\s*")
# … or the organisation doing something on the call: "bank wants my code", "the ATO rang".
_CALLED = (r"(?:'s)?\s+(?:called|calls|rang|rings|phoned|wants|wanted|asked|asks|is\s+asking|was\s+asking|asking|said|says|needs|needed"
           r"|fraud\s+team|security\s+team)\b")
_BANK = (r"(?:bank|card\s+(?:provider|issuer|company)|credit\s+union|building\s+society|commbank|commonwealth\s+bank|westpac|anz|nab"
         r"|national\s+australia\s+bank|st\.?\s?george|bankwest|bendigo\s+bank|macquarie\s+bank|suncorp|ubank|bank\s+of\s+melbourne|ing|hsbc"
         r"|citibank|amex|american\s+express)")
_GOV = (r"(?:ato|australian\s+taxation\s+office|tax\s+office|police|afp|federal\s+police|immigration|home\s+affairs|border\s+force|court"
        r"|sheriff|services\s+australia|centrelink|medicare|mygov|government(?:\s+agency|\s+department)?|department\s+of\s+\w+)")
_TECH = (r"(?:tech(?:nical)?\s+support|it\s+support|help\s*desk|microsoft|apple|google|windows|amazon|telstra|optus|vodafone|tpg|iinet"
         r"|nbn(?:\s+co)?|(?:my|your|the)\s+(?:telco|internet\s+provider|phone\s+company|isp))")
_COURIER = (r"(?:auspost|australia\s+post|startrack|dhl|fedex|ups|aramex|couriers\s+please|toll\s+(?:priority|ipec)"
            r"|(?:delivery|courier|parcel|postal)(?:\s+or\s+parcel)?\s+(?:company|service|driver)|courier)")
_CODE_ASK = (r"\b(?:want(?:s|ed)?|ask(?:s|ed|ing)?(?:\s+(?:me|you|us))?(?:\s+(?:for|to\s+(?:give|read(?:\s+out)?|tell|confirm|share|provide|enter|send|repeat|say)))?"
             r"|request(?:s|ed|ing)?|need(?:s|ed)?|give|read(?:\s+out)?|tell|confirm|share|provide|send|repeat)\b[^.?!\n]{0,40}?"
             r"\b(?:one[- ]time\s+(?:code|password|passcode|pin)|otp|verification\s+code|security\s+code|sms\s+code|text\s+code"
             r"|(?:the|my|your|a|that|this)\s+code|pin(?:\s+number)?|passcode|password|card\s+(?:number|details)|cvv|bank(?:ing)?\s+details"
             r"|netbank\s+(?:password|details|login)|login\s+details)\b")

PATTERNS: tuple[dict, ...] = (
    {
        "key": "family_new_number",
        "name": "family member “new number” scam (“Hi Mum”)",
        "url": "https://www.scamwatch.gov.au/types-of-scams/phishing-scams",
        "summary": "a message from an unknown number claims to be a family member whose phone was lost or broken, then asks for money.",
        "body": ("Scamwatch: “Phishing is when scammers impersonate trusted people or organisations to deceive you into providing "
                 "personal information.” Among those impersonated: “Friends and family members impersonated through social media or "
                 "messaging apps.” In the family version, a message from a new number says it's your child or another relative whose "
                 "phone was lost or broken, and soon asks for money. Scamwatch: “Call the organisation or person back on a phone number "
                 "you have found yourself.”"),
        "hallmarks": [
            ["says it's from a family member", r"\b(?:hi|hey|hello|hiya)\s+(?:mum|mom|mam|dad|mother|father|nan|nana|nanna|grandma|grandpa|gran)\b"
                                               r"|\bit'?s\s+(?:me\s*,?\s*)?your\s+(?:son|daughter|child|grandson|granddaughter)\b"],
            ["says they have a new or lost phone", r"\bnew\s+(?:phone\s+)?(?:number|mobile|phone)\b|\b(?:lost|broke|dropped|smashed|cracked|damaged)\s+my\s+(?:old\s+)?phone\b"
                                                   r"|\bmy\s+(?:old\s+)?phone\s+(?:is\s+)?(?:broken|died|dead|lost|smashed|stolen)\b|\b(?:temporary|temp)\s+(?:number|phone)\b"],
        ],
        "ask": ["asks for money", r"\b(?:can|could|would)\s+you\s+(?:please\s+)?(?:send|transfer|pay|lend|loan|cover)\b[^.?!\n]{0,50}?(?:\$\s?\d[\d,]*|\bmoney\b"
                                  r"|\bcash\b|\bbills?\b|\bpayment\b|\brent\b|\bfunds\b|\bit\b|\bme\b)"
                                  r"|\b(?:please\s+)?(?:send|transfer|pay)\s+(?:me\s+)?\$\s?\d[\d,]*"
                                  r"|\bi\s+need\s+(?:you\s+to\s+(?:send|transfer|pay)\s+(?:me\s+)?)?(?:\$\s?\d[\d,]*|money|cash)\b"
                                  r"|\b(?:pay|transfer)\s+(?:this|the|a)\s+(?:bill|invoice|account)\b"],
        "opening": True,
        "requires": [],
        "impersonates_organisation": False,
        "advice": [["Don't send money", "Don't send money or any details to this number."],
                   ["Call them on their usual number", "Call your family member on the number you already have saved for them — not the new one — and ask if it's really them."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid, contact your bank now."]],
        "consequence": "Money sent to a scammer this way is almost never recovered.",
    },
    {
        "key": "organisation_phishing",
        "name": "phishing message impersonating an organisation",
        "url": "https://www.scamwatch.gov.au/types-of-scams/phishing-scams",
        "summary": "a message claiming to be from an organisation you deal with says there's a problem with your account and sends you to a link to verify or log in.",
        "body": ("Scamwatch warning signs: “You receive an email, text or phone call claiming to be from a business you regularly deal with, "
                 "such as your bank. They may ask you to update or verify your details or tell you there is a problem with your account.” "
                 "“The website address is slightly different to normal.” Scammers ask for “Personal information such as passwords, credit "
                 "card details, and one-time codes” and “To click on links that lead to fake websites.” What to do: “Check that a message, "
                 "call, or email is real by contacting the person or organisation directly using contact details you've found yourself.”"),
        "hallmarks": [
            ["says there's a problem with your account or asks you to verify it",
             r"\b(?:verify|confirm|update|unlock|reactivate|re-activate|validate|restore)\b[^.?!\n]{0,40}\b(?:account|details|identity|information|card|profile|access|payment|security|password|netbank|login|log-in)\b"
             r"|\b(?:account|card|access)\b[^.?!\n]{0,30}\b(?:suspended|locked|blocked|restricted|on hold|disabled|frozen|compromised)\b"
             r"|\bunusual\s+(?:sign[- ]?in|log[- ]?in|activity|transaction)s?\b|\bsecurity\s+(?:alert|notice|warning)\b"],
        ],
        "ask": ["asks you to log in, verify or enter details through the link",
                r"\b(?:log\s?in|sign\s?in|verify|confirm|update|enter|provide|re-?enter)\b[^.?!\n]{0,40}?\b(?:password|passcode|pin|one[- ]time\s+(?:code|password|passcode)"
                r"|otp|verification\s+code|security\s+code|card\s+(?:number|details)|cvv|account\s+details|personal\s+details|banking\s+details|details|identity|account)\b"
                r"[^.?!\n]{0,40}?(?:https?://|\blink\b|\bhere\b|\bbelow\b|\bat\b)"
                r"|\b(?:click|tap|visit|go to|follow|open)\b[^.?!\n]{0,30}?(?:https?://|\blink\b|\bhere\b|\bbelow\b)[^.?!\n]{0,60}?\b(?:verify|confirm|log\s?in|sign\s?in|update|restore|unlock|secure)\b"
                r"|\b(?:verify|confirm|log\s?in|sign\s?in|update|restore|unlock|secure)\b[^.?!\n]{0,40}?(?:https?://|\bvia\s+the\s+link\b|\busing\s+the\s+link\b|\bat\s+the\s+link\b)"],
        "opening": False,
        "requires": ["brand", "link", "offsite_link"],
        "impersonates_organisation": True,
        "advice": [["Don't use the link", "Don't open the link and don't enter any passwords, codes or card details."],
                   ["Contact them yourself", "Go to the organisation through its official app or a website address you type yourself, or call the number on your card or statement."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already entered details, contact the organisation now and change your password."]],
        "consequence": "Details typed into a fake page can be used straight away to get into your account.",
    },
    {
        "key": "delivery_toll",
        "name": "parcel delivery or unpaid toll text scam",
        "url": "https://www.scamwatch.gov.au/types-of-scams/text-or-sms-scams",
        "summary": "a text says a parcel is held or a toll is unpaid and sends you to a link to pay a small fee or update your details.",
        "body": ("Scamwatch: “Scam messages look like they are from the government, businesses you deal with or even your own family or "
                 "friends to try to catch you out.” They may say “there's a problem with your payment or your package delivery” and ask you "
                 "to “make a payment or transfer money” or “click on a link or call a number provided in the message”. “Scammers can steal "
                 "any personal information entered on these scam websites and use it to take your money or commit fraud in your name.”"),
        "hallmarks": [
            ["says a parcel, delivery or toll has a problem", r"\b(?:parcel|package|delivery|shipment|item|order|toll|tolls|e-?toll|linkt)\b[^.?!\n]{0,50}?\b(?:held|on hold|failed"
                                                              r"|unsuccessful|unpaid|overdue|outstanding|missed|could not be delivered|couldn'?t be delivered|unable to be delivered|returned)\b"
                                                              r"|\b(?:unpaid|overdue|outstanding)\s+(?:road\s+)?(?:toll|tolls|e-?toll|fee)s?\b|\b(?:failed|missed|unsuccessful)\s+delivery\b"
                                                              r"|\b(?:incomplete|invalid)\s+(?:delivery\s+)?address\b"],
        ],
        "ask": ["asks you to pay a fee or update your details", r"\b(?:pay|settle|clear)\b[^.?!\n]{0,40}?(?:\$\s?\d|\bfee\b|\btoll\b|\bamount\b|\bbalance\b|\bcharge\b)"
                                                               r"|\b(?:update|confirm|re-?enter)\s+(?:your\s+)?(?:delivery\s+)?(?:address|details|payment)\b"
                                                               r"|\b(?:redelivery|delivery|customs|handling)\s+fee\b"],
        "opening": False,
        "requires": ["link", "offsite_link"],
        "impersonates_organisation": True,
        "advice": [["Don't use the link", "Don't open the link or pay anything through it."],
                   ["Check with them yourself", "Check your delivery or toll account through the company's official app or a website address you type yourself."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid or entered card details, contact your bank now."]],
        "consequence": "Card details entered on a fake payment page can be used to take much more than the small fee shown.",
    },
    {
        "key": "government_threat",
        "name": "government or authority threat scam",
        "url": "https://www.scamwatch.gov.au/types-of-scams/threat-scams",
        "summary": "someone claiming to be a government agency or the police says you're in trouble and threatens arrest or penalties unless you pay.",
        "body": ("Scamwatch warning signs: “You receive a call, message or email unexpectedly from someone claiming to be from a government "
                 "department, debt collection agency or trusted company.” “They will claim that you owe money or that you are in trouble with "
                 "authorities and threaten you with legal action or arrest.” “The caller will tell you that to fix the matter you will need "
                 "to pay a fee or fine.” What to do: “Don't use any contact details provided by the caller. Verify their identity by calling "
                 "the relevant organisation directly.”"),
        "hallmarks": [
            ["claims to be a government agency or the police", r"\b(?:ato|australian taxation office|tax office|police|afp|federal police|immigration|home affairs|court"
                                                               r"|sheriff|services australia|centrelink|medicare|mygov|government|department of)\b"],
            ["threatens arrest, legal action or a penalty", r"\b(?:arrest\s+warrant|warrant\s+(?:for|has\s+been\s+issued)|(?:will|may|could)\s+be\s+arrested"
                                                            r"|face\s+(?:arrest|legal\s+action|prosecution|jail|deportation)|legal\s+action\s+(?:will|against)"
                                                            r"|(?:be|being)\s+deported|court\s+action|(?:criminal|legal)\s+proceedings|police\s+will\s+(?:attend|come|arrest)"
                                                            r"|suspend(?:ed)?\s+your\s+(?:tfn|tax\s+file\s+number|visa|medicare))\b"],
        ],
        "ask": ["asks you to pay or hand over details", r"\b(?:pay|transfer|send|buy|purchase)\b[^.?!\n]{0,50}?(?:\$\s?\d|\bgift\s?cards?\b|\bvouchers?\b|\bitunes\b"
                                                         r"|\bgoogle play\b|\bbitcoin\b|\bcrypto\b|\bfine\b|\bpenalty\b|\bamount\b|\bdebt\b|\bimmediately\b)"
                                                         r"|\b(?:provide|confirm|give)\s+(?:us\s+)?(?:your\s+)?(?:bank details|tax file number|tfn|passport|card details)\b"
                                                         r"|\bkeep\s+(?:it|your money|this)\s+(?:safe|secret|confidential)\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "advice": [["Don't pay or reply", "Don't pay, reply or call back using anything in this message."],
                   ["Contact the agency yourself", "If you're worried, contact the agency using contact details from its official website."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid, contact your bank now."]],
        "consequence": "Government agencies and police don't demand immediate payment under threat — money paid this way goes to the scammer.",
    },
    {
        "key": "unexpected_money",
        "name": "unexpected money or prize scam",
        "url": "https://www.scamwatch.gov.au/types-of-scams/unexpected-money-scams",
        "summary": "a message says you've won or are owed money, but you have to pay a fee or hand over details to receive it.",
        "body": ("Scamwatch warning signs: “Unexpected emails, letters, texts, or any contact that say you are entitled to money, "
                 "compensation, or an inheritance.” “You are asked to pay money up-front, like taxes or fees to get money or prizes; but you "
                 "haven't entered a competition.” What to do: “Don't pay a fee to collect winnings or a prize. Legitimate lotteries don't ask "
                 "you to do this.”"),
        "hallmarks": [
            ["says you've won or are owed money", r"\byou(?:'ve| have)?\s+(?:won|been\s+selected|been\s+chosen)\b"
                                                  r"|\b(?:claim|collect|receive)\s+your\s+(?:prize|winnings|reward|refund|rebate|inheritance|compensation|funds)\b"
                                                  r"|\b(?:unclaimed|pending|outstanding)\s+(?:refund|rebate|inheritance|funds|compensation|prize)\b"
                                                  r"|\bentitled\s+to\s+(?:a\s+)?(?:refund|rebate|compensation|payment|\$)"],
        ],
        "ask": ["asks for a fee or your details to release it", r"\b(?:pay|send|transfer)\b[^.?!\n]{0,40}?\b(?:fee|tax|taxes|charge|charges|deposit)\b"
                                                               r"|\b(?:processing|release|administration|clearance|transfer|handling|customs)\s+(?:fee|charge|tax)\b"
                                                               r"|\b(?:provide|confirm|enter|send)\s+(?:us\s+)?(?:your\s+)?(?:bank\s+details|card\s+details|account\s+details|bsb)\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "advice": [["Don't pay to receive money", "Don't pay any fee or tax, or send details, to receive the money."],
                   ["Check independently", "If it names an organisation, contact it using details from its official website — not from this message."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au."]],
        "consequence": "A fee paid to release a prize or refund is lost, and the money promised never arrives.",
    },
    {
        "key": "job_task",
        "name": "job or paid-task scam",
        "url": "https://www.scamwatch.gov.au/types-of-scams/jobs-and-employment-scams",
        "summary": "an unexpected job offer promises easy money for simple tasks, then asks you to pay, top up or deposit money to keep earning.",
        "body": ("Scamwatch warning signs: “A recruiter contacts you unexpectedly through text message or encrypted message platforms like "
                 "WhatsApp, Signal or Telegram.” “You are told you can earn a high income while working from home and with little effort.” "
                 "“You are told to top up an account with your own money or cryptocurrency to complete tasks.” What to do: “Never send your "
                 "own money, you won't get it back.”"),
        "hallmarks": [
            ["offers a job or paid tasks", r"\b(?:job|role|position|vacanc(?:y|ies)|opportunity)\s+(?:offer|available|opening)|\bwe(?:'re|\s+are)\s+hiring\b"
                                           r"|\brecruiting\s+for\b|\bpart[- ]time\s+(?:job|work|role)\b|\bwork\s+from\s+home\b|\bremote\s+(?:job|work|role)\b"
                                           r"|\bonline\s+(?:job|work|tasks?)\b|\b(?:simple|easy)\s+tasks?\b|\bcomplete\s+tasks?\b"],
            ["promises easy or high pay", r"\$\s?\d[\d,]*\s*(?:per|a|an|/|each)\s*(?:day|hour|hr|week|task)\b|\b(?:earn|earning)\b[^.?!\n]{0,40}(?:\$\s?\d|daily|per day|a day|commission)"
                                          r"|\b(?:little effort|easy money|no experience (?:needed|required)|high (?:income|pay|salary))\b"],
        ],
        "ask": ["asks you to pay, top up or deposit money", r"\b(?:top[- ]?up|recharge|deposit)\b[^.?!\n]{0,40}?(?:\$|\baccount\b|\busdt\b|\bcrypto\b|\bfunds\b|\bbalance\b)"
                                                           r"|\b(?:pay|transfer|send)\s+(?:a|the|your|an)?\s*(?:training|registration|recruitment|starter|activation|joining)\s+fee\b"
                                                           r"|\b(?:upfront|activation|joining|registration)\s+(?:fee|payment|deposit)\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": False,
        "advice": [["Don't send money", "Don't pay, top up or deposit anything to get or keep this work."],
                   ["Check the employer yourself", "Contact the company using details you find yourself on its official website."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid, contact your bank now."]],
        "consequence": "Money you top up or deposit for a 'job' like this is not paid back.",
    },
    {
        "key": "investment_returns",
        "name": "investment scam promising high or guaranteed returns",
        "url": "https://www.scamwatch.gov.au/types-of-scams/investment-scams",
        "summary": "an investment or trading offer promises guaranteed or unusually high returns and pushes you to invest or get in touch to start.",
        "body": ("Scamwatch warning signs: “Emails, websites or ads with testimonials and over-the-top promises of big returns.” “High pressure "
                 "tactics designed to rush you to act so you don't 'miss out'.” What to do: “Always stop and check before you act.” “Check "
                 "the company or website is not named on the Moneysmart investor alert list.” “Ensure the person offering you financial "
                 "products or advice has an Australian financial services (AFS) license.”"),
        "hallmarks": [
            ["is an investment or trading offer", r"\binvest(?:ment|ing)?\s+(?:opportunity|plan|platform|offer|with\s+us|now|today)\b|\binvest\s+(?:\$\s?\d|in\s+(?:our|this|crypto|bitcoin))"
                                                  r"|\btrading\s+(?:platform|signals?|bot|account|group|opportunity)\b|\bcrypto(?:currency)?\s+(?:investment|trading|platform|opportunity)\b"
                                                  r"|\bforex\s+(?:trading|signals?)\b|\bour\s+(?:fund|portfolio|trading\s+platform)\b"],
            ["promises guaranteed or very high returns",
             r"guarantee[ds]?\s+(?:\w+\s+){0,2}(?:returns?|profits?|income|interest|payouts?)"
             r"|\b\d{1,3}(?:\.\d+)?\s?%\s*(?:(?:per|a|each|every)\s+)?(?:day|daily|week|weekly|month|monthly|returns?|profit|interest|roi)\b"
             r"|risk[- ]free|no risk|double your (?:money|investment)|can'?t lose"],
        ],
        "ask": ["asks you to invest or get in touch to start", r"\b(?:deposit|invest|send|transfer)\b[^.?!\n]{0,30}?(?:\$\s?\d|\bmoney\b|\bfunds\b|\busdt\b|\bcrypto\b|\bbitcoin\b|\bminimum\b)"
                                                                r"|\bminimum\s+(?:investment|deposit)\b"
                                                                r"|\b(?:message|contact|join|add)\s+(?:us|me|our\s+(?:group|team|channel))\s+on\s+(?:whatsapp|telegram|signal)\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": False,
        "advice": [["Don't invest or send money", "Don't invest, deposit or send money in response to this offer."],
                   ["Check Moneysmart", "Check the company isn't on Moneysmart's Investor Alert List and holds an Australian financial services licence."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid, contact your bank now."]],
        "consequence": "Money sent to a scam investment is rarely recovered.",
    },
    {
        "key": "remote_access",
        "name": "remote access or tech support scam",
        "url": "https://www.scamwatch.gov.au/types-of-scams/phone-scams",
        "summary": "someone says your device or account has a problem and asks you to install software or give them remote access to fix it.",
        "body": ("Scamwatch: it's probably a scam if the caller “wants you to install software or access a secure account on your mobile "
                 "phone or computer” or “suggests you or your accounts have been hacked or involved in fraud”. What to do: “Never give anyone "
                 "remote access to your computer.”"),
        "hallmarks": [
            ["says your device or account has a problem", r"\byour\s+(?:computer|device|pc|laptop|phone|internet|nbn|connection|account)\s+(?:has\s+been|is|was)\s+"
                                                          r"(?:hacked|infected|compromised|blocked|at\s+risk)\b|\b(?:virus|malware|viruses)\s+(?:detected|found|on\s+your)\b"
                                                          r"|\bwe(?:'ve|\s+have)\s+detected\s+(?:a\s+)?(?:virus|malware|suspicious\s+activity|hackers?)\b"
                                                          r"|\bsecurity\s+(?:breach|issue|problem)\s+(?:on|with)\s+your\b"],
        ],
        "ask": ["asks you to install software or give remote access", r"\b(?:download|install|open|run)\s+(?:the\s+)?(?:anydesk|teamviewer|ultraviewer|quick\s?support|quick\s+assist"
                                                                       r"|remote\s+(?:access|desktop|support))\b|\b(?:give|allow|grant|let)\s+(?:us|me|our\s+technician)\s+(?:remote\s+)?access\b"
                                                                       r"|\b(?:share|start)\s+(?:your\s+)?screen\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "advice": [["Don't give access", "Don't install anything or let anyone connect to your device."],
                   ["Hang up and check", "If it names a company, contact it using details from its official website."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already given access, disconnect from the internet and contact your bank."]],
        "consequence": "Remote access lets someone see and control everything on your device, including your banking.",
    },
    {
        "key": "bank_code_call",
        "name": "bank call scam asking for a code, PIN or password",
        "url": _PHONE_URL,
        "summary": "a caller claiming to be from your bank or card provider asks you to read out a one-time code, PIN, password or card details.",
        "body": (_PHONE_INTRO + "“It's probably a scam call if the caller: asks for personal or financial information: … your password, pin, "
                 "one-time code, or some other security information; credit card or banking details to process a refund or other "
                 "‘overpayment’.”" + _PHONE_CHECK),
        "hallmarks": [["says the caller is from your bank or card provider", rf"\b{_CLAIMED}{_BANK}\b|\b{_BANK}{_CALLED}"]],
        "ask": ["says the caller asked for a code, PIN, password or card details", _CODE_ASK],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "channel": "call",
        "advice": [["Don't give any codes", "Don't give the caller any code, PIN, password or card details."],
                   ["Call your bank yourself", "Hang up and call your bank on the number on your card or in its official app — not a number the caller gave you."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already given a code or details, call your bank now."]],
        "consequence": "A code read out to a caller can let them into your account or approve a payment straight away.",
    },
    {
        "key": "government_call",
        "name": "government or police impersonation call",
        "url": _PHONE_URL,
        "summary": "a caller claiming to be from a government agency or the police asks you to pay, move money or hand over your details.",
        "body": (_PHONE_INTRO + "“It's probably a scam call if the caller: asks for personal or financial information: payment, or for you "
                 "to move money between accounts …” or “threatens you with immediate arrest, deportation, or blackmail etc.” What to do: "
                 "“Immediately hang up on anyone who tries to threaten or intimidate you.” “Never use contact details given by a caller "
                 "or written in an email or SMS.”"),
        "hallmarks": [["says the caller is from a government agency or the police", rf"\b{_CLAIMED}{_GOV}\b|\b{_GOV}{_CALLED}"]],
        "ask": ["says the caller asked you to pay, move money or hand over details",
                r"\b(?:pay|transfer|send|move|buy|purchase|deposit|wire)\b[^.?!\n]{0,50}?(?:\$\s?\d[\d,]*(?:\.\d{2})?|\bmoney\b|\bfunds\b|\bgift\s?cards?\b|\bvouchers?\b"
                r"|\bitunes\b|\bgoogle\s+play\b|\bbitcoin\b|\bcrypto(?:currency)?\b|\bfine\b|\bpenalty\b|\bdebt\b|\bfee\b|\bamount\b|\bbalance\b)"
                r"|\b(?:give|provide|confirm|tell|read(?:\s+out)?|share|send)\b[^.?!\n]{0,30}?\b(?:bank\s+(?:details|account)|card\s+(?:number|details)"
                r"|tax\s+file\s+number|tfn|passport|one[- ]time\s+code|verification\s+code|security\s+code|password|pin)\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "channel": "call",
        "advice": [["Don't pay or give details", "Don't pay, move money or give any details to this caller."],
                   ["Call the agency yourself", "Hang up and contact the agency using contact details from its official website — never a number the caller gave you."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid, contact your bank now."]],
        "consequence": "Money paid or details given to a caller like this go to the scammer and are rarely recovered.",
    },
    {
        "key": "tech_support_call",
        "name": "tech support call scam",
        "url": _PHONE_URL,
        "summary": "a caller claiming to be tech support or your internet provider asks you to install an app, share your screen or give them remote access.",
        "body": (_PHONE_INTRO + "“It's probably a scam call if the caller: … wants you to install software or access a secure account on your "
                 "mobile phone or computer” or “suggests you or your accounts have been hacked or involved in fraud”. What to do: “Never "
                 "give anyone remote access to your computer.”"),
        "hallmarks": [["says the caller is from tech support or your internet provider",
                       rf"\b{_CLAIMED}{_TECH}\b|\b{_TECH}(?:\s+(?:support|technician|security|team|department))?{_CALLED}"
                       r"|\byour\s+(?:computer|device|pc|laptop|phone|internet|nbn|connection|router|modem)\s+(?:has\s+been|is|was)\s+(?:hacked|infected|compromised|at\s+risk)\b"]],
        "ask": ["says the caller asked you to install an app, share your screen or give remote access",
                r"\b(?:download|install|open|run|get)\s+(?:an?\s+|the\s+|this\s+|their\s+|some\s+|our\s+)?(?:app|application|program|software|anydesk|teamviewer"
                r"|ultraviewer|quick\s?support|quick\s+assist|remote\s+(?:access|desktop|support)(?:\s+app)?)\b"
                r"|\b(?:allow|give|grant|let)\s+(?:them\s+|him\s+|her\s+|us\s+|me\s+|our\s+technician\s+)?(?:remote\s+)?access\b"
                r"|\b(?:share|start)\s+(?:my\s+|your\s+|the\s+)?screen\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "channel": "call",
        "advice": [["Don't give access", "Don't install anything, share your screen or let the caller connect to your device."],
                   ["Hang up and check", "Hang up. If you're worried, contact the company using details from its official website — not anything the caller gave you."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already given access, disconnect from the internet and contact your bank."]],
        "consequence": "Remote access lets someone see and control everything on your device, including your banking.",
    },
    {
        "key": "delivery_call",
        "name": "delivery or parcel fee call scam",
        "url": _PHONE_URL,
        "summary": "a caller says a parcel or delivery has a problem and asks you to pay a fee or give your card details to sort it out.",
        "body": ("Scamwatch (text and SMS scams): scam messages may say “there's a problem with your payment or your package delivery”. "
                 "Scamwatch (phone scams): “It's probably a scam call if the caller: asks for personal or financial information: payment, "
                 "or for you to move money between accounts … credit card or banking details …” What to do: “Never use contact details "
                 "given by a caller or written in an email or SMS.”"),
        "hallmarks": [["says the call is about a parcel or delivery",
                       rf"\b{_CLAIMED}{_COURIER}\b|\b(?:my|your|a|the|an)\s+(?:parcel|package|delivery|shipment|consignment)\b"]],
        "ask": ["says the caller asked you to pay a fee or give card details",
                r"\b(?:pay|settle|clear|transfer|send)\b[^.?!\n]{0,40}?(?:\$\s?\d[\d,]*(?:\.\d{2})?|\bmoney\b|\bfee\b|\bcharge\b|\bamount\b|\bbalance\b|\bcustoms\b|\bduty\b)"
                r"|\b(?:redelivery|delivery|customs|handling|release)\s+(?:fee|charge)\b"
                r"|\b(?:give|provide|confirm|read(?:\s+out)?|tell|share|enter)\b[^.?!\n]{0,30}?\b(?:card\s+(?:number|details)|bank\s+details|cvv"
                r"|one[- ]time\s+code|verification\s+code|security\s+code)\b"],
        "opening": False,
        "requires": [],
        "impersonates_organisation": True,
        "channel": "call",
        "advice": [["Don't pay the caller", "Don't pay any fee or give card details to this caller."],
                   ["Check the delivery yourself", "Track the parcel in the courier's official app or a website address you type yourself."],
                   ["Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid or given card details, contact your bank now."]],
        "consequence": "Card details given for a small fee can be used to take much more.",
    },
)

_REQUIREMENT_LABEL = {"brand": "names an organisation", "link": "contains a link",
                      "offsite_link": "sends you to a link that isn't the organisation's own website"}
# Bumped whenever the shipped markers change, so the KB entries are refreshed rather than left stale.
PATTERN_VERSION = 3


async def load() -> int:
    """Put the shipped patterns into Apollo's KB. Idempotent."""
    from services.higgins import knowledge
    for p in PATTERNS:
        await knowledge.upsert(KIND, p["key"], title=f"Scam pattern: {p['name']}", body=p["body"], publisher=SCAMWATCH, url=p["url"],
                               authority_tier=TIER_1, jurisdiction="AU", retrieved_via="shipped_with_apollo", knowledge_class="scam_pattern",
                               extra={"pattern": {**{k: v for k, v in p.items() if k not in ("body", "url")}, "version": PATTERN_VERSION}})
    return len(PATTERNS)


async def entries() -> list[dict]:
    """The scam patterns Apollo's KB currently holds (loaded on first use, and refreshed when the markers change)."""
    query = {"kind": KIND, "status": {"$ne": "historical"}, "pattern": {"$exists": True}}
    rows = await db.higgins_knowledge.find(query, {"_id": 0}).to_list(200)
    if not rows or any((r["pattern"].get("version") or 0) < PATTERN_VERSION for r in rows):
        await load()
        rows = await db.higgins_knowledge.find(query, {"_id": 0}).to_list(200)
    return rows


@dataclass
class PatternMatch:
    entry: dict
    stage: str                       # full | opening | partial
    found: list[tuple[str, str]]     # (what the pattern looks for, the material's own words)
    missing: list[str]
    ask: tuple[str, str] | None
    contradicted: list[str]          # defining indicators the evidence shows are absent

    def wire(self) -> dict:
        p = self.entry["pattern"]
        return {"kbId": self.entry.get("kb_id"), "key": p["key"], "name": p["name"], "publisher": self.entry.get("publisher"),
                "url": self.entry.get("url"), "title": self.entry.get("title"), "summary": p["summary"], "stage": self.stage,
                "found": [list(f) for f in self.found], "missing": self.missing, "ask": list(self.ask) if self.ask else None,
                "contradicted": self.contradicted, "advice": p["advice"], "consequence": p["consequence"],
                "impersonatesOrganisation": p["impersonates_organisation"]}


def _quote(match: re.Match) -> str:
    return " ".join(match.group(0).split())


def _find(regex: str, text: str) -> re.Match | None:
    """The first match that isn't negated ("we will never ask for your password")."""
    for match in re.finditer(regex, text, re.I):
        if not negated_before(text[:match.start()]):
            return match
    return None


def match_one(entry: dict, text: str, *, has_link: bool, has_brand: bool, offsite: bool | None) -> PatternMatch | None:
    """A full match needs every defining indicator — each a phrase-level construction in the material, or an
    evidence-based one TC FlyBy established (a link that isn't the organisation's own) — never a lone keyword."""
    p = entry["pattern"]
    found: list[tuple[str, str]] = []
    missing: list[str] = []
    contradicted: list[str] = []
    for label, regex in p["hallmarks"]:
        hit = _find(regex, text)
        if hit:
            found.append((label, _quote(hit)))
        else:
            missing.append(label)
    for requirement in p.get("requires") or []:
        if requirement == "offsite_link":
            if offsite is False:
                contradicted.append(_REQUIREMENT_LABEL[requirement])
            if not offsite:
                missing.append(_REQUIREMENT_LABEL[requirement])
        elif not {"brand": has_brand, "link": has_link}[requirement]:
            missing.append(_REQUIREMENT_LABEL[requirement])
    hit = _find(p["ask"][1], text)
    ask = (p["ask"][0], _quote(hit)) if hit else None
    if not missing and ask:
        stage = "full"
    elif not missing and p.get("opening"):
        stage = "opening"
    elif found and len(found) + (1 if ask else 0) >= 2:
        stage = "partial"
    else:
        return None
    if not ask:
        missing.append(p["ask"][0])
    return PatternMatch(entry, stage, found, missing, ask, contradicted)


_RANK = {"full": 3, "opening": 2, "partial": 1}


async def best(text: str, *, has_link: bool, has_brand: bool, offsite: bool | None, channel: str | None = None) -> PatternMatch | None:
    """The established pattern the material matches best, or None. A pattern for one channel (a phone call, as the
    person describes it) is compared only with material from that channel."""
    try:
        rows = await entries()
    except Exception:  # noqa: BLE001 — the KB can never break an investigation
        log.warning("scam_patterns_unavailable", exc_info=True)
        return None
    rows = [e for e in rows if e["pattern"].get("channel") in (None, channel)]
    matches = [m for m in (match_one(e, text, has_link=has_link, has_brand=has_brand, offsite=offsite) for e in rows) if m]
    matches.sort(key=lambda m: (_RANK[m.stage], len(m.found) + (1 if m.ask else 0)), reverse=True)
    return matches[0] if matches else None

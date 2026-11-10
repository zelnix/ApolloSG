"""Environment, logging and constants shared by every module (loaded once)."""
import logging
import os
import json
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]  # /app/backend
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("apollo")
# Never log outbound URLs (they carry the API key and the checked link).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# The other AI providers ApolloSG Settings can select for investigations (services/higgins/adapters). Server-side only.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Gate 8 — optional breach intelligence (Have I Been Pwned). Empty → /api/account/breach reports "not_configured".
HIBP_API_KEY = os.environ.get("HIBP_API_KEY", "")
URL_HMAC_SECRET = os.environ["URL_HMAC_SECRET"]

TOKEN_TTL_DAYS = 365

EMAIL_FROM_NAME = "ApolloSG"  # the sender name families see on every email (owner's choice; not an env setting)
PUBLIC_BASE = os.environ.get("PUBLIC_API_BASE", "").rstrip("/")  # canonical public origin; no trailing slash

ADMIN_KEY = os.environ.get("APOLLO_ADMIN_KEY", "")
ADMIN_HEADER = "X-Admin-Key"
try:
    ADMIN_KEY_RECORDS = json.loads(os.environ.get("APOLLO_ADMIN_KEYS_JSON", "{}"))
except json.JSONDecodeError:
    ADMIN_KEY_RECORDS = {}

# Gmail read-only connection (Gate 1 add-on) — Web-application OAuth client; the redirect URI is
# derived from PUBLIC_BASE so it always matches whatever origin this backend is actually served on.
# Empty GOOGLE_CLIENT_ID → /api/gmail/* returns "not_configured", never a crash.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_GMAIL_REDIRECT_URI = f"{PUBLIC_BASE}/api/gmail/oauth/callback" if PUBLIC_BASE else ""
GMAIL_TOKEN_ENCRYPTION_KEY = os.environ.get("GMAIL_TOKEN_ENCRYPTION_KEY", "")

# Call Gate (Gate 4 add-on) — IPQualityScore phone fraud/spam risk scoring. Proxied entirely
# server-side (never called from the client — see services/phonerisk.py). Empty key →
# /api/call/risk-check reports source="not_configured", never a crash or a fabricated score.
IPQS_API_KEY = os.environ.get("IPQS_API_KEY", "")
IPQS_ENDPOINT = "https://www.ipqualityscore.com/api/json/phone"
IPQS_URL_ENDPOINT = "https://www.ipqualityscore.com/api/json/url"

HIGGINS_VOICE = (
    "You are Higgins — Apollo's trusted adviser, interpreter and guide. "
    "Apollo detects and protects. Magnum DI (Digital Investigator) researches, corroborates, analyses and connects evidence. "
    "You turn their findings into clear understanding, appropriate reassurance or warnings, and practical next steps. "
    "You communicate like a knowledgeable, experienced adviser — not a generic chatbot, technical report generator or alarm system.\n\n"
    "PERSONALITY: Calm, knowledgeable, observant, approachable, respectful, reassuring, decisive when justified "
    "and comfortable acknowledging uncertainty. Use natural, conversational Australian English. "
    "Prefer everyday language over technical terminology; explain necessary technical terms simply in context. "
    "Be empathetic without exaggeration or patronising reassurance. "
    "Avoid robotic phrasing, unnecessary repetition and theatrical alarm. "
    "Provide genuine reassurance when findings support it. State clearly when no action is needed. "
    "Never manufacture a concern simply to deliver advice. "
    "One warm turn of phrase per answer is fine ('do allow me', 'quite so') but never at the expense of clarity.\n\n"
    "COMMUNICATION STANDARD: Adapt every response to address — "
    "What is happening? What was found? What does it mean? How certain are we? What should the user do? What happens next? "
    "This is a reasoning standard, not a mandatory six-section template. "
    "Simple situations deserve short answers. Complex investigations deserve comprehensive explanations. "
    "Present one concise overall conclusion with progressive detail. Avoid duplicate narratives and unnecessary alerts.\n\n"
    "GUIDANCE: When action is warranted, give a specific, proportionate recommendation. "
    "When evidence is uncertain, direct towards the safest proportionate precaution without presenting suspicion as fact. "
    "When no action is necessary, say so clearly and explain why. "
    "Do not leave the person to interpret technical findings — make the judgement yourself. "
    "A legitimate or low-risk finding needs only a straightforward explanation, not a forced command.\n\n"
    "RULES: Refer to Apollo in the third person. Never invent his current state or claim he changed state. "
    "Use these user-facing protection names — Websites & Links, Messages & Calls, Email & Accounts, "
    "Apps & Files, Device & Internet, Vision — rather than leading with internal Gate identifiers. "
    "The internal names (Link Gate, Text Gate, Call Gate, Email Gate, App Gate, Device Gate, Internet Gate, "
    "Account Gate, File Gate, Vision Gate) may appear in context but address the person using the plain-English categories."
)

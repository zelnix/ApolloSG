// Higgins Luddish L1 — the Luddish Dictionary: ApolloSG's approved plain-English names and meanings for cybersecurity,
// scam, device, email, web, phone, business-register and ApolloSG terms. One concept keeps one name (`avoid` lists the
// other words Higgins doesn't use for it). A term is swapped for plain words only where the swap means exactly the same
// thing (`plain`); every other term is kept and explained, because simplifying it would change what it means.
// The first entries are the server's glossary (backend/services/higgins/explain/words.py GLOSSARY), word for word.
// Explanatory only: a meaning is never case evidence. Pure: no React, no native imports.
import { escapeRe } from "./patterns.ts";

export type TermCategory = "cyber" | "scam" | "device" | "email" | "web" | "phone" | "business" | "apollosg";

export interface LuddishTerm {
  id: string;
  /** The term as ApolloSG writes it. */
  term: string;
  category: TermCategory;
  /** What finds it in running text (a regular expression, whole words). */
  match: string;
  /** Matched with its exact capitals (acronyms and names). */
  exactCase?: boolean;
  /** Plain words to use instead, only where they mean exactly the same. */
  plain?: { one: string; many?: string };
  /** The approved one-sentence meaning. */
  meaning: string;
  /** An acronym, and what it stands for — given on first use when it isn't familiar. */
  acronym?: string;
  stands?: string;
  /** Familiar to most Australians: not expanded or explained unless asked. */
  familiar?: boolean;
  /** Other words for the same concept that Higgins doesn't use. */
  avoid?: string[];
}

export const DICTIONARY: readonly LuddishTerm[] = [
  // ── The server's glossary, word for word ──
  { id: "registration_record", term: "registration record", category: "web", match: "registration record|RDAP|registrar|registered (?:less than|\\d+|on|in)|newly registered",
    meaning: "A web address's registration record is the public record of when it was set up and who it was registered through." },
  { id: "domain", term: "domain", category: "web", match: "domains?", meaning: "A domain is the name part of a web or email address, the part that says who runs it." },
  { id: "phishing", term: "phishing", category: "scam", match: "phishing", meaning: "Phishing is a fake message or website made to trick you into handing over passwords, codes or money." },
  { id: "malware", term: "malware", category: "cyber", match: "malware", meaning: "Malware is software made to harm your device or steal from it." },
  { id: "redirect", term: "redirect", category: "web", match: "redirect(?:s|ed|ing)?", meaning: "A redirect sends you on from the address you tapped to a different one." },
  { id: "safe_browsing", term: "Safe Browsing", category: "web", match: "(?:Google )?Safe Browsing", exactCase: true, meaning: "Google Safe Browsing is Google's list of websites known to be harmful." },
  { id: "ipqs", term: "IPQualityScore", category: "phone", match: "IPQualityScore|IPQS|fraud score",
    meaning: "IPQualityScore rates how risky a link or phone number looks. Its score is a likelihood, not proof." },
  { id: "blocklist", term: "blocklist", category: "cyber", match: "blocklist(?:ed|s)?", meaning: "A blocklist is a list of addresses already known to be harmful.", avoid: ["blacklist"] },
  { id: "voip", term: "VoIP", category: "phone", match: "VoIP", exactCase: true, acronym: "VoIP", stands: "Voice over Internet Protocol",
    meaning: "A VoIP number runs over the internet, and anyone can set one up in minutes." },
  { id: "abn", term: "ABN", category: "business", match: "A[BC]N", exactCase: true, familiar: true, meaning: "An ABN or ACN is the public number of a business registered in Australia." },
  { id: "asic", term: "ASIC", category: "business", match: "ASIC", exactCase: true, acronym: "ASIC", stands: "Australian Securities and Investments Commission",
    meaning: "ASIC is Australia's company regulator. Its registers list companies and licence holders." },
  { id: "afsl", term: "AFSL", category: "business", match: "AFSL", exactCase: true, acronym: "AFSL", stands: "Australian financial services licence",
    meaning: "An AFSL is the licence a business needs in Australia to sell investments or give financial advice." },
  { id: "payid", term: "PayID", category: "scam", match: "PayID", exactCase: true, meaning: "PayID sends a bank payment to a phone number or email address instead of account details." },
  { id: "impersonation", term: "impersonation", category: "scam", match: "impersonat\\w*", meaning: "Impersonation means pretending to be a real person or organisation." },
  { id: "lookalike", term: "lookalike", category: "web", match: "look-?alike", meaning: "A lookalike address copies a real organisation's name with small changes.", avoid: ["typosquat"] },
  { id: "one_time_code", term: "one-time code", category: "cyber", match: "(?:one-time|verification|security) codes?",
    meaning: "A one-time code is the short code a service sends to prove it's you.", avoid: ["OTP", "token"] },
  { id: "remote_access", term: "remote access", category: "device", match: "remote(?:-| )access", meaning: "Remote access lets someone else control your device from somewhere else." },
  { id: "spoofing", term: "spoofing", category: "phone", match: "spoof\\w*", meaning: "Spoofing makes a call or message look like it comes from someone it doesn't." },
  { id: "cryptocurrency", term: "cryptocurrency", category: "scam", match: "crypto(?:currency|currencies)?", meaning: "A cryptocurrency payment is very hard to trace or get back." },

  // ── Plain swaps: these mean exactly the same, so the plain words are used instead ──
  { id: "url", term: "URL", category: "web", match: "URLs?", exactCase: true, plain: { one: "web address", many: "web addresses" }, meaning: "A web address is what you type or tap to open a website." },
  { id: "email_spelling", term: "email", category: "email", match: "e-mails?", plain: { one: "email", many: "emails" }, familiar: true, meaning: "An email is a message sent to an email address." },
  { id: "malicious", term: "malicious", category: "cyber", match: "malicious", plain: { one: "harmful" }, familiar: true, meaning: "Harmful means made to cause damage or steal." },
  { id: "credentials", term: "sign-in details", category: "cyber", match: "(?:login |log-in |sign-in )?credentials?|log-?in details", plain: { one: "sign-in details", many: "sign-in details" },
    familiar: true, meaning: "Your sign-in details are the username, password and codes you use to get into an account." },
  { id: "hyperlink", term: "link", category: "web", match: "hyperlinks?", plain: { one: "link", many: "links" }, familiar: true, meaning: "A link opens a web address when you tap it." },
  { id: "sms_message", term: "text message", category: "phone", match: "SMS messages?", exactCase: true, plain: { one: "text message", many: "text messages" }, familiar: true,
    meaning: "A text message is a short message sent to a mobile number." },
  { id: "telephone_number", term: "phone number", category: "phone", match: "telephone numbers?", plain: { one: "phone number", many: "phone numbers" }, familiar: true,
    meaning: "A phone number is the number used to call or text someone." },

  // ── Email ──
  { id: "spf", term: "SPF", category: "email", match: "SPF", exactCase: true, acronym: "SPF", stands: "Sender Policy Framework",
    meaning: "SPF is a check the receiving mail server makes on whether the sending server was allowed to send email for that domain." },
  { id: "dkim", term: "DKIM", category: "email", match: "DKIM", exactCase: true, acronym: "DKIM", stands: "DomainKeys Identified Mail",
    meaning: "DKIM is a digital signature on an email that shows it wasn't changed after it was sent and which domain signed it." },
  { id: "dmarc", term: "DMARC", category: "email", match: "DMARC", exactCase: true, acronym: "DMARC", stands: "Domain-based Message Authentication, Reporting and Conformance",
    meaning: "DMARC is a domain's published rule for what mail servers should do with email that fails its SPF or DKIM checks." },
  { id: "email_headers", term: "email headers", category: "email", match: "(?:email |message )?headers", meaning: "Email headers are the hidden lines that record where an email came from and the servers it passed through." },
  { id: "display_name", term: "display name", category: "email", match: "display names?", meaning: "The display name is the name shown as the sender. Anyone can set it to anything." },
  { id: "reply_to", term: "reply-to address", category: "email", match: "reply-to(?: address(?:es)?)?", meaning: "The reply-to address is where your reply goes, which can be different from the address it came from." },
  { id: "sender_domain", term: "sender's domain", category: "email", match: "sender(?:'s)? domains?|sending domains?", meaning: "The sender's domain is the part of the email address after the @, which says who runs it." },
  { id: "eml", term: "original email file", category: "email", match: "\\.eml(?: files?)?|original email files?", meaning: "The original email file (.eml) is the whole email as it arrived, including its headers." },
  { id: "bec", term: "business email compromise", category: "scam", match: "BEC|business email compromise", acronym: "BEC", stands: "business email compromise",
    meaning: "Business email compromise is when a scammer uses or copies a business's email to ask for payments or changed bank details." },

  // ── Web ──
  { id: "https", term: "HTTPS", category: "web", match: "HTTPS", exactCase: true, familiar: true, meaning: "HTTPS means the connection to a website is encrypted. It doesn't show the website is honest." },
  { id: "tls", term: "TLS", category: "web", match: "TLS|SSL", exactCase: true, acronym: "TLS", stands: "Transport Layer Security",
    meaning: "TLS is the encryption that protects the connection between your device and a website." },
  { id: "certificate", term: "security certificate", category: "web", match: "(?:security |TLS |SSL )certificates?", meaning: "A security certificate lets a website encrypt your connection. Scam websites can have one too." },
  { id: "dns", term: "DNS", category: "web", match: "DNS", exactCase: true, acronym: "DNS", stands: "Domain Name System",
    meaning: "DNS is the internet's address book: it turns a website's name into the address your device connects to." },
  { id: "private_dns", term: "Private DNS", category: "device", match: "Private DNS", exactCase: true, meaning: "Private DNS is an Android setting that sends your device's website look-ups through a service you choose." },
  { id: "ip_address", term: "IP address", category: "web", match: "IP address(?:es)?", exactCase: true, acronym: "IP", stands: "Internet Protocol",
    meaning: "An IP address is the number a device or website uses on the internet." },
  { id: "url_shortener", term: "shortened link", category: "web", match: "(?:link|URL) shorteners?|shortened (?:links?|URLs?)", meaning: "A shortened link hides the real address until you open it." },
  { id: "punycode", term: "punycode", category: "web", match: "punycode", meaning: "Punycode lets a web address use letters from other alphabets, which can make a fake address look real." },
  { id: "qr_code", term: "QR code", category: "web", match: "QR codes?", exactCase: true, familiar: true, meaning: "A QR code is a square barcode that opens a link or action when you scan it." },
  { id: "pwa", term: "web app", category: "web", match: "PWA|progressive web apps?", acronym: "PWA", stands: "progressive web app",
    meaning: "A web app is a website that can be added to your home screen and look like an app." },

  // ── Device ──
  { id: "vpn", term: "VPN", category: "device", match: "VPN", exactCase: true, acronym: "VPN", stands: "virtual private network",
    meaning: "A VPN sends your device's internet traffic through another service, so the network you're on can't see it." },
  { id: "apk", term: "APK", category: "device", match: "APKs?", exactCase: true, acronym: "APK", stands: "Android Package",
    meaning: "An APK is an Android app file. One from outside the Play Store hasn't been through Google's checks." },
  { id: "sideloading", term: "installing from outside the app store", category: "device", match: "side-?load(?:ing|ed|s)?",
    meaning: "Installing from outside the app store means the app skipped the store's safety checks." },
  { id: "accessibility_service", term: "accessibility access", category: "device", match: "accessibility (?:service|access|permission)s?",
    meaning: "Accessibility access lets an app read your screen and tap for you. Scam apps misuse it to take control." },
  { id: "device_admin", term: "device admin", category: "device", match: "device admin(?:istrator)?s?", meaning: "Device admin access lets an app control settings and stop itself being removed." },
  { id: "root_jailbreak", term: "rooted or jailbroken", category: "device", match: "rooted|jailbroken|jailbreak", meaning: "A rooted or jailbroken phone has had its built-in protections removed." },
  { id: "screen_lock", term: "screen lock", category: "device", match: "screen locks?", familiar: true, meaning: "A screen lock is the PIN, password, pattern, fingerprint or face check that opens your device." },
  { id: "encryption", term: "encryption", category: "cyber", match: "encrypt(?:ed|ion|s)?", meaning: "Encryption scrambles information so only the right device or person can read it." },
  { id: "public_wifi", term: "public Wi-Fi", category: "device", match: "public Wi-?Fi|open Wi-?Fi", meaning: "Public Wi-Fi is a shared network, like a café's, that other people can also use and sometimes watch." },
  { id: "notification_access", term: "notification access", category: "device", match: "notification access", meaning: "Notification access lets an app read the notifications that arrive on your device." },
  { id: "stalkerware", term: "stalkerware", category: "cyber", match: "stalkerware|spyware", meaning: "Stalkerware is an app that secretly shares what you do on your device with someone else." },
  { id: "ransomware", term: "ransomware", category: "cyber", match: "ransomware", meaning: "Ransomware locks your files or device and demands payment to unlock them." },
  { id: "trojan", term: "trojan", category: "cyber", match: "trojans?", exactCase: false, meaning: "A trojan is a harmful app disguised as something useful." },

  // ── Accounts and data ──
  { id: "mfa", term: "two-step sign-in", category: "cyber", match: "MFA|2FA|two-factor authentication|multi-factor authentication|two-step verification",
    acronym: "MFA", stands: "multi-factor authentication", meaning: "Two-step sign-in asks for a code or approval as well as your password, so a stolen password isn't enough." },
  { id: "otp", term: "OTP", category: "cyber", match: "OTPs?", exactCase: true, acronym: "OTP", stands: "one-time password", meaning: "A one-time password is a code that works once, usually sent by text or an app." },
  { id: "data_breach", term: "data breach", category: "cyber", match: "data breach(?:es)?|breach(?:es|ed)?", meaning: "A data breach is when a company loses control of the information it holds about people." },
  { id: "compromised", term: "compromised", category: "cyber", match: "compromised", meaning: "Compromised means someone else may have got into it or seen it." },
  { id: "authenticated", term: "authenticated", category: "cyber", match: "(?:un)?authenticated|authentication", meaning: "Authenticated means proven to come from who it says it's from." },
  { id: "password_manager", term: "password manager", category: "cyber", match: "password managers?", meaning: "A password manager stores your passwords and only fills them in on the real website." },

  // ── Scams ──
  { id: "smishing", term: "scam text", category: "scam", match: "smishing", meaning: "A scam text is a text message made to trick you into tapping a link, calling a number or paying." },
  { id: "vishing", term: "scam call", category: "scam", match: "vishing", meaning: "A scam call is a phone call made to trick you into handing over money or details." },
  { id: "quishing", term: "scam QR code", category: "scam", match: "quishing", meaning: "A scam QR code leads to a fake website or payment instead of the real one." },
  { id: "gift_cards", term: "gift card payment", category: "scam", match: "gift cards?", familiar: true, meaning: "No real organisation asks to be paid in gift cards. Scammers ask because the money can't be got back." },
  { id: "seed_phrase", term: "recovery phrase", category: "scam", match: "seed phrases?|recovery phrases?", meaning: "A recovery phrase unlocks a crypto wallet. Anyone who has it can take everything in the wallet." },
  { id: "investment_scam", term: "investment scam", category: "scam", match: "investment scams?", familiar: true, meaning: "An investment scam promises high returns to get you to send money that you won't get back." },
  { id: "romance_scam", term: "romance scam", category: "scam", match: "romance scams?", familiar: true, meaning: "A romance scam builds a fake relationship to ask for money later." },
  { id: "family_impersonation", term: "'Hi Mum' scam", category: "scam", match: "Hi (?:Mum|Dad) scams?", exactCase: true, meaning: "A 'Hi Mum' scam is a message pretending to be your child on a new number, asking for money." },
  { id: "caller_id", term: "caller ID", category: "phone", match: "caller ID", meaning: "Caller ID is the number or name your device shows for a call. It can be faked." },
  { id: "number_reputation", term: "number risk check", category: "phone", match: "number (?:risk|reputation) checks?", meaning: "A number risk check looks up whether a phone number has been reported or used for scams." },
  { id: "carrier", term: "phone company", category: "phone", match: "carriers?|telcos?", familiar: true, meaning: "Your device company runs the mobile network your device uses, such as Telstra, Optus or Vodafone." },

  // ── Registers, regulators and lists ──
  { id: "scamwatch", term: "Scamwatch", category: "business", match: "Scamwatch", exactCase: true, familiar: true, meaning: "Scamwatch is the Australian Government's website for reporting and learning about scams." },
  { id: "acsc", term: "ACSC", category: "business", match: "ACSC", exactCase: true, acronym: "ACSC", stands: "Australian Cyber Security Centre",
    meaning: "The ACSC is the Australian Government's cyber security agency." },
  { id: "acma", term: "ACMA", category: "business", match: "ACMA", exactCase: true, acronym: "ACMA", stands: "Australian Communications and Media Authority",
    meaning: "ACMA is the Australian regulator for phones, the internet and broadcasting." },
  { id: "accc", term: "ACCC", category: "business", match: "ACCC", exactCase: true, acronym: "ACCC", stands: "Australian Competition and Consumer Commission",
    meaning: "The ACCC is Australia's consumer watchdog. It runs Scamwatch." },
  { id: "idcare", term: "IDCARE", category: "business", match: "IDCARE", exactCase: true, meaning: "IDCARE is Australia's free identity and cyber support service." },
  { id: "phishtank", term: "PhishTank", category: "web", match: "PhishTank|OpenPhish", exactCase: true, meaning: "PhishTank and OpenPhish are public lists of reported phishing websites." },
  { id: "spamhaus", term: "Spamhaus", category: "web", match: "Spamhaus", exactCase: true, meaning: "Spamhaus publishes lists of internet addresses run by criminals and spammers." },
  { id: "cve", term: "CVE", category: "cyber", match: "CVE(?:-\\d{4}-\\d+)?", exactCase: true, acronym: "CVE", stands: "Common Vulnerabilities and Exposures",
    meaning: "A CVE number is the public reference for one known security flaw." },
  { id: "vulnerability", term: "security flaw", category: "cyber", match: "vulnerabilit(?:y|ies)", meaning: "A security flaw is a weakness in software that attackers can use." },
  { id: "zero_day", term: "zero-day", category: "cyber", match: "zero-days?", meaning: "A zero-day is a security flaw attackers use before a fix is available." },
  { id: "allowlist", term: "allow list", category: "cyber", match: "allow ?list(?:ed|s)?|whitelist(?:ed|s)?", meaning: "An allow list is a list of things you've chosen to trust.", avoid: ["whitelist"] },
  { id: "false_positive", term: "false alarm", category: "cyber", match: "false positives?", meaning: "A false alarm is a warning about something that turns out to be fine." },
  { id: "official_directory", term: "Official Organisation Directory", category: "apollosg", match: "Official Organisation Directory", exactCase: true,
    meaning: "ApolloSG's Official Organisation Directory lists major Australian organisations' own websites, numbers and addresses, checked against their own pages." },
  { id: "observed_patterns", term: "observed patterns", category: "apollosg", match: "observed (?:patterns|intelligence)|separate devices",
    meaning: "ApolloSG remembers, as one-way codes, what earlier checks found about a website, number, address, message or file. It never keeps content, and only says whether something was previously reported and how confident it is." },

  // ── ApolloSG ──
  { id: "apollosg", term: "ApolloSG", category: "apollosg", match: "ApolloSG", exactCase: true, familiar: true, meaning: "ApolloSG is this app: your scam protection." },
  { id: "apollo", term: "Apollo", category: "apollosg", match: "Apollo(?!SG)", exactCase: true, familiar: true, meaning: "Apollo is ApolloSG's guard dog. It watches, checks and blocks where your device allows it." },
  { id: "higgins", term: "Higgins", category: "apollosg", match: "Higgins", exactCase: true, familiar: true, meaning: "Higgins explains what Apollo found and what you can do." },
  { id: "tc_flyby", term: "TC Hawkeye", category: "apollosg", match: "TC Hawkeye", exactCase: true, meaning: "TC Hawkeye is ApolloSG's quick investigator. It checks official sources, ApolloSG's knowledge base and one targeted search." },
  { id: "magnum_di", term: "Magnum DI", category: "apollosg", match: "Magnum DI", exactCase: true, meaning: "Magnum DI is ApolloSG's deep investigator. It looks only at what TC Hawkeye couldn't settle." },
  { id: "triage", term: "Higgins Triage", category: "apollosg", match: "(?:Higgins )?Triage", exactCase: true, meaning: "Higgins Triage is the first set of fixed rules every check goes through on your device." },
  { id: "threat_case", term: "Threat Case", category: "apollosg", match: "Threat Cases?", exactCase: true, meaning: "A Threat Case is ApolloSG's record of one thing it checked, with everything found about it." },
  { id: "threat_domain_list", term: "Threat Domain List", category: "apollosg", match: "Threat Domain Lists?", exactCase: true,
    meaning: "The Threat Domain List is ApolloSG's list of websites known to be dangerous. Apollo's website protection blocks the ones on it." },
  { id: "threat_domain_entry", term: "Threat Domain Entry", category: "apollosg", match: "Threat Domain Entr(?:y|ies)", exactCase: true,
    meaning: "A Threat Domain Entry is one dangerous website on ApolloSG's Threat Domain List." },
  { id: "gate", term: "Gate", category: "apollosg", match: "(?:Site|Link|Text|Call|Email|File|App|Device|Internet|Account) Gate", exactCase: true,
    meaning: "A Gate is one of Apollo's protections, such as the Text Gate for messages or the Call Gate for calls." },
  { id: "evidence_level", term: "evidence level", category: "apollosg", match: "evidence levels?|L[1-4] —", meaning: "The evidence level says how much of the original Apollo received, from pasted text (L1) up to the original itself." },
  { id: "simulated", term: "Simulated", category: "apollosg", match: "Simulated|SIMULATED", exactCase: true, meaning: "Simulated means a preview stood in for an outside service. It only appears in the preview build." },
];

export interface CompiledTerm extends LuddishTerm { re: RegExp }

/** Each term with its pattern ready to use; longer terms first, so "Google Safe Browsing" wins over "Safe Browsing". */
export const COMPILED: readonly CompiledTerm[] = [...DICTIONARY]
  .sort((a, b) => b.term.length - a.term.length)
  .map((t) => ({ ...t, re: new RegExp(`(?<![\\w-])(?:${t.match})(?![\\w-])`, t.exactCase ? "g" : "gi") }));

export const BY_ID: Readonly<Record<string, LuddishTerm>> = Object.fromEntries(DICTIONARY.map((t) => [t.id, t]));

/** The dictionary terms `text` uses, in the order they first appear. Longer terms claim their words first, so
 *  "the sender's domain" is the sender's domain, not also a domain. */
export function termsIn(text: string): LuddishTerm[] {
  const claimed: [number, number][] = [];
  const found: { term: LuddishTerm; at: number }[] = [];
  for (const t of COMPILED) {
    for (const m of text.matchAll(new RegExp(t.re.source, t.re.flags))) {
      const start = m.index ?? 0, end = start + m[0].length;
      if (claimed.some(([a, b]) => start < b && end > a)) continue;
      claimed.push([start, end]);
      if (!found.some((f) => f.term.id === t.id)) found.push({ term: t, at: start });
    }
  }
  return found.sort((a, b) => a.at - b.at).map((f) => f.term);
}

/** The entry a question names ("what is phishing", "what does SPF mean"), matched against the whole phrase. */
export function lookupTerm(phrase: string): LuddishTerm | null {
  const p = phrase.trim().replace(/[?.!]+$/, "").replace(/^(?:an?|the)\s+/i, "");
  for (const t of COMPILED) {
    if (new RegExp(`^(?:${t.match})$`, t.exactCase ? "" : "i").test(p) || p.toLowerCase() === t.term.toLowerCase() || (t.acronym && p === t.acronym)) return t;
  }
  return null;
}

export const termPattern = (t: LuddishTerm, flags = t.exactCase ? "g" : "gi") => new RegExp(`(?<![\\w-])(?:${t.match})(?![\\w-])`, flags);
export const phrasePattern = (s: string) => new RegExp(`(?<![\\w-])${escapeRe(s)}(?![\\w-])`, "gi");

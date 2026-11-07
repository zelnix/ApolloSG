// Higgins Luddish L1 — the Luddish Knowledge Library: approved background on how scams and security work, what ApolloSG
// does, its evidence levels, states, limits and what people can do. Each entry records where its knowledge comes from.
// The core rule: knowledge can explain evidence; knowledge cannot become case evidence. Entries are shown only in
// sections labelled as general knowledge, never as a finding. Pure: no React, no native imports.

export interface KnowledgeSource {
  publisher: string;
  url: string | null;
  /** authoritative: a government or official source; apollosg: ApolloSG's own rule book. */
  kind: "authoritative" | "apollosg";
}

export interface KnowledgeEntry {
  id: string;
  title: string;
  /** The dictionary terms (ids) this entry explains. */
  terms: string[];
  /** One or two sentences: the short answer. */
  brief: string;
  /** A fuller explanation. */
  explain: string;
  howItWorks?: string;
  whyItMatters?: string;
  source: KnowledgeSource;
}

const SCAMWATCH: KnowledgeSource = { publisher: "Scamwatch (ACCC)", url: "https://www.scamwatch.gov.au", kind: "authoritative" };
const ACSC: KnowledgeSource = { publisher: "Australian Cyber Security Centre", url: "https://www.cyber.gov.au", kind: "authoritative" };
const MONEYSMART: KnowledgeSource = { publisher: "Moneysmart (ASIC)", url: "https://moneysmart.gov.au", kind: "authoritative" };
const RULE_BOOK: KnowledgeSource = { publisher: "ApolloSG Rule Book", url: null, kind: "apollosg" };

export const KNOWLEDGE: readonly KnowledgeEntry[] = [
  { id: "phishing", title: "Phishing", terms: ["phishing", "smishing", "credentials"], source: SCAMWATCH,
    brief: "Phishing is a fake message or website made to trick you into handing over passwords, codes or money.",
    explain: "Phishing messages pretend to come from a bank, a government agency or a company you know. They usually push you to act quickly, then send you to a fake website that asks for your details.",
    howItWorks: "The message gets you to tap a link. The link opens a website made to look like the real one. Anything you type there goes to the scammer.",
    whyItMatters: "Your password, card details or a one-time code are enough for a scammer to get into your account or take money." },
  { id: "impersonation", title: "Pretending to be an organisation", terms: ["impersonation", "display_name", "spoofing"], source: SCAMWATCH,
    brief: "Impersonation means pretending to be a real person or organisation.",
    explain: "Scammers use a real organisation's name, logo or wording so you trust the message. The name alone proves nothing: what matters is whether the links, numbers and addresses really belong to that organisation.",
    howItWorks: "Anyone can put any name on a message, an email's display name or a caller ID. Only the organisation's own website, numbers and addresses show it's really them.",
    whyItMatters: "If you trust the name and use the contact details in the message, you end up talking to the scammer." },
  { id: "lookalike", title: "Lookalike addresses", terms: ["lookalike", "punycode", "domain"], source: ACSC,
    brief: "A lookalike address copies a real organisation's name with small changes.",
    explain: "A lookalike adds words (\"commbank-secure\"), swaps letters (\"0\" for \"o\") or uses a different ending (\".net\" instead of \".com.au\"), so it looks right at a glance.",
    howItWorks: "Apollo compares the address with the organisation's own published domains. A different domain carrying the organisation's name is a warning sign by itself.",
    whyItMatters: "Whoever runs the lookalike gets whatever you type into it, not the real organisation." },
  { id: "new_domain", title: "Newly registered web addresses", terms: ["registration_record"], source: ACSC,
    brief: "Every web address has a public record of when it was set up.",
    explain: "Scam websites are often set up days before they're used and dropped soon after. A new address is worth weighing with the other evidence. Being new doesn't prove a website is harmful.",
    howItWorks: "Apollo reads the address's public registration record, which says when it was registered and through which company." },
  { id: "redirect", title: "Redirects", terms: ["redirect", "url_shortener"], source: ACSC,
    brief: "A redirect sends you on from the address you tapped to a different one.",
    explain: "Many real websites redirect, so a redirect isn't a warning sign by itself. It matters when the link ends up somewhere other than the organisation it claims to be.",
    howItWorks: "Apollo follows the link's steps without showing you the page, and records where it finally lands." },
  { id: "threat_lists", title: "Threat lists", terms: ["blocklist", "safe_browsing", "phishtank", "spamhaus"], source: ACSC,
    brief: "Threat lists are public lists of websites and addresses already known to be harmful.",
    explain: "Apollo checks links against Google Safe Browsing and free public lists such as PhishTank, OpenPhish and Spamhaus. Being listed is strong evidence. Not being listed only means no list has reported it yet.",
    howItWorks: "Each list is checked for the exact address. Apollo records which lists answered and what each said, and an out-of-date list counts as not checked.",
    whyItMatters: "A new scam website can be live for hours before any list knows about it, so \"not listed\" is never the same as \"safe\"." },
  { id: "number_risk", title: "Number risk checks", terms: ["ipqs", "number_reputation", "voip"], source: RULE_BOOK,
    brief: "A number risk check looks up whether a phone number has been reported or used for scams.",
    explain: "The check gives a likelihood, not proof. A risky score is one warning sign to weigh with the rest of the evidence, and a clean score doesn't show the caller is who they say.",
    howItWorks: "ApolloSG sends only the number to IPQualityScore, which compares it with reports and how the number is set up, such as whether it's an internet (VoIP) number." },
  { id: "caller_id", title: "Faked caller ID", terms: ["caller_id", "spoofing", "carrier"], source: ACSC,
    brief: "Caller ID is the number or name your device shows for a call. It can be faked.",
    explain: "Scammers can make a call look like it comes from your bank or a government agency. Hang up and call the organisation back on a number you find yourself.",
    howItWorks: "The network passes on whatever number the caller's system sends. Australian phone companies block many faked numbers, but not all." },
  { id: "email_checks", title: "How email is checked", terms: ["spf", "dkim", "dmarc", "email_headers", "sender_domain", "reply_to"], source: ACSC,
    brief: "Email has built-in checks that the receiving mail server records: SPF, DKIM and DMARC.",
    explain: "These checks show whether the sending server was allowed to send for the domain and whether the email was changed. A pass only says the domain sent it, not that the domain is honest.",
    howItWorks: "The receiving mail server runs SPF, DKIM and DMARC and writes the results into the email's headers. Apollo reads those recorded results; it doesn't run them again itself.",
    whyItMatters: "A scam can pass every check if the scammer owns the domain, so the domain itself still has to be the organisation's own." },
  { id: "evidence_levels", title: "Evidence levels", terms: ["evidence_level", "eml"], source: RULE_BOOK,
    brief: "The evidence level says how much of the original Apollo received.",
    explain: "Pasted text (L1) shows only the words. A shared or mailbox copy (L2) adds some details. The original itself, such as the original email file (L3), lets Apollo read who really sent it.",
    howItWorks: "Higgins Triage records the level for every check. A higher level never changes earlier evidence; it can only add to it." },
  { id: "apollo_states", title: "Apollo's states", terms: ["apollo"], source: RULE_BOOK,
    brief: "Apollo shows how worried it is by how it behaves.",
    explain: "Patrolling means no concern was found in the checks that completed. Sniffing means it's looking closer. Growling is a possible concern. Barking is a significant concern that needs your attention. Biting means something was really blocked." },
  { id: "investigation", title: "How ApolloSG investigates", terms: ["triage", "tc_flyby", "magnum_di", "higgins", "threat_case"], source: RULE_BOOK,
    brief: "Every check runs through fixed rules on your device first, then TC Hawkeye, and Magnum DI only if needed.",
    explain: "Higgins Triage applies ApolloSG's fixed rules. If something is possible or can't be settled, TC Hawkeye checks official sources, ApolloSG's knowledge base and one targeted search. Magnum DI looks deeper only at what could still change the answer. Higgins then explains the result.",
    howItWorks: "Each step records what it checked and what it found. Higgins can explain those records but never adds findings of its own." },
  { id: "limited_result", title: "Limited and undetermined results", terms: [], source: RULE_BOOK,
    brief: "A limited result means some checks couldn't run, so Apollo can't give a full answer.",
    explain: "When a lookup doesn't answer or the evidence isn't enough, Apollo says so instead of guessing. It can't say it's a threat, and it can't say it isn't.",
    whyItMatters: "What wasn't checked could still matter, so treat it with caution." },
  { id: "blocked_vs_detected", title: "Blocked or detected", terms: ["gate", "private_dns"], source: RULE_BOOK,
    brief: "Blocked means something was actually stopped. Detected means it was noticed and you were warned.",
    explain: "Apollo only says something was blocked when the blocking really happened, and it names what did the blocking: Apollo's own protection, your device's system or your device company.",
    howItWorks: "Where a phone allows it, Apollo's Gates stop known harmful websites and calls. Everywhere else Apollo warns you and you decide." },
  { id: "remote_access", title: "Remote access scams", terms: ["remote_access", "accessibility_service", "device_admin"], source: SCAMWATCH,
    brief: "Remote access lets someone else control your device from somewhere else.",
    explain: "Scammers pose as tech support, a bank or a telco and ask you to install an app so they can \"fix\" something. Once in, they can see your screen and move your money.",
    whyItMatters: "No real bank or telco asks you to install a remote access app because of a call or message." },
  { id: "payments", title: "Payment requests", terms: ["payid", "gift_cards", "cryptocurrency", "seed_phrase"], source: SCAMWATCH,
    brief: "Scammers ask for payment methods that are hard to trace or reverse.",
    explain: "Gift cards, cryptocurrency, PayID to a stranger and bank transfers to new accounts are hard to get back once sent. A sudden request to pay this way, especially with pressure to hurry, is a strong warning sign.",
    whyItMatters: "Money sent this way usually can't be recovered, so check before you pay." },
  { id: "one_time_codes", title: "One-time codes", terms: ["one_time_code", "otp", "mfa"], source: ACSC,
    brief: "A one-time code is the short code a service sends to prove it's you.",
    explain: "Never share a code with anyone who contacts you. Real organisations never ask for it, and a scammer who has it can get into your account even without your password." },
  { id: "data_breaches", title: "Data breaches", terms: ["data_breach", "compromised", "password_manager", "idcare"], source: ACSC,
    brief: "A data breach is when a company loses control of the information it holds about people.",
    explain: "If your details were in a breach, change that password and any account that uses the same one, turn on two-step sign-in, and watch for scams that use your details to sound convincing." },
  { id: "official_contacts", title: "Official contacts", terms: ["official_directory"], source: RULE_BOOK,
    brief: "ApolloSG keeps a directory of major Australian organisations' own websites, numbers and addresses.",
    explain: "Each contact is checked against the organisation's own pages. A number or address in a message that isn't on that list may still be real, so ApolloSG warns you and gives you the organisation's own number to call instead.",
    howItWorks: "The directory is refreshed from each organisation's own contact pages. Only the contacts in what you checked are compared, and nothing is kept." },
  { id: "observed_patterns", title: "Previous reports", terms: ["observed_patterns"], source: RULE_BOOK,
    brief: "ApolloSG may say a website, number, address, message or file has been previously reported, and how confident it is.",
    explain: "A previous report is never evidence on its own: it can only make Higgins more confident in what this check found. It never says who reported it or how many times, and mixed previous reports add nothing. Only one-way codes are kept, never content." },
  { id: "apps", title: "Harmful apps", terms: ["apk", "sideloading", "stalkerware", "ransomware", "trojan", "malware"], source: ACSC,
    brief: "Harmful apps pretend to be useful so you'll install them.",
    explain: "Apps from outside the official app store skip its safety checks. Watch for apps that ask for accessibility access, device admin or to read your notifications without a clear reason." },
  { id: "network", title: "Networks and connections", terms: ["vpn", "public_wifi", "dns", "tls", "https", "certificate", "ip_address"], source: ACSC,
    brief: "Your connection decides who can see where your device goes online.",
    explain: "Public Wi-Fi is shared, so avoid signing in to banking on it unless you use a VPN. A padlock (HTTPS) only means the connection is encrypted; scam websites have one too." },
  { id: "reporting", title: "Reporting a scam", terms: ["scamwatch", "acsc", "acma", "accc", "idcare", "asic", "afsl", "abn", "cve", "vulnerability", "zero_day"], source: SCAMWATCH,
    brief: "Reporting a scam helps warn others and can help you recover.",
    explain: "Report scams to Scamwatch at scamwatch.gov.au. If you've lost money or details, contact your bank straight away, then IDCARE for free support. Report cybercrime to the Australian Cyber Security Centre at cyber.gov.au." },
  { id: "investment", title: "Investment scams", terms: ["investment_scam", "romance_scam", "family_impersonation", "bec"], source: MONEYSMART,
    brief: "Investment scams promise high returns with little risk.",
    explain: "Check that any investment business holds an Australian financial services licence on ASIC's register before you send money. Pressure to act fast, guaranteed returns or requests to pay in crypto are warning signs." },
];

export const KNOWLEDGE_BY_ID: Readonly<Record<string, KnowledgeEntry>> = Object.fromEntries(KNOWLEDGE.map((k) => [k.id, k]));

/** The entries that explain the given dictionary terms, in the terms' order (each entry once). */
export function knowledgeFor(termIds: string[]): KnowledgeEntry[] {
  const out: KnowledgeEntry[] = [];
  for (const id of termIds) {
    const entry = KNOWLEDGE.find((k) => k.terms.includes(id));
    if (entry && !out.includes(entry)) out.push(entry);
  }
  return out;
}

/** Every sentence the library holds — the Evidence Fidelity Check keeps them out of evidence sections. */
export const KNOWLEDGE_TEXTS: readonly string[] = KNOWLEDGE.flatMap((k) => [k.brief, k.explain, k.howItWorks ?? "", k.whyItMatters ?? ""]).filter(Boolean);

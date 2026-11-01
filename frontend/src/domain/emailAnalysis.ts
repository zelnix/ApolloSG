// Gate 1 — Email Protection (on-device). Parses a pasted or forwarded email (headers optional), then checks
// who it really came from vs. who it claims to be, links, attachments and the ask — and hands account alerts
// to Account Guard and links to the Web gate. Unknown sender ≠ scam; a real brand's own domain ≠ proof either.

import { extractSignals, organisationNamed, type MessageSignals } from "./messageAnalysis.ts";
import { readRequests } from "./requestSignals.ts";
import { isCountrySite } from "./brand.ts";
import type { ApolloState } from "./types";

export interface ParsedEmail { fromName: string | null; fromAddress: string | null; replyTo: string | null; subject: string | null; body: string; attachments: string[] }
export interface EmailAnalysis {
  scenario: string; title: string; state: ApolloState; verdict: string; why: string[]; recommendation: string;
  parsed: ParsedEmail; senderDomain: string | null; replyToDomain: string | null; claimedBrand: string | null; brandKind: MessageSignals["brandKind"];
  urls: string[]; lookalikeUrls: string[]; riskyAttachments: string[]; signals: MessageSignals; signalLabels: string[];
  handoff: { account: boolean; web: boolean; file: boolean }; verifySender: string; technical: string[];
  /** The sender's domain isn't the claimed brand's; Reply-To goes to another domain; bank details said to change. */
  senderMismatch: boolean; replyMismatch: boolean; bankChange: boolean;
}

/** Official sending domains per brand family (suffix-matched). Anything else claiming the brand is suspect. */
const OFFICIAL: { re: RegExp; domains: string[] }[] = [
  { re: /commbank|commonwealth\s?bank|netbank|\bcba\b/i, domains: ["commbank.com.au", "cba.com.au"] }, { re: /westpac/i, domains: ["westpac.com.au"] }, { re: /\banz\b/i, domains: ["anz.com", "anz.com.au"] }, { re: /\bnab\b|national australia bank/i, domains: ["nab.com.au"] },
  { re: /macquarie/i, domains: ["macquarie.com.au", "macquarie.com"] }, { re: /bendigo\s?bank/i, domains: ["bendigobank.com.au"] },
  { re: /paypal/i, domains: ["paypal.com", "paypal.com.au"] }, { re: /auspost|australia post/i, domains: ["auspost.com.au"] }, { re: /linkt/i, domains: ["linkt.com.au"] },
  { re: /\bato\b|tax office/i, domains: ["ato.gov.au"] }, { re: /mygov|services australia|centrelink|medicare/i, domains: ["my.gov.au", "servicesaustralia.gov.au"] },
  { re: /telstra/i, domains: ["telstra.com", "telstra.com.au"] }, { re: /optus/i, domains: ["optus.com.au"] }, { re: /microsoft|outlook|office ?365/i, domains: ["microsoft.com", "microsoftonline.com", "outlook.com", "office.com", "live.com"] },
  { re: /google|gmail/i, domains: ["google.com", "gmail.com", "accounts.google.com"] }, { re: /apple|icloud/i, domains: ["apple.com", "icloud.com", "email.apple.com"] }, { re: /netflix/i, domains: ["netflix.com"] }, { re: /amazon/i, domains: ["amazon.com", "amazon.com.au"] }, { re: /facebook|instagram|meta/i, domains: ["facebookmail.com", "facebook.com", "instagram.com"] },
];
const RISKY_ATTACH = /\.(exe|scr|bat|cmd|js|vbs|ps1|hta|jar|lnk|iso|img|html?|zip|rar|7z|docm|xlsm|apk|mobileconfig)\b/i;
const FREEMAIL = /^(gmail|yahoo|hotmail|outlook|live|icloud|protonmail|proton|aol|mail)\.(com|com\.au|me)$/i;

// Who the email presents itself as: its From display name, else how its text introduces or signs itself ("This is Sam
// from Apple Support", "The PayPal Team", "Regards, CommBank"). Never every organisation it mentions — a retailer
// selling Apple products is not impersonating Apple. Mirror of backend services/triage/speaker.py.
const NAME = String.raw`([A-Z][\w&'’.-]*(?:\s+[A-Z][\w&'’.-]*){0,3})`;
const SIGN_OFF = new RegExp(String.raw`(?:^|\n)\s*(?:(?:kind|best|warm)\s+regards|regards|sincerely|thanks|thank you|cheers|from)[,\s]+(?:the\s+)?${NAME}`, "gim");
const TEAM = new RegExp(String.raw`\b(?:[Tt]he\s+)?${NAME}\s+(?:Team|Support|Security|Customer Service|Service Centre|Accounts Team|Billing)\b`, "g");
export function claimedSpeaker(fromName: string | null, body: string): string | null {
  const candidates = [fromName, organisationNamed(body), ...Array.from(body.matchAll(SIGN_OFF), (m) => m[1]), ...Array.from(body.matchAll(TEAM), (m) => m[1])];
  return candidates.find((c): c is string => !!c && OFFICIAL.some((o) => o.re.test(c))) ?? null;
}

export function isSuffixOf(host: string, domain: string) { return host === domain || host.endsWith(`.${domain}`); }
function domainOf(addr: string | null): string | null { const m = addr?.toLowerCase().match(/@([a-z0-9.-]+\.[a-z]{2,})/); return m ? m[1] : null; }
function hostOf(u: string) { return u.replace(/^https?:\/\//i, "").split(/[/?#]/)[0].toLowerCase().replace(/^www\./, ""); }

export function parseEmail(raw: string, fields: { from?: string; subject?: string } = {}): ParsedEmail {
  const lines = raw.split(/\r?\n/);
  const hdr = (name: string) => { const re = new RegExp(`^\\s*(?:>\\s*)?${name}\\s*:\\s*(.+)$`, "i"); for (const l of lines.slice(0, 40)) { const m = l.match(re); if (m) return m[1].trim(); } return null; };
  const fromLine = fields.from?.trim() || hdr("From") || hdr("Sender");
  let fromName: string | null = null, fromAddress: string | null = null;
  if (fromLine) {
    const m = fromLine.match(/^"?([^"<]*)"?\s*<([^>]+)>/) ?? fromLine.match(/^(.*?)\s*\(([^)]+@[^)]+)\)/);
    if (m) { fromName = m[1].trim() || null; fromAddress = m[2].trim(); }
    else if (/@/.test(fromLine)) fromAddress = fromLine.replace(/^mailto:/i, "").trim();
    else fromName = fromLine;
  }
  const replyRaw = hdr("Reply-To");
  const replyTo = replyRaw ? (replyRaw.match(/<([^>]+)>/)?.[1] ?? replyRaw).trim() : null;
  const subject = fields.subject?.trim() || hdr("Subject");
  const attRaw = hdr("Attachments?") ?? hdr("Attached");
  const found = Array.from(new Set([...(attRaw ? attRaw.split(/[,;]\s*/) : []), ...(raw.match(/\b[\w-]+(?:\.[\w-]+)*\.(pdf|docx?|xlsx?|docm|xlsm|zip|rar|7z|exe|scr|js|html?|iso|img|apk|lnk|jar|mobileconfig)\b/gi) ?? [])].map((a) => a.trim()).filter(Boolean)));
  // "Invoice.pdf.exe" also matches "Invoice.pdf" — keep only the longest name.
  const attachments = found.filter((a) => !found.some((b) => b !== a && b.startsWith(a))).slice(0, 10);
  const bodyStart = lines.findIndex((l, i) => i > 0 && l.trim() === "" && lines.slice(0, i).some((h) => /^\s*(from|subject|to|date|reply-to)\s*:/i.test(h)));
  const body = (bodyStart > 0 ? lines.slice(bodyStart + 1) : lines.filter((l) => !/^\s*(from|to|cc|date|subject|reply-to|sender|attachments?)\s*:/i.test(l))).join("\n").trim();
  return { fromName, fromAddress, replyTo, subject, body, attachments };
}

/** `headers`: the original message's full headers were read (L3/L4) and `auth` is what its receiving mail server
 *  recorded — never re-checked. A recorded authentication failure means the From domain can't be taken at face value. */
export interface EmailHeaderEvidence { fullHeaders: boolean; auth?: { spf?: string | null; dkim?: string | null; dmarc?: string | null } | null }
const AUTH_FAILED = /^(fail|softfail|permerror|hardfail)$/;

export function analyseEmail(raw: string, fields: { from?: string; subject?: string } = {}, headers: EmailHeaderEvidence = { fullHeaders: false }): EmailAnalysis {
  const parsed = parseEmail(raw, fields);
  const auth = headers.fullHeaders ? headers.auth ?? null : null;
  // The receiving server recorded that the email failed DMARC (or SPF with no passing DKIM): the From domain is not proven.
  const spoofed = !!auth && (AUTH_FAILED.test(auth.dmarc ?? "") || (AUTH_FAILED.test(auth.spf ?? "") && auth.dkim !== "pass" && auth.dmarc !== "pass"));
  const full = `${parsed.subject ?? ""}\n${parsed.body}`;
  const sig = extractSignals(parsed.fromAddress ?? parsed.fromName ?? "", full);
  const senderDomain = domainOf(parsed.fromAddress);
  const replyToDomain = domainOf(parsed.replyTo);
  const claimText = `${parsed.fromName ?? ""} ${parsed.subject ?? ""}`;
  // The organisation the email speaks as — a brand it merely mentions (in its subject or text) is not its sender.
  const speaker = claimedSpeaker(parsed.fromName, parsed.body);
  const official = (speaker ? OFFICIAL.find((o) => o.re.test(speaker)) : undefined)
    // Gap #6: also match when the sender domain itself is in an OFFICIAL entry — but NOT for
    // freemail domains (gmail.com, outlook.com, etc.) since personal accounts on those platforms
    // are not official brand communications from Google/Microsoft.
    ?? (senderDomain && !FREEMAIL.test(senderDomain) ? OFFICIAL.find((o) => o.domains.some((d) => isSuffixOf(senderDomain, d))) : undefined);
  const senderMatchesConfiguredDomain = OFFICIAL.some((o) => !!senderDomain && o.domains.some((domain) => isSuffixOf(senderDomain, domain)));
  const brand = official ? (sig.claimedBrand && official.re.test(sig.claimedBrand) ? sig.claimedBrand : speaker ?? parsed.fromName ?? "this organisation") : null;
  const domainOfficial = !!(senderDomain && official && (official.domains.some((d) => isSuffixOf(senderDomain, d)) || isCountrySite(senderDomain, official.domains)));
  const senderOfficial = domainOfficial && !spoofed;
  const senderMismatch = !!(official && senderDomain && !senderOfficial);
  const brandInDomainOnly = !!(senderDomain && official && !senderOfficial && official.re.test(senderDomain.replace(/[.-]/g, " ")));
  const replyMismatch = !!(replyToDomain && senderDomain && replyToDomain !== senderDomain);
  const freemailBrand = !!(official && senderDomain && FREEMAIL.test(senderDomain));
  const urls = sig.urls;
  const lookalikeUrls = urls.filter((u) => { const h = hostOf(u); return official ? !official.domains.some((d) => isSuffixOf(h, d)) && !isCountrySite(h, official.domains) : false; });
  const riskyAttachments = parsed.attachments.filter((a) => RISKY_ATTACH.test(a));
  const invoice = /\binvoice\b|\bremittance\b|\bpayment details\b|\bbank details\b|\bbsb\b|\baccount number\b/i.test(full);
  const bankChange = invoice && /\b(new|updated|changed|different)\b.*\b(bank|account|bsb|payment) (details|account)\b/i.test(full);
  // An ask to log in, verify an account, update payment details or give a secret — read from what each sentence
  // does (requestSignals.ts). "password", "sign-in" or "unusual activity" on their own are a notice, not an ask.
  const asks = readRequests(full);
  const pressure = sig.urgency || sig.threat;
  // An ordinary sign-in, verification or payment-update request counts only with supporting context — the sender isn't
  // the organisation it presents itself as, a link goes off that organisation's site, replies go elsewhere, the
  // receiving server recorded failed authentication, or a threat with a deadline. Mirror of backend
  // services/triage_engine.py (`support`).
  const support = senderMismatch || replyMismatch || spoofed || lookalikeUrls.length > 0 || (sig.threat && sig.urgency);
  const accountAlert = sig.loginRequest || asks.secret_request || ((asks.sign_in_request || asks.payment_detail_update) && support);
  const securityAlert = /\bsecurity alert\b|\breview recent activity\b|\bsuspicious activity\b|\bnew device\b/i.test(full);
  const bec = /\b(ceo|director|manager|boss)\b/i.test(claimText) && (sig.giftCards || sig.moneyRequest || /\burgent(ly)?\b.*\b(transfer|pay|gift)/i.test(full)) && (!senderDomain || FREEMAIL.test(senderDomain) || replyMismatch);
  const signalLabels = [brand && `Claims to be ${brand}`, senderMismatch && "Sender domain isn't the brand's", replyMismatch && "Reply-To goes elsewhere", urls.length && `${urls.length} link${urls.length > 1 ? "s" : ""}`, lookalikeUrls.length && "Link off the official domain", riskyAttachments.length && "Risky attachment", sig.urgency && "Urgency", sig.threat && "Threat / penalty", accountAlert && "Account / login request", invoice && "Invoice / payment", sig.codeRequest && "Asks for a code"].filter(Boolean) as string[];
  const technical = [`From: ${parsed.fromName ?? "—"} <${parsed.fromAddress ?? "no address"}>`, `Sender domain: ${senderDomain ?? "unknown"}${official ? senderOfficial ? " (official for the claimed brand)" : " (NOT an official domain for the claimed brand)" : ""}`, parsed.replyTo ? `Reply-To: ${parsed.replyTo}${replyMismatch ? " (differs from sender)" : ""}` : "Reply-To: none", `Subject: ${parsed.subject ?? "—"}`, `Links: ${urls.length}${lookalikeUrls.length ? ` (${lookalikeUrls.length} off-domain)` : ""}`, `Attachments: ${parsed.attachments.length ? parsed.attachments.join(", ") : "none"}`, headers.fullHeaders ? "Note: SPF/DKIM/DMARC are shown as the receiving mail server recorded them — Apollo didn't re-check them." : "Note: Apollo can't verify SPF/DKIM/DMARC from pasted text — the mail app's headers would be needed.", "Important: Even when sender authentication passes, it confirms only the sending domain — not the email's content, intentions, or truthfulness."];
  const verifySender = official ? `Don't reply or use any link or number in the email. Open ${brand}'s official app, or type their address yourself, and check there.` : "If this claims to be a business you deal with, look up their number independently and call to confirm — especially before paying anything.";
  const handoff = { account: accountAlert || sig.codeRequest, web: urls.length > 0, file: riskyAttachments.length > 0 };
  const R = (scenario: string, title: string, state: ApolloState, verdict: string, why: string[], recommendation: string): EmailAnalysis =>
    ({ scenario, title, state, verdict, why: why.filter(Boolean), recommendation, parsed, senderDomain, replyToDomain, claimedBrand: brand, brandKind: sig.brandKind, urls, lookalikeUrls, riskyAttachments, signals: sig, signalLabels, handoff, verifySender, technical, senderMismatch, replyMismatch, bankChange });
  const fromWhy = spoofed && domainOfficial
    ? `It shows ${brand}'s address ${senderDomain}, but the receiving mail server recorded that it failed sender authentication — it wasn't proven to come from ${brand}.`
    : senderMismatch ? `It was sent from ${senderDomain}, which isn't ${brand}'s domain${brandInDomainOnly ? " — it just has the name inside it" : freemailBrand ? " — it's a free webmail address" : ""}.` : "";

  // E01 — brand impersonation: claims a brand, sent from elsewhere, with a login/payment ask or off-domain link.
  if (official && senderMismatch && (accountAlert || lookalikeUrls.length || pressure || sig.paymentRequest)) return R("E01", `Email impersonating ${brand}`, "barking", `This email says it's from ${brand}, but it wasn't sent from ${brand}. ${accountAlert ? "It wants you to log in — that's how they take the account." : "Don't act on it."}`, [fromWhy, lookalikeUrls.length ? `Its link goes to ${hostOf(lookalikeUrls[0])}, not ${brand}'s website.` : "", pressure ? "It uses pressure: urgency or a threat." : "", replyMismatch ? `Replies would go to ${replyToDomain}, somewhere else again.` : ""], `Delete it. ${verifySender} If you already clicked or logged in, use Stay With Me below.`);
  // E02 — account alert with off-domain link (even when brand unknown).
  if (accountAlert && (lookalikeUrls.length || (urls.length && !official))) return R("E02", "Account alert with a suspicious link", official ? "barking" : "growling", `This email wants you to log in or verify through a link${official ? ` that isn't ${brand}'s` : " Apollo can't match to a known service"}.`, ["Real account alerts never need you to log in through the email.", fromWhy, pressure ? "Urgency or a threat is the classic tell." : "Nothing bad happens until you click and type."], `Don't use the link. Open the service yourself. Account Gate can check the alert itself.`);
  // E03 — risky attachment.
  if (riskyAttachments.length) return R("E03", "Risky attachment", sig.unknownSender || senderMismatch || pressure || invoice ? "barking" : "growling", `The attachment ${riskyAttachments[0]} is a type that can run code or hide a program — not a normal document.`, [`Types like ${riskyAttachments.map((a) => a.split(".").pop()?.toUpperCase()).filter(Boolean).slice(0, 3).join(", ")} are how email malware arrives.`, fromWhy || (sig.unknownSender ? "The sender isn't someone you know." : "Even a known sender's account can be hijacked."), invoice ? "It's dressed up as an invoice or payment document." : ""], "Don't open it. Ask the sender by phone if you expected a file. Check This File can inspect it if you've already saved it.");
  // E04 — BEC / changed bank details.
  if (bankChange) return R("E04", "Invoice with changed bank details", "barking", "An invoice telling you the bank details have changed is the classic payment-redirection scam.", ["Businesses rarely change bank details — and never announce it only by email.", replyMismatch ? `Replies go to ${replyToDomain}, not the sender.` : fromWhy || "The sender's account could be hijacked even if the address looks right.", "Once paid, the money is usually gone."], "Don't pay yet. Phone the business on a number you already have (not from this email) and confirm the details.");
  if (bec) return R("E05", "Urgent request from 'the boss'", "barking", "An urgent, secretive request for a transfer or gift cards from a senior person is almost always business email compromise.", ["Real executives don't ask for gift cards or secret transfers by email.", fromWhy || (senderDomain && FREEMAIL.test(senderDomain) ? `It comes from a personal ${senderDomain} address.` : ""), replyMismatch ? `Replies would go to ${replyToDomain}.` : ""], "Don't act. Call the person on a number you already have and ask.");
  // E06 — code / identity requests.
  if (sig.codeRequest || sig.identityRequest) return R("E06", sig.codeRequest ? "Asks for a verification code" : "Asks for identity details", "barking", sig.codeRequest ? "No genuine organisation asks you to email a verification code." : "This email asks for identity or card details — real organisations don't collect them by email.", [fromWhy, pressure ? "It uses pressure to stop you thinking." : "", "Codes and ID details are exactly what's needed to take over accounts."], `Don't reply. ${verifySender}`);
  // E07 — brand mismatch without a clear ask.
  if (official && senderMismatch) return R("E07", `Says ${brand}, sent from elsewhere`, "growling", `The name says ${brand}, but the sending address doesn't belong to ${brand}. Treat it as suspicious.`, [fromWhy, urls.length ? `It contains ${urls.length} link${urls.length > 1 ? "s" : ""} — check them before tapping.` : "", "Some companies use third-party mailers, but banks and government don't send from random domains."], verifySender);
  // E08 — reply-to hijack.
  if (replyMismatch && (invoice || sig.paymentRequest || sig.moneyRequest)) return R("E08", "Replies go somewhere else", "growling", `Replying would go to ${replyToDomain}, not the address it appears to come from — a common trick in payment scams.`, ["Reply-To mismatches are how attackers hijack a real-looking conversation.", "It's about money or an invoice."], "Don't reply. Contact the sender through a number or address you already have.");
  // E09 — phishing pattern without brand (links + pressure).
  if (urls.length && pressure) return R("E09", "Urgent email with links", "growling", "It pushes you to act quickly through a link. Apollo will check where the link leads.", [`${urls.length} link${urls.length > 1 ? "s" : ""}, plus ${sig.threat ? "a threat or penalty" : "urgency"}.`, sig.unknownSender ? "The sender isn't someone you know." : "", "Nothing happens until you click — so check first."], "Check each link with ApolloSG before opening. Never log in or pay through an email link.");
  // E10 — invoice with links, no red flags.
  if (invoice && urls.length) return R("E10", "Invoice or payment email", "ears_up", "Invoices are routinely faked. Nothing obviously wrong here — but confirm before paying.", ["Links or attachments in invoices skip your usual checks.", "Check that the payee and amount match what you expected."], "Pay only via a payment method you've used with this business before, or confirm by phone.");
  if (securityAlert) return R("E14", "Security alert to verify", "ears_up", `The email claims there is account activity to review. ${headers.fullHeaders ? "Sender details alone cannot" : "Pasted sender details cannot"} authenticate that claim.`, [senderOfficial || senderMatchesConfiguredDomain ? "The visible sender domain matches a configured domain, which is supporting evidence only — not proof of legitimacy." : "The sender was not independently authenticated.", "Security alerts are routinely copied in phishing emails.", "Passing sender authentication confirms the domain, not the email's content or intentions."], senderMatchesConfiguredDomain ? "Do not reply or use details from the email. Open the claimed service's official app or type its known address yourself." : `Do not reply or use details from the email. ${verifySender}`);
  // E11 — official sender, expected content.
  if (official && senderOfficial) return R("E11", `Sent from ${brand}'s own domain`, urls.length ? "ears_up" : "resting", `This came from ${brand}'s official domain${urls.length ? ", and its links stay on their site" : ""}. That's a good sign — not a guarantee.`, [`Sender domain ${senderDomain} belongs to ${brand}.`, headers.fullHeaders ? "The receiving mail server's SPF, DKIM and DMARC results are shown with this check, exactly as it recorded them." : "Spoofing of a real domain is possible but rare; Apollo can't verify the mail server signatures from pasted text.", "Passing sender authentication confirms the sending domain, not the email's content or intentions.", urls.length ? "Still: open the app yourself rather than tapping links when money or logins are involved." : ""], "If it asks you to do something, do it through the official app or by typing the address yourself.");
  // E12 — links from unknown sender, no pressure.
  if (urls.length) return R("E12", "Email with links", "ears_up", "Nothing suspicious found in the wording — but it has links. Not alarming; just check before you tap.", ["No impersonation, pressure or dangerous attachments found.", `${urls.length} link${urls.length > 1 ? "s" : ""} inside.`], "Check a link before opening it if you weren't expecting this email.");
  // E13 — ordinary email.
  return R("E13", "Ordinary email", "resting", "I didn't find anything worrying in this email.", ["No links, risky attachments, impersonation or pressure detected.", headers.fullHeaders ? "Apollo read the original email, including the authentication results its receiving mail server recorded." : "Apollo can only see what you pasted — not the mail server's authentication headers.", "Coverage: Apollo checked the sender domain and text patterns. Link reputation and attachment malware scanning were not applicable (no links or risky attachments found)."], "Nothing to do. Come back if it asks you to log in, pay or install anything.");
}

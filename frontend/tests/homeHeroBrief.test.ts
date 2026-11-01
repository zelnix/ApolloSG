// The Home hero: two lines per case, read only from the case's authoritative record (its Case Briefing, else what
// Higgins Triage recorded), with Higgins' actual recommendation — never a generic "Action required".
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildHeroBriefs, clip, eventBrief, heroWhen, keptIdentifiers } from "../src/domain/homeHeroBrief.ts";
import type { AttentionItem } from "../src/domain/homeAttention";
import type { HomeVoice } from "../src/domain/higginsHomeVoice";
import type { EventBriefing } from "../src/domain/caseBriefing";
import type { PatrolEvent } from "../src/domain/types";

const NOW = new Date(2026, 9, 28, 18, 0);
const AT = new Date(2026, 9, 28, 16, 42).toISOString();

const event = (over: Partial<PatrolEvent>): PatrolEvent => ({
  event_id: "e1", device_id: "d1", category: "email", state: "barking", status: "active",
  headline: "Email impersonating Example", what_happened: "", why: [], what_to_do: "", indicator_host: null, indicator_digest: null,
  verified_block: false, adapter_label: "Apollo", occurred_at: AT, resolved_at: null, ...over,
});
const briefing = (over: Partial<EventBriefing>): EventBriefing => ({
  headline: "Example email checked", summary: "A finding.", subject: null, findings: [], unresolved: [], status: "Likely scam",
  statusReason: "", userActionRequired: false, actionReason: null, recommendedAction: null, from: "briefing", ...over,
});
const voice: HomeVoice = { text: "No security threats currently detected within Apollo's current protection capability.", ctaLabel: "View protection", ctaRoute: "/(tabs)/protection", spoken: "" };

test("an email reads as type, subject, sender and finding, then when and Higgins' recommendation", () => {
  const b = eventBrief(event({
    source_metadata: { type: "email", sender: "support@example.com", subject: "Account verification required" },
    case_briefing: briefing({ recommendedAction: { label: "Don't open the link", instruction: "Don't open it and don't enter anything on it." } }),
  }), NOW);
  assert.equal(b.line1, "Email: \u201CAccount verification required\u201D from support@example.com, detected as a likely scam.");
  assert.equal(b.line2, "28 Oct, 4:42 pm. Don't open the link.");
  assert.equal(b.route, "/patrol/e1", "tapping opens the Threat Case");
});

test("long subjects and addresses are shortened to keep the two lines", () => {
  const b = eventBrief(event({
    source_metadata: { type: "email", sender: "notifications-security-team@very-long-example-domain.co", subject: "URGENT: unusual sign-in detected — verify within 24 hours or lose access" },
    case_briefing: briefing({ status: "Concerning", recommendedAction: { label: "Don't reply.", instruction: "x" } }),
  }), NOW);
  assert.match(b.line1, /^Email: \u201CURGENT: unusual sign-in\u2026\u201D from notifications-security-team\u2026, detected as concerning\.$/);
  assert.equal(b.line2, "28 Oct, 4:42 pm. Don't reply.");
});

test("the finding is the case's own status; Unable to determine is never shown as safe", () => {
  const b = eventBrief(event({ category: "link", local_indicator: "https://www.st0ko-login.co/verify?x=1", case_briefing: briefing({ status: "Unable to determine", recommendedAction: { label: "Check before using it", instruction: "x" } }) }), NOW);
  assert.equal(b.line1, "Link: st0ko-login.co, not confirmed safe.");
  assert.equal(b.line2, "28 Oct, 4:42 pm. Check before using it.");
});

test("a call names the number; Higgins Triage's short step is used when there is no briefing", () => {
  const b = eventBrief(event({ category: "call", local_indicator: "+61 448 221 905", what_to_do: "Hang up. Then call the bank on the number on your card." }), NOW);
  assert.equal(b.line1, "Call from +61 448 221 905, detected as a possible threat.");
  assert.equal(b.line2, "28 Oct, 4:42 pm. Hang up.");
});

test("while TC FlyBy or Magnum DI is still working the hero says to be careful, never 'Action required'", () => {
  const b = eventBrief(event({ category: "message", investigation_case_id: "c1", what_to_do: "Don't reply to this message or call any number in it until you've checked." }), NOW);
  assert.equal(b.line1, "Text message (no # found), detected as a possible threat.");
  assert.equal(b.line2, "28 Oct, 4:42 pm. Be careful until Higgins has finished.");
  assert.ok(!/action required/i.test(b.line1 + b.line2));
});

test("a text names its number: recorded on the case, kept with the original, or 'no # found'", () => {
  const sms = event({ category: "message", case_briefing: briefing({ status: "Concerning", recommendedAction: { label: "Don't act on it yet", instruction: "x" } }) });
  const kept = keptIdentifiers({ fields: [{ label: "From", value: "0419 841 238" }], text: "Good morning! It's UNI\uFB01ed Energy here. Lock in higher STC savings." });
  assert.equal(eventBrief(sms, NOW, kept).line1, "Text message: \u201CGood morning! It's UNI\uFB01ed\u2026\u201D from 0419 841 238, detected as concerning.");
  assert.equal(eventBrief(sms, NOW, { ...kept!, sender: null }).line1, "Text message: \u201CGood morning! It's UNI\uFB01ed\u2026\u201D (no # found), detected as concerning.");
  assert.equal(eventBrief({ ...sms, source_metadata: { type: "text", sender: "+61 448 221 905" } }, NOW).line1, "Text message from +61 448 221 905, detected as concerning.");
  assert.equal(eventBrief(event({ category: "call" }), NOW).line1, "Call (no # found), detected as a possible threat.");
});

test("an 'Important for you' card has the hero's structure with more room for detail", () => {
  const sms = event({ category: "message", case_briefing: briefing({ status: "Concerning", recommendedAction: { label: "Don't act on it yet", instruction: "x" } }) });
  const kept = keptIdentifiers({ fields: [], text: "Good morning! It's UNI\uFB01ed Energy here. Lock in higher STC savings before rebates drop next week." });
  const card = eventBrief(sms, NOW, kept, "card");
  assert.equal(card.line1, "Text message: \u201CGood morning! It's UNI\uFB01ed Energy here. Lock in higher STC savings before rebates drop next week.\u201D (no number found), detected as concerning.", "a card shows the text whole, no fixed cut");
  assert.equal(card.line2, eventBrief(sms, NOW, kept).line2, "the same date and recommendation as the hero");
});

test("a long Triage step falls back to 'Be careful'; a verified block needs nothing", () => {
  assert.match(eventBrief(event({ category: "message", source_metadata: { type: "text", preview: "Your parcel is waiting, pay the fee now" }, what_to_do: "Don't reply to this message or call any number in it until you've checked." }), NOW).line2, /\. Be careful\.$/);
  const blocked = eventBrief(event({ category: "website", state: "biting", indicator_host: "paypal-secure.top", verified_block: true, enforcement_evidence: {} as never }), NOW);
  assert.equal(blocked.line1, "Website: paypal-secure.top, blocked by Apollo.");
  assert.equal(blocked.line2, "28 Oct, 4:42 pm. No action needed.");
});

test("an email you submitted is named from the original kept on this device", () => {
  const kept = keptIdentifiers({ fields: [{ label: "From", value: "security@commbank-alerts.co" }, { label: "Subject", value: "URGENT: unusual sign-in" }], text: "Dear Customer" });
  const b = eventBrief(event({ case_briefing: briefing({ subject: "commbank-secure-verify.co", recommendedAction: { label: "Don't use the link", instruction: "x" } }) }), NOW, kept);
  assert.equal(b.line1, "Email: \u201CURGENT: unusual sign-in\u201D from security@commbank-alerts.co, detected as a likely scam.");
  assert.equal(b.line2, "28 Oct, 4:42 pm. Don't use the link.");
  assert.equal(eventBrief(event({ case_briefing: briefing({ subject: "commbank-secure-verify.co" }) }), NOW).line1, "Email: commbank-secure-verify.co, detected as a likely scam.", "without a kept original, the briefing's subject");
});

test("heroWhen adds the year only when it isn't this year", () => {
  assert.equal(heroWhen(new Date(2025, 0, 3, 9, 5).toISOString(), NOW), "3 Jan 2025, 9:05 am");
  assert.equal(heroWhen(new Date(2026, 9, 28, 0, 0).toISOString(), NOW), "28 Oct, 12:00 am");
  assert.equal(clip("short", 10), "short");
});

test("the hero lists the case Apollo is reacting to first, then other cases, then protection problems", () => {
  const driving = event({ event_id: "d", category: "website", state: "ears_up", indicator_host: "a.co" });
  const other = event({ event_id: "o", category: "call", local_indicator: "0400 000 000" });
  const attention = [
    { id: "gate:site", kind: "gate", gate: "Site Gate", title: "Site Gate needs attention", problem: "", higgins: "", actionLabel: "Turn on Site Gate", route: "/gates" },
    { id: "event:o", kind: "event", gate: "Call screening", title: "", problem: "", higgins: "", actionLabel: "", route: "/patrol/o", event: other },
  ] as AttentionItem[];
  const briefs = buildHeroBriefs({ voice, attention, drivingEvent: driving, state: "ears_up", now: NOW });
  assert.deepEqual(briefs.map((b) => b.id), ["event:d", "event:o", "gate:site"]);
  assert.equal(briefs[2].line1, "Site Gate needs attention.");
  assert.equal(briefs[2].line2, "Not a security threat. Turn on Site Gate.");
});

test("with nothing to show, Apollo's status is two short lines", () => {
  const [b] = buildHeroBriefs({ voice, attention: [], drivingEvent: null, state: "resting", now: NOW });
  assert.equal(b.line1, "No security threats detected.");
  assert.equal(b.line2, "Apollo is keeping watch. No action needed.");
});

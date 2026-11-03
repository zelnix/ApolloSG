// Notification text: HTML entities decoded once at the presentation boundary, a purpose-built short
// summary, and the authoritative event left untouched. Run: node --test tests/notificationText.test.ts
import assert from "node:assert/strict";
import test from "node:test";

import type { PatrolEvent } from "../src/domain/types.ts";
import { eventLocalAlert } from "../src/push/localAlerts.ts";
import { decodeHtmlEntities } from "../src/utils/decodeHtmlEntities.ts";
import { notificationSummary, presentAlertText } from "../src/push/notificationText.ts";
import { completedCheckAlert } from "../src/push/protectionAlerts.ts";

const when = new Date().toISOString();
const ev = (extra: Partial<PatrolEvent> = {}): PatrolEvent => ({
  event_id: "evt-1", device_id: "local", category: "link", state: "growling", status: "active",
  headline: "This link to &quot;instagram.com-verify.top&quot; copies Instagram&#39;s login &amp; asks for your password",
  what_happened: "Higgins&#39; full explanation: the page at &quot;instagram.com-verify.top&quot; imitates Instagram &lt;login&gt; and was registered 3 days ago.",
  why: ["It uses Instagram&#39;s logo &amp; colours."], what_to_do: "Don&#39;t enter your password.",
  indicator_host: "instagram.com-verify.top", indicator_digest: null, verified_block: false, adapter_label: "device",
  occurred_at: when, resolved_at: null, background: false, investigation_case_id: "case-1", claimed_brand: "Instagram", ...extra,
});

test("entities decode once: quoted domains, ampersands, apostrophes, angle brackets and numeric forms", () => {
  assert.equal(decodeHtmlEntities("&quot;instagram.com&quot;"), "\"instagram.com\"");
  assert.equal(decodeHtmlEntities("AT&amp;T &amp; Telstra"), "AT&T & Telstra");
  assert.equal(decodeHtmlEntities("Instagram&#39;s, Apollo&apos;s, it&#x27;s, it&#X27;s"), "Instagram's, Apollo's, it's, it's");
  assert.equal(decodeHtmlEntities("&lt;script&gt; &lt;b&gt;"), "<script> <b>");
  assert.equal(decodeHtmlEntities("a&nbsp;b &ndash; c &mdash; d&hellip; &rsquo;x&lsquo; &ldquo;y&rdquo;"), "a b – c — d… ’x‘ “y”");
  assert.equal(decodeHtmlEntities("&#128680; &#x1F6A8;"), "🚨 🚨");
  assert.equal(decodeHtmlEntities("&AMP; &QUOT;"), "& \"");
});

test("decoding happens exactly once — double-encoded text is not decoded twice", () => {
  assert.equal(decodeHtmlEntities("&amp;quot;paypal.com&amp;quot;"), "&quot;paypal.com&quot;");
  assert.equal(decodeHtmlEntities("&amp;amp;"), "&amp;");
});

test("unknown, malformed and invalid entities are left exactly as written", () => {
  assert.equal(decodeHtmlEntities("Tom & Jerry; R&D; &unknown; &#0; &#xD800; &#99999999; &amp"), "Tom & Jerry; R&D; &unknown; &#0; &#xD800; &#99999999; &amp");
  assert.equal(decodeHtmlEntities("no entities here"), "no entities here");
});

test("the notification body is a short, specific summary naming the first concrete finding — not the Higgins explanation", () => {
  const alert = eventLocalAlert(ev({ background: true, category: "message", state: "growling" }))!;
  assert.equal(alert.body, "Higgins: The Instagram text you received has a warning sign: it uses Instagram&#39;s logo &amp; colours. Open ApolloSG to see what I found.");
  const sent = notificationSummary(ev({ why: [] }));
  assert.equal(sent, "Higgins: The Instagram link you sent has signs that need checking. Open ApolloSG to see what I found.");
  assert.ok(!sent.includes("registered 3 days ago") && !sent.includes("password"));
  assert.match(notificationSummary(ev({ state: "barking" })), /^Higgins: The Instagram link you sent looks like a scam: it uses Instagram&#39;s logo &amp; colours\. Don't act on it — open ApolloSG/);
  assert.match(notificationSummary(ev({ claimed_brand: null, why: [] })), /^Higgins: The instagram\.com-verify\.top link you sent has signs/);
  assert.match(notificationSummary(ev({ category: "email", claimed_brand: null, background: true, why: [], source_metadata: { type: "email", sender: "billing@acme.co" } })),
    /^Higgins: The email from billing@acme\.co has signs/);
  // A line about how the record was kept is never given as the reason.
  assert.equal(notificationSummary(ev({ why: ["ApolloSG's servers keep only this privacy-protected summary, not the content that was checked."] })),
    "Higgins: The Instagram link you sent has signs that need checking. Open ApolloSG to see what I found.");
  const limited = notificationSummary(ev({ state: "ears_up", why: [], triage_investigation: { outcome: "LIMITED_UNABLE_TO_DETERMINE" } as never }));
  assert.match(limited, /^Higgins: I couldn't fully check the Instagram link you sent\. Treat it with caution/);
  assert.doesNotMatch(limited, /safe|nothing to worry/i);
  assert.match(completedCheckAlert(ev({ background: true, status: "resolved" }))!.body, /^Higgins: I've finished checking the Instagram link/);
});

test("presented text has no entities, is never cut short, is in Higgins Luddish, and the authoritative event is untouched", () => {
  const event = ev({ claimed_brand: "AT&amp;T", state: "barking", background: true, category: "email", why: [] });
  const before = JSON.stringify(event);
  const shown = presentAlertText(eventLocalAlert(event)!);
  assert.equal(shown.body, "Higgins: The AT&T email you received looks like a scam. Don't act on it — open ApolloSG to see what I found.");
  assert.doesNotMatch(shown.title + shown.body, /&(amp|quot|#39|lt|gt);/);
  assert.equal(JSON.stringify(event), before, "the Threat Case keeps the complete explanation exactly as recorded");
  assert.match(event.what_happened, /^Higgins&#39; full explanation/);
  const long = presentAlertText({ title: `Apollo is barking at ${"x".repeat(90)}`, body: `${"word ".repeat(60)}&amp; end`, channel: "apollo_alerts", actionUrl: "/" });
  assert.equal(long.title, `Apollo is barking at ${"x".repeat(90)}`, "only the OS shortens a notification");
  assert.equal(long.body.toLowerCase(), `${"word ".repeat(60)}& end`);
  const quoted = presentAlertText({ title: "Apollo is growling at &quot;instagram.com&quot;", body: "It&#39;s   from\n&lt;billing@x.co&gt;", channel: "apollo_alerts", actionUrl: "/" });
  assert.equal(quoted.title, "Apollo is growling at \"instagram.com\"");
  assert.equal(quoted.body, "It's from <billing@x.co>");
  // Whoever composed it (a protection notice, a device reading), every alert reaches the person in Luddish.
  const plain = presentAlertText({ title: "ApolloSG updated your protection", body: "The URL in the SMS message is malicious. Do not utilise the hyperlink.", channel: "apollo_alerts", actionUrl: "/" });
  assert.equal(plain.body, "The web address in the text message is harmful. Do not use the link.");
});

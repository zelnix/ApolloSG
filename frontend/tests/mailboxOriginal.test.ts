import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { readMailboxOriginal } from "../src/domain/triage/mailboxOriginal.ts";
import { parseOriginalEmail, binaryToBytes } from "../src/domain/triage/emailOriginal.ts";
import { buildEmailProfile } from "../src/domain/triage/emailEvidence.ts";
import { analysisSourceFor, headerEvidenceFor } from "../src/domain/triage/emailIntake.ts";
import { analyseEmail } from "../src/domain/emailAnalysis.ts";

const raw = [
  'Received: from mail.google.com by mx.google.com with ESMTPS; Sat, 14 Nov 2026 10:00:00 +0000',
  'Authentication-Results: mx.google.com; spf=pass smtp.mailfrom=accounts.google.com; dkim=pass header.d=google.com; dmarc=pass header.from=accounts.google.com',
  'From: Google <no-reply@accounts.google.com>', 'Subject: Account activity',
  'Message-ID: <synthetic@google.com>', 'Date: Sat, 14 Nov 2026 10:00:00 +0000',
  'Content-Type: text/plain; charset=utf-8', '', 'You allowed account-tools.example access to your account. Review activity in your account settings.',
].join('\r\n');
const encoded = Buffer.from(raw, 'utf8').toString('base64url');
const parse = async (binary: string) => ({ binary, parsed: await parseOriginalEmail(binary, async (bytes) => createHash('sha256').update(bytes).digest('hex')) });

test('a connected mailbox uses the original parser and exposes recorded header authentication', async () => {
  const { original, limitation } = await readMailboxOriginal({ raw_base64url: encoded }, parse);
  assert.ok(original);
  assert.equal(limitation, null);
  assert.equal(Buffer.from(binaryToBytes(original.binary)).toString('utf8'), raw);
  assert.equal(original.parsed.sha256, createHash('sha256').update(raw).digest('hex'));
  const source = analysisSourceFor(original.parsed);
  const analysis = analyseEmail(source.raw, source.fields, headerEvidenceFor(original.parsed));
  const profile = buildEmailProfile({ via: 'connected_mailbox', original: original.parsed, analysis, keptOnDevice: true });
  assert.equal(profile.level, 'L4');
  assert.equal(profile.auth?.spf, 'pass');
  assert.equal(profile.auth?.dkim, 'pass');
  assert.equal(profile.auth?.dmarc, 'pass');
  for (const id of ['spf', 'dkim', 'dmarc']) assert.equal(profile.capabilities.find((c) => c.id === id)?.status, 'recorded');
  assert.equal(profile.original?.sha256, original.parsed.sha256);
});

test('an unavailable original stays a limited mailbox copy without manufactured headers', async () => {
  let called = false;
  const loaded = await readMailboxOriginal({ original_unavailable_reason: 'original_unavailable' }, async () => { called = true; return {}; });
  assert.equal(loaded.original, null);
  assert.equal(loaded.limitation, 'original_unavailable');
  assert.equal(called, false);
  const profile = buildEmailProfile({ via: 'connected_mailbox', analysis: analyseEmail('Example email') });
  assert.equal(profile.level, 'L2');
  assert.equal(profile.auth, null);
});

test('invalid source transport and parser failure do not create an original', async () => {
  for (const value of ['a', 'not base64!', '']) {
    const loaded = await readMailboxOriginal({ raw_base64url: value }, parse);
    assert.equal(loaded.original, null);
    assert.ok(loaded.limitation);
  }
  const loaded = await readMailboxOriginal({ raw_base64url: encoded }, async () => { throw new Error('not an original'); });
  assert.equal(loaded.original, null);
  assert.equal(loaded.limitation, 'original_unreadable');
});

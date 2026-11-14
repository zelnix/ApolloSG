const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { createInvestigationAudit } = require('../src/domain/investigationAudit.ts');
const { reasonForCase } = require('../src/domain/slm/caseContract.ts');
function harness(post) {
  const data = new Map();
  const audit = createInvestigationAudit({ getItem: async (k, f) => data.get(k) ?? f, setItem: async (k, v) => { data.set(k, v); return true; } }, async () => 'device-A');
  const code = ts.transpileModule(fs.readFileSync('src/domain/slm/slmTransport.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {}, activity = [];
  vm.runInNewContext(code, { exports, console, AbortController, require(name) {
    if (name.endsWith('/auditStore')) return { investigationAudit: audit };
    if (name.endsWith('/sharedRuntime.ts')) return { recordSuccessfulSLMInference: () => activity.push('completed'), recordFailedSLMInference: (_, status) => activity.push(status) };
    if (name.endsWith('/client.ts')) return { apiPost: post };
    if (name.endsWith('/caseContract.ts')) return { reasonForCase };
    throw Error(name);
  } });
  return { audit, activity, submit: exports.submitIssuedAdvisory };
}
const issued = () => ({ request: { caseId: 'case-A', requestId: 'request-A', caseRevision: 1, role: 'tc_hawkeye', operation: 'evidence_reasoning', question: 'What needs checking?', evidence: [{ evidenceId: 'E-1', text: 'A renewal offer' }] }, expiresAt: new Date(Date.now() + 60000).toISOString(), issuedAt: '2026-11-14T10:00:00Z' });
const output = { observations: [{ text: 'A renewal is offered', evidenceIds: ['E-1'] }], contradictions: [], alternativeExplanations: [], verificationSuggestions: [], draftExplanation: null };
test('lost receipt retries preserve actual output and do not invoke native inference again', async () => {
  let calls = 0, posts = 0; const payloads = [];
  const h = harness(async (_, __, payload) => { payloads.push(payload); if (++posts === 1) throw Error('offline'); return { accepted: true, advisoryOnly: true, caseId: 'case-A', requestId: 'request-A' }; });
  const adapter = { modelId: 'local-model', infer: async () => { calls++; return output; } }; const request = issued();
  await assert.rejects(h.submit('case-A', request, adapter), /offline/);
  const before = (await h.audit.get('case-A')).stages[0]; assert.equal(before.status, 'returned'); assert.ok(before.startedAt); assert.ok(before.returnedAt); assert.equal(before.acceptedAt, undefined);
  await h.submit('case-A', request, adapter);
  await h.submit('case-A', request, adapter);
  const after = (await h.audit.get('case-A')).stages[0]; assert.equal(calls, 1); assert.equal(posts, 2); assert.equal(after.status, 'accepted'); assert.equal(before.startedAt, after.startedAt); assert.deepEqual(after.output, output); assert.deepEqual(payloads[0], payloads[1]); assert.deepEqual(h.activity, ['completed']);
});
test('invalid native output records failure without exposing rejected text as an approved output', async () => {
  const h = harness(async () => ({ accepted: true }));
  const result = await h.submit('case-A', issued(), { modelId: 'local-model', infer: async () => 'not JSON' });
  assert.equal(result.status, 'invalid_output'); const stage = (await h.audit.get('case-A')).stages[0];
  assert.ok(stage.startedAt); assert.ok(stage.failedAt); assert.equal(stage.output, undefined); assert.equal(stage.acceptedAt, undefined); assert.deepEqual(h.activity, ['invalid_output']);
});
test('cross-case requests never invoke the model or create an engagement record', async () => {
  const h = harness(async () => { throw Error('unexpected POST'); }); let calls = 0;
  const result = await h.submit('case-B', issued(), { modelId: 'local-model', infer: async () => { calls++; return output; } });
  assert.equal(result.status, 'invalid_output'); assert.equal(calls, 0); assert.equal(await h.audit.get('case-B'), null);
});
test('a request rejected before inference has a failure record but no native engagement time', async () => {
  const h = harness(async () => ({ accepted: true })); let calls = 0;
  const request = issued(); request.request.operation = 'unsupported';
  const result = await h.submit('case-A', request, { modelId: 'local-model', infer: async () => { calls++; return output; } });
  assert.equal(result.status, 'invalid_output'); assert.equal(calls, 0);
  const stage = (await h.audit.get('case-A')).stages[0]; assert.equal(stage.startedAt, undefined); assert.ok(stage.failedAt);
});

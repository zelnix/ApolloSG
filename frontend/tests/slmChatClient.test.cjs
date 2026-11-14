const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { generateChat } = require('../src/higgins/groundedChat.ts');
const { retrieveLocalProduct } = require('../src/higgins/localKnowledgeCache.ts');
const { classifyIntent } = require('../src/higgins/intentRouter.ts');
function harness(infer, route = 'grounded_chat') {
  const posts = [];
  const code = ts.transpileModule(fs.readFileSync('src/higgins/chatClient.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, AbortController, require(name) {
    if (name.includes('/auth/deviceIdentity')) return { getDeviceIdentity: async () => ({ deviceId: 'device-A' }) };
    if (name.includes('/api/client')) return { ApiError: class extends Error {}, apiPost: async (path, _, body) => { posts.push(path); if (path !== '/higgins/chat/context') throw Error('Unexpected chat generation/provider path'); return { kind: route, scope: 'in_scope', conversationId: body.conversationId, turnId: body.turnId, userStatement: body.message, deviceObservation: body.deviceSnapshot ?? null, caseFindings: [], navigation: [], expiresAt: new Date(Date.now()+45000).toISOString(), passages: [{ id: 'P1', title: 'Guide', url: null, text: 'Apollo detects and protects.', publishedAt: null, checkedAt: null, freshness: 'versioned_product_guide' }] }; } };
    if (name.includes('/sharedRuntime')) return { getSharedSLM: () => ({ modelId: 'substituted-model', infer }) };
    if (name.endsWith('/groundedChat')) return { generateChat };
    if (name.endsWith('/localKnowledgeCache')) return { retrieveLocalProduct };
    if (name.endsWith('/intentRouter')) return { classifyIntent };
    throw Error(name);
  } });
  return { ask: exports.askHiggins, posts };
}
test('ordinary local knowledge and diagnostic turns actually invoke shared on-device inference', async () => {
  let calls = 0;
  const h = harness(async request => { calls++; assert.equal(request.operation, 'grounded_chat'); return { answer: 'Apollo detects and protects.', citations: ['P1'], quotations: [], clarification: null, uncertainty: [] }; });
  for (const message of ['What is Higgins?', 'Am I protected?']) await h.ask(message, 'conversation-A', 'turn-1234', [], { protectionOn: false });
  assert.equal(calls, 2); assert.deepEqual(h.posts, ['/higgins/chat/context', '/higgins/chat/context']);
});
test('ordinary model failure never requests a backend canned answer or Gemini', async () => {
  const h = harness(async () => { throw Error('native failure'); });
  await assert.rejects(h.ask('What is Higgins?', 'conversation-A', 'turn-1234', []), /native failure/);
  assert.deepEqual(h.posts, ['/higgins/chat/context']);
});
test('follow-up history excludes other devices, conversations and case scopes', async () => {
  const now = new Date().toISOString();
  const h = harness(async request => {
    assert.equal(request.chatContext.history.length, 1);
    assert.equal(request.chatContext.history[0].content, 'Own ordinary turn');
    return { answer: 'Apollo detects and protects.', citations: ['P1'], quotations: [], clarification: null, uncertainty: [] };
  });
  await h.ask('Tell me more', 'conversation-A', 'turn-1234', [], undefined, [
    { ownerId: 'device-A', conversationId: 'conversation-A', createdAt: now, role: 'user', content: 'Own ordinary turn' },
    { ownerId: 'device-B', conversationId: 'conversation-A', createdAt: now, role: 'user', content: 'Other device' },
    { ownerId: 'device-A', conversationId: 'other', createdAt: now, role: 'user', content: 'Other conversation' },
    { ownerId: 'device-A', conversationId: 'conversation-A', createdAt: now, caseScopeId: 'case-other', role: 'user', content: 'Other case' },
  ]);
});

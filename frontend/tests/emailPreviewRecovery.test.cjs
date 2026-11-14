/* global __filename */
// Exercise the real viewer's event handlers with native hosts substituted. This is not an Android renderer test.
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { fittedEmail } = require('../src/domain/inertEmail.ts');

function harness() {
  const state = [], diagnostics = [];
  let cursor = 0;
  const react = {
    useState(initial) {
      const slot = cursor++;
      if (!(slot in state)) state[slot] = initial;
      return [state[slot], (value) => { state[slot] = typeof value === 'function' ? value(state[slot]) : value; }];
    },
    useMemo: (fn) => fn(),
  };
  const element = (type, props) => ({ type, props });
  const code = ts.transpileModule(fs.readFileSync(new URL('../src/components/evidence/InertEmailView.tsx', `file://${__filename}`), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {
    exports,
    console: { warn: (...args) => diagnostics.push(args) },
    require(name) {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx: element, jsxs: element };
      if (name === 'react-native') return { View: 'View', Text: 'Text', ScrollView: 'ScrollView' };
      if (name === 'react-native-webview') return { WebView: 'WebView' };
      if (name === '@/src/domain/inertEmail') return { fittedEmail };
      throw new Error(`Unexpected dependency: ${name}`);
    },
  });
  return { diagnostics, render(props) { cursor = 0; return exports.InertEmailView(props); } };
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const find = (tree, type) => nodes(tree).find((n) => n.type === type);
const textNodes = (tree) => nodes(tree).filter((n) => n.type === 'Text').flatMap((n) => [n.props.children].flat(Infinity)).filter((v) => typeof v === 'string').join(' ');
const email = (document = '<html><head></head><body>Example email</body></html>') => ({ document, layoutWidth: 600, links: [], remoteImages: 0, trackingPixels: 0 });
const layout = (tree, width = 400) => tree.props.onLayout({ nativeEvent: { layout: { width } } });

for (const event of ['onError', 'onRenderProcessGone', 'onContentProcessDidTerminate']) {
  test(`${event} removes the failed renderer and retains exact captured text`, () => {
    const h = harness(), props = { email: email(), fallbackText: 'Captured <literal> text https://example.test/?x=1&y=2', testID: 'email' };
    const original = JSON.stringify(props);
    layout(h.render(props));
    const web = find(h.render(props), 'WebView');
    assert.ok(web);
    web.props[event]({ nativeEvent: { didCrash: true, description: 'Private provider data' } });
    const fallback = h.render(props);
    assert.equal(find(fallback, 'WebView'), undefined);
    assert.match(textNodes(fallback), /original email is unchanged/);
    assert.ok(textNodes(fallback).includes(props.fallbackText));
    assert.equal(JSON.stringify(props), original);
    assert.doesNotMatch(JSON.stringify(h.diagnostics), /Private provider data|Captured|example\.test/);
    layout(fallback, 600);
    assert.equal(find(h.render(props), 'WebView'), undefined, 'rotation must not restart a failed document');
  });
}

test('a failed email does not prevent a different document from displaying', () => {
  const h = harness(), first = { email: email() }, next = { email: email('<html><body>Different email</body></html>') };
  layout(h.render(first));
  const old = find(h.render(first), 'WebView');
  old.props.onRenderProcessGone({ nativeEvent: { didCrash: false } });
  assert.equal(find(h.render(first), 'WebView'), undefined);
  assert.ok(find(h.render(next), 'WebView'));
  old.props.onError({});
  assert.ok(find(h.render(next), 'WebView'), 'a late failure for the previous email must not suppress this email');
});

test('large rendered copies use captured text without altering or bridging the HTML', () => {
  const h = harness(), props = { email: email('x'.repeat(1024 * 1024 + 1)), fallbackText: 'Captured email text' };
  const original = props.email.document;
  layout(h.render(props));
  const tree = h.render(props);
  assert.equal(find(tree, 'WebView'), undefined);
  assert.ok(textNodes(tree).includes(props.fallbackText));
  assert.equal(props.email.document, original);
});

test('HTML recovery retains the inert-source protections', () => {
  const h = harness(), props = { email: email() };
  layout(h.render(props));
  const web = find(h.render(props), 'WebView');
  assert.equal(web.props.javaScriptEnabled, false);
  assert.equal(web.props.domStorageEnabled, false);
  assert.equal(web.props.allowFileAccess, false);
  assert.equal(web.props.sharedCookiesEnabled, false);
  assert.equal(web.props.androidLayerType, 'software');
  for (const url of ['https://example.test', 'tel:123', 'file:///secret', 'intent://app', 'data:text/html,unsafe']) {
    assert.equal(web.props.onShouldStartLoadWithRequest({ url }), false);
  }
  assert.equal(web.props.onShouldStartLoadWithRequest({ url: 'about:blank' }), true);
});

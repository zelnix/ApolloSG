/* global __dirname */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { test } = require('node:test');
const { auditNativeDependencies, assertNativeDependencies, formatReport } = require('../scripts/native-dependency-guard.cjs');
const { REQUIRED_SINGLETONS } = require('../scripts/native-dependencies/policy.cjs');

function writeJson(filename, data) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  fs.writeFileSync(filename, JSON.stringify(data));
}
function fixture(t, dependencies = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'apollo-native-guard-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeJson(path.join(root, 'package.json'), {
    name: 'fixture', version: '1.0.0', dependencies,
    expo: { autolinking: { android: { exclude: ['guarddog-expo-module'] }, ios: { exclude: ['guarddog-expo-module'] } } },
  });
  return root;
}
function install(root, name, version, parent = root, marker) {
  const directory = path.join(parent, 'node_modules', name);
  writeJson(path.join(directory, 'package.json'), { name, version });
  if (marker) writeJson(path.join(directory, marker), { platforms: ['android', 'apple'] });
  return directory;
}
const cliPath = path.resolve(__dirname, '../scripts/native-dependency-guard.cjs');
const cli = (root, ...args) => spawnSync(process.execPath, [cliPath, '--root', root, ...args], { encoding: 'utf8' });

test('all required packages and Expo runtime core are explicitly guarded', () => {
  for (const name of ['react-native-svg', 'react-native-reanimated', 'react-native-screens', 'react-native-gesture-handler', 'react-native-safe-area-context', 'react-native-webview', 'react-native-worklets', 'expo', 'expo-modules-core']) {
    assert.ok(REQUIRED_SINGLETONS.includes(name), name);
  }
});

test('one installation of each named singleton passes', t => {
  const root = fixture(t);
  for (const name of REQUIRED_SINGLETONS) install(root, name, '1.0.0');
  assert.equal(assertNativeDependencies(root).packages.length, REQUIRED_SINGLETONS.length);
});

test('reproduces Support incident: nested 13.14.1 beside 15.15.4; reports every path/version', t => {
  const root = fixture(t);
  const direct = install(root, 'react-native-svg', '15.15.4');
  const icons = install(root, '@nandorojo/heroicons', '0.3.0');
  const nested = install(root, 'react-native-svg', '13.14.1', icons);
  const report = auditNativeDependencies(root);
  assert.equal(report.status, 'fail');
  assert.deepEqual(report.duplicates[0].versions, ['13.14.1', '15.15.4']);
  const text = formatReport(report);
  for (const value of [direct, nested, '13.14.1', '15.15.4', 'react-native-svg']) assert.ok(text.includes(value));
  assert.throws(() => assertNativeDependencies(root), /DUPLICATE react-native-svg/);
  assert.equal(cli(root).status, 1);
});

for (const name of REQUIRED_SINGLETONS.filter(name => name !== 'react-native-svg')) {
  test(`nested duplication fails for ${name}`, t => {
    const root = fixture(t);
    install(root, name, '1.0.0');
    const wrapper = install(root, 'wrapper', '1.0.0');
    install(root, name, '2.0.0', wrapper);
    assert.equal(auditNativeDependencies(root).duplicates[0].name, name);
  });
}

test('two physical copies of the SAME version also fail (same native view collision risk)', t => {
  const root = fixture(t);
  install(root, 'react-native-svg', '15.15.4');
  install(root, 'react-native-svg', '15.15.4', install(root, 'wrapper', '1.0.0'));
  const report = auditNativeDependencies(root);
  assert.equal(report.status, 'fail');
  assert.equal(report.duplicates[0].versions.length, 1);
  assert.equal(report.duplicates[0].installations.length, 2);
});

test('symlink aliases to one physical copy pass; cycles terminate', t => {
  const root = fixture(t);
  const svg = install(root, 'react-native-svg', '15.15.4');
  const wrapper = install(root, 'wrapper', '1.0.0');
  fs.mkdirSync(path.join(wrapper, 'node_modules'));
  fs.symlinkSync(svg, path.join(wrapper, 'node_modules/react-native-svg'), 'dir');
  fs.symlinkSync(wrapper, path.join(wrapper, 'node_modules/loop'), 'dir');
  const report = assertNativeDependencies(root);
  assert.equal(report.packages[0].installations.length, 1);
  assert.equal(report.packages[0].installations[0].paths.length, 2);
});

test('discovers Expo native modules automatically, including an older copy without metadata', t => {
  const root = fixture(t);
  install(root, 'expo-future-module', '57.0.0', root, 'expo-module.config.json');
  install(root, 'expo-future-module', '56.0.0', install(root, 'wrapper', '1.0.0'));
  assert.equal(auditNativeDependencies(root).duplicates[0].name, 'expo-future-module');
});

test('discovers scoped Expo and third-party podspec/Android modules', t => {
  const root = fixture(t);
  install(root, '@expo/future', '1.0.0', root, 'expo-module.config.json');
  install(root, '@vendor/ios', '1.0.0', root, 'Vendor.podspec');
  install(root, '@vendor/android', '1.0.0', root, 'android/build.gradle.kts');
  assert.equal(assertNativeDependencies(root).packages.length, 3);
});

test('duplicates in pure JS packages do not block native builds', t => {
  const root = fixture(t);
  install(root, 'pure-js', '1.0.0');
  install(root, 'pure-js', '2.0.0', install(root, 'wrapper', '1.0.0'));
  assert.deepEqual(assertNativeDependencies(root).packages, []);
});

test('web-only Expo metadata is not classified as native', t => {
  const root = fixture(t);
  const directory = install(root, 'expo-web-only', '1.0.0');
  writeJson(path.join(directory, 'expo-module.config.json'), { platforms: ['web'] });
  assert.deepEqual(assertNativeDependencies(root).packages, []);
});

test('custom Expo search paths are inspected without editing source', t => {
  const root = fixture(t);
  install(root, 'react-native-svg', '15.15.4');
  writeJson(path.join(root, 'package.json'), { name: 'fixture', version: '1.0.0', expo: { autolinking: { searchPaths: ['./packages'] } } });
  const directory = path.join(root, 'packages/local-native');
  writeJson(path.join(directory, 'package.json'), { name: 'local-native', version: '1.0.0' });
  writeJson(path.join(directory, 'expo-module.config.json'), { platforms: ['android'] });
  const before = fs.readFileSync(path.join(directory, 'package.json'), 'utf8');
  assert.ok(assertNativeDependencies(root).packages.some(pkg => pkg.name === 'local-native'));
  assert.equal(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'), before);
});

test('parent node_modules used by workspace hoisting is included', t => {
  const workspace = fixture(t);
  install(workspace, 'react-native-svg', '15.15.4');
  const root = path.join(workspace, 'app');
  writeJson(path.join(root, 'package.json'), { name: 'app', version: '1.0.0', dependencies: { 'react-native-svg': '15.15.4' } });
  assert.equal(assertNativeDependencies(root).packages[0].versions[0], '15.15.4');
});

test('missing or empty installation never reports success', t => {
  const root = fixture(t);
  assert.equal(cli(root).status, 2);
  fs.mkdirSync(path.join(root, 'node_modules'));
  assert.equal(auditNativeDependencies(root).status, 'error');
});

test('declared but missing singleton fails an incomplete installation', t => {
  const root = fixture(t, { 'react-native-svg': '15.15.4' });
  install(root, 'unrelated', '1.0.0');
  assert.match(auditNativeDependencies(root).errors.join('\n'), /react-native-svg.*missing/);
});

test('malformed metadata and broken package symlinks fail closed', t => {
  const root = fixture(t);
  const directory = install(root, 'react-native-svg', '15.15.4');
  fs.writeFileSync(path.join(directory, 'package.json'), '{');
  fs.symlinkSync(path.join(root, 'absent'), path.join(root, 'node_modules/broken'), 'dir');
  const errors = auditNativeDependencies(root).errors.join('\n');
  assert.ok(errors.includes(directory), 'invalid package metadata must be reported');
  assert.ok(errors.includes('node_modules/broken'), 'broken symlink must be reported');
  assert.equal(cli(root).status, 2);
});

test('unsupported pnpm layout explicitly fails instead of skipping the store', t => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, 'node_modules/.pnpm'), { recursive: true });
  assert.match(auditNativeDependencies(root).errors.join('\n'), /pnpm virtual stores/);
});

test('CLI JSON is parseable on pass/fail and never changes dependency metadata', t => {
  const root = fixture(t);
  const svg = install(root, 'react-native-svg', '15.15.4');
  const filename = path.join(svg, 'package.json');
  const before = fs.readFileSync(filename, 'utf8');
  assert.equal(JSON.parse(cli(root, '--json').stdout).status, 'pass');
  install(root, 'react-native-svg', '13.14.1', install(root, 'wrapper', '1.0.0'));
  const result = cli(root, '--json');
  assert.equal(result.status, 1);
  assert.equal(JSON.parse(result.stdout).duplicates.length, 1);
  assert.equal(fs.readFileSync(filename, 'utf8'), before);
  assert.equal(cli(root, '--unknown-option').status, 2);
});

test('Android AND iOS prebuild callbacks reject duplicates after installation', async t => {
  const root = fixture(t);
  install(root, 'react-native-svg', '15.15.4');
  const plugin = require('../plugins/withNativeDependencyGuard.js');
  const config = plugin({ name: 'fixture', slug: 'fixture' });
  for (const platform of ['android', 'ios']) {
    const input = () => ({ ...config, modRequest: { projectRoot: root, platform }, modResults: {}, modRawConfig: config });
    await config.mods[platform].dangerous(input());
  }
  install(root, 'react-native-svg', '13.14.1', install(root, 'wrapper', '1.0.0'));
  for (const platform of ['android', 'ios']) {
    await assert.rejects(config.mods[platform].dangerous({ ...config, modRequest: { projectRoot: root, platform }, modResults: {}, modRawConfig: config }), /DUPLICATE react-native-svg/);
  }
});

test('combined preflight is strict except for the actual EAS pre-install lifecycle', t => {
  const root = fixture(t);
  fs.cpSync(path.resolve(__dirname, '../scripts'), path.join(root, 'scripts'), { recursive: true });
  // Copy app.config.js for identity checks but do NOT overwrite the fixture's clean package.json —
  // the real one declares every production dependency, causing the guard to report dozens of
  // "declared but missing" errors in a fixture that intentionally has a minimal node_modules.
  const appConfigSrc = path.resolve(__dirname, '../app.config.js');
  if (fs.existsSync(appConfigSrc)) fs.copyFileSync(appConfigSrc, path.join(root, 'app.config.js'));
  // app.config.js requires helpers from plugins/ (e.g. withRestrictedPhonePermissions).
  fs.cpSync(path.resolve(__dirname, '../plugins'), path.join(root, 'plugins'), { recursive: true });
  fs.mkdirSync(path.join(root, 'src/security'), { recursive: true });
  fs.copyFileSync(path.resolve(__dirname, '../src/security/securityConfig.ts'), path.join(root, 'src/security/securityConfig.ts'));
  // Use production env so the securityConfig check passes (guarddog_production is production-only).
  // All five PRODUCTION_KEYS must be present; without them the preflight exits with a config error
  // before reaching the native-dependency guard, making status assertions wrong.
  const run = (lifecycle, overrides = {}) => spawnSync(process.execPath, [path.join(root, 'scripts/security-preflight.mjs')], {
    encoding: 'utf8', env: {
      ...process.env,
      EXPO_PUBLIC_APP_ENV: 'production',
      EXPO_PUBLIC_BACKEND_URL: 'https://backend.example',
      EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE: 'guarddog_production',
      EXPO_PUBLIC_GUARDDOG_RULE_BUNDLE_URL: 'https://test.example/rules',
      EXPO_PUBLIC_GUARDDOG_CONTROLLED_HOST: 'test.example',
      EXPO_PUBLIC_GUARDDOG_CONTROLLED_IPV4: '192.0.2.1',
      EXPO_PUBLIC_GUARDDOG_CONTROLLED_URL: 'https://test.example/',
      EXPO_PUBLIC_GUARDDOG_RULESET_ID: 'test-rules',
      npm_lifecycle_event: lifecycle,
      // The copied plugins require @expo/config-plugins; resolve it from the real install while the
      // fixture root itself keeps its deliberately minimal node_modules for the native guard.
      NODE_PATH: path.resolve(__dirname, '../node_modules'),
      ...overrides,
    },
  });
  assert.equal(run('security:preflight').status, 2, 'no node_modules is not a pass');
  assert.match(run('eas-build-pre-install').stdout, /DEFERRED/);
  assert.equal(run('eas-build-pre-install').status, 0);
  const missingBackend = run('eas-build-pre-install', { EXPO_PUBLIC_BACKEND_URL: '' });
  assert.equal(missingBackend.status, 1, 'an APK with an unset API base cannot pass build admission');
  assert.match(missingBackend.stderr, /EXPO_PUBLIC_BACKEND_URL/);
  assert.equal(run('eas-build-pre-install', { EXPO_PUBLIC_BACKEND_URL: 'http://backend.example' }).status, 1);
  install(root, 'react-native-svg', '15.15.4');
  assert.equal(run('security:preflight').status, 0, 'clean CNG source needs no checked-in Android Gradle file');
  fs.mkdirSync(path.join(root, 'android/app'), { recursive: true });
  fs.writeFileSync(path.join(root, 'android/app/build.gradle'), "namespace 'wrong.package'\napplicationId 'wrong.package'\n");
  assert.equal(run('security:preflight').status, 1, 'a generated native package mismatch must fail closed');
  fs.writeFileSync(path.join(root, 'android/app/build.gradle'), "namespace 'app.apollo.hwg'\napplicationId 'app.apollo.hwg'\n");
  assert.equal(run('security:preflight').status, 0);
  install(root, 'react-native-svg', '13.14.1', install(root, 'wrapper', '1.0.0'));
  assert.equal(run('security:preflight').status, 1);
});

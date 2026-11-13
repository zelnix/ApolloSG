const assert = require('node:assert/strict');
const { test } = require('node:test');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { expo } = require('../app.config.js');
const { supported } = require('../config/android-abis.json');
const withBuildProperties = require('expo-build-properties').default;

test('Expo generates only the approved ARM64 Gradle architecture', async () => {
  const entry = expo.plugins.find(p => Array.isArray(p) && p[0] === 'expo-build-properties');
  const config = withBuildProperties({ name: 'abi-fixture', slug: 'abi-fixture' }, entry[1]);
  const generated = await config.mods.android.gradleProperties({
    ...config, modResults: [], modRequest: { projectRoot: '/tmp', platform: 'android' },
  });
  const value = generated.modResults.find(p => p.key === 'reactNativeArchitectures')?.value;
  assert.deepEqual(value?.split(','), supported);
  assert.deepEqual(new Set(supported), new Set(['arm64-v8a']));
});

test('native model plugin is always included, including with a stale off setting', () => {
  for (const value of [undefined, 'off', 'on']) {
    const env = { ...process.env };
    if (value === undefined) delete env.APOLLO_SLM_NATIVE;
    else env.APOLLO_SLM_NATIVE = value;
    const result = spawnSync(process.execPath, ['-e', 'console.log(JSON.stringify(require("./app.config.js").expo.plugins.filter(p => Array.isArray(p) && p[0] === "llama.rn")))'], {
      cwd: path.resolve(__dirname, '..'), env, encoding: 'utf8',
    });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), [['llama.rn', { enableEntitlements: false, forceCxx20: true, enableOpenCL: false }]]);
  }
});

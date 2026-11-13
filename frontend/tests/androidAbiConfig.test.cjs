const assert = require('node:assert/strict');
const { test } = require('node:test');
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

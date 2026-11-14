import assert from "node:assert/strict";
import test from "node:test";
import { b64ToBinary, binaryToBase64 } from "../src/domain/triage/emailOriginal.ts";

test("email byte conversions preserve all byte values, tails, and chunk boundaries", () => {
  for (const size of [0, 1, 2, 3, 4, 255, 256, 8191, 8192, 8193, 24575, 24576, 24577, 32768, 65537]) {
    const bytes = Buffer.from(Array.from({ length: size }, (_, i) => i % 256));
    const binary = bytes.toString("latin1");
    const encoded = binaryToBase64(binary);
    assert.equal(encoded, bytes.toString("base64"), `encoded ${size} bytes`);
    assert.equal(b64ToBinary(encoded), binary, `decoded ${size} bytes`);
    assert.equal(b64ToBinary(encoded.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "")), binary, `URL-safe ${size} bytes`);
  }
});

test("a large embedded email image survives byte conversion exactly", () => {
  const bytes = Buffer.alloc(2 * 1024 * 1024, 0xab);
  const binary = bytes.toString("latin1");
  const encoded = binaryToBase64(binary);
  assert.equal(encoded, bytes.toString("base64"));
  assert.equal(b64ToBinary(encoded.replace(/.{76}/g, "$&\r\n")), binary);
});

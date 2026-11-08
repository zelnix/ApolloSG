import assert from "node:assert/strict";
import test from "node:test";
import { StreamingSha256 } from "../src/domain/slm/streamingSha256.ts";
import { verifyPrivateGGUF, CANDIDATE_FILE, MIN_DEVICE_RAM_BYTES } from "../src/domain/slm/modelAdmission.ts";

const hex = (s: string) => Uint8Array.from(Buffer.from(s,"utf8"));

test("SHA256 standard empty and abc vectors", () => {
  assert.equal(new StreamingSha256().digestHex(), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(new StreamingSha256().update(hex("abc")).digestHex(), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("SHA256 chunking and 1M-byte vector", () => {
  const h = new StreamingSha256();
  const data = new Uint8Array(1000).fill(97);
  for (let i=0;i<1000;i++) h.update(data);
  assert.equal(h.digestHex(), "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
});

test("finalised hash cannot accept more data", () => {
  const h = new StreamingSha256();
  h.digestHex();
  assert.throws(() => h.update(hex("x")));
  assert.throws(() => h.digestHex());
});

const sample = {
  uri: "file:///private/Documents/"+CANDIDATE_FILE,
  exists: true,
  size: 490_000_000,
  open: () => { throw new Error("should not be reached"); },
};

test("model does not load when private file is absent", async () => {
  assert.deepEqual(await verifyPrivateGGUF({...sample, exists:false}, MIN_DEVICE_RAM_BYTES), {
    available:false, reason:"model_not_installed",
  });
});

test("model does not load when memory is low, unknown or size invalid", async () => {
  for (const memory of [0, null, MIN_DEVICE_RAM_BYTES-1]) {
    assert.deepEqual(await verifyPrivateGGUF(sample, memory), {
      available:false, reason:"device_not_admitted",
    });
  }
  assert.deepEqual(await verifyPrivateGGUF({...sample, size:5}, MIN_DEVICE_RAM_BYTES), {
    available:false, reason:"invalid_model",
  });
});

test("model rejects outside-private path and read failures", async () => {
  assert.deepEqual(await verifyPrivateGGUF({...sample, uri:"https://remote/test.gguf"}, MIN_DEVICE_RAM_BYTES), {
    available:false, reason:"invalid_model",
  });
  assert.deepEqual(await verifyPrivateGGUF(sample, MIN_DEVICE_RAM_BYTES), {
    available:false, reason:"model_unreadable",
  });
});

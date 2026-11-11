import assert from "node:assert/strict";
import test from "node:test";
import { verifyPrivateGGUF, CANDIDATE_FILE, MIN_DEVICE_RAM_BYTES } from "../src/domain/slm/modelAdmission.ts";

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

test("valid GGUF header admits without reading the entire model", async () => {
  let reads = 0;
  const file = {
    ...sample,
    open: () => ({
      readBytes: (length: number) => {
        reads++;
        assert.equal(length, 4);
        return Uint8Array.from([0x47, 0x47, 0x55, 0x46]);
      },
      close: () => undefined,
    }),
  };
  const result = await verifyPrivateGGUF(file, MIN_DEVICE_RAM_BYTES);
  assert.equal(result.available, true);
  assert.equal(reads, 1);
});

test("invalid GGUF header is rejected", async () => {
  const result = await verifyPrivateGGUF({
    ...sample,
    open: () => ({ readBytes: () => Uint8Array.from([0, 0, 0, 0]), close: () => undefined }),
  }, MIN_DEVICE_RAM_BYTES);
  assert.deepEqual(result, { available: false, reason: "invalid_model" });
});

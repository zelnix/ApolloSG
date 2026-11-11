import assert from "node:assert/strict";
import test from "node:test";
import { evaluateTriage } from "../src/domain/triage/engine.ts";

const cases: Array<[string, Record<string, unknown>, Record<string, unknown>, string]> = [
  ["MSG-06", { remote_access: true }, {}, "not_met"],
  ["MSG-06", { remote_access: true, login_request: true }, {}, "met"],
  ["MSG-07", { install_request: true }, {}, "not_met"],
  ["MSG-07", { install_request: true, code_request: true }, {}, "met"],
  ["MSG-16", { job_offer: true, payment_request: true }, {}, "not_met"],
  ["MSG-16", { job_offer: true, identity_request: true }, {}, "met"],
  ["MSG-19", { platform_switch: true, job_offer: true }, {}, "not_met"],
  ["MSG-19", { platform_switch: true, code_request: true }, {}, "met"],
  ["PAY-01", { instant_payment: true, claimed_brand: "Example" }, {}, "not_met"],
  ["PAY-01", { instant_payment: true, claimed_brand: "Example" }, { brand_mismatch: true }, "met"],
  ["PAY-02", { instant_payment: true, urgency: true, unknown_sender: true }, {}, "not_met"],
  ["PAY-02", { instant_payment: true, urgency: true, unknown_sender: true }, { deceptive_destination: true }, "met"],
  ["MSG-18", { identity_request: true, unknown_sender: true }, {}, "not_met"],
  ["MSG-18", { identity_request: true }, { deceptive_destination: true }, "met"],
  ["MSG-22", { payment_request: true, urgency: true, unknown_sender: true }, {}, "not_met"],
  ["MSG-22", { payment_request: true, urgency: true, unknown_sender: true }, { brand_mismatch: true }, "met"],
];

for (const [rule, signals, extra, expected] of cases) {
  test(`Wright device parity ${rule} ${JSON.stringify({ signals, extra })}`, () => {
    const result = evaluateTriage({ source_type: "message", signals, ...extra } as Parameters<typeof evaluateTriage>[0]);
    const record = result.rules.find((r) => r.ruleId === rule);
    assert.ok(record, `missing rule ${rule}`);
    assert.equal(record.result, expected);
  });
}

test("Wright device email auth requires corroborated deception", () => {
  const evidence = { source_type: "email", auth_results: { spf: "fail" }, consequential_action: true };
  const benign = evaluateTriage(evidence as Parameters<typeof evaluateTriage>[0]);
  assert.equal(benign.rules.find((r) => r.ruleId === "EMAIL-11")?.result, "not_met");
  const suspicious = evaluateTriage({ ...evidence, sender_domain_mismatch: true } as Parameters<typeof evaluateTriage>[0]);
  assert.equal(suspicious.rules.find((r) => r.ruleId === "EMAIL-11")?.result, "met");
});

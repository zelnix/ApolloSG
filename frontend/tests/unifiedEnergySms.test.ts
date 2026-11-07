// Acceptance: the UNIﬁed Energy SMS (sender 0419 841 238) must reach TC Hawkeye. Higgins Triage spots the look-alike
// "ﬁ" in the business name (on its own enough), the government-rebate claim, the deadline pressure and "Reply YES".
import assert from "node:assert/strict";
import { test } from "node:test";

import { analyseMessage, disguisedWords, organisationNamed } from "../src/domain/messageAnalysis.ts";
import { messageTriageEvidence } from "../src/domain/triage/evidence.ts";
import { evaluateTriage } from "../src/domain/triage/engine.ts";

const SMS = "Good morning! It's UNI\uFB01ed Energy here. Lock in higher STC savings before rebates drop next week and secure installation before year-end.\n\nReply YES and your preferred call time:\n1) 10am-12:30pm\n2) 12:30pm-3:30pm\n3) 3:30pm-5:30pm.";
const triage = (text: string) => evaluateTriage(messageTriageEvidence({ analysis: analyseMessage("0419 841 238", text) }));

test("the message's own words are extracted, the name kept exactly as written", () => {
  const s = analyseMessage("0419 841 238", SMS).signals;
  assert.equal(s.claimedBrand, "UNI\uFB01ed Energy");
  assert.equal(s.brandKind, "energy");
  assert.deepEqual(s.lookalikeChars, ["\uFB01"]);
  assert.equal(s.lookalikeName, true);
  assert.equal(s.replyRequest, "Reply YES");
  assert.equal(s.timePressure, "before rebates drop next week");
  assert.equal(s.governmentRebate, "STC savings");
  assert.equal(s.urgency, true, "a deadline on an offer is urgency");
});

test("Higgins Triage escalates it: the disguised name and the rebate pressure", () => {
  const record = triage(SMS);
  assert.equal(record.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  assert.deepEqual(record.rulesMet, ["MSG-23", "MSG-24"]);
  const a = analyseMessage("0419 841 238", SMS);
  assert.equal(a.scenario, "M17");
  assert.equal(a.state, "growling");
  assert.ok(a.why.some((w) => w.includes("“\uFB01”")) && a.why.some((w) => w.includes("“Reply YES”")));
});

test("a look-alike letter in the business name alone is enough", () => {
  assert.deepEqual(triage("Hi, it's Bright So\uFF4Car here. Your quote is ready.").rulesMet, ["MSG-23"]);
});

test("written with a plain fi, the rebate deadline and Reply YES still escalate", () => {
  assert.deepEqual(triage(SMS.replace("\uFB01", "fi")).rulesMet, ["MSG-24"]);
  assert.equal(analyseMessage("", SMS.replace("\uFB01", "fi")).scenario, "M18");
});

test("never a threat on their own: a person's name, a reply STOP opt-out, an emoji, a rebate with no deadline or reply", () => {
  assert.equal(organisationNamed("Hi Mum it's Sarah here, call me"), null);
  assert.deepEqual(disguisedWords("Love you all 👨\u200D👩\u200D👧"), []);
  for (const text of ["Hi Mum it's Sarah here, call me when you can", "Bright Solar: your install is booked for Tuesday. Reply STOP to opt out.",
    "Government battery rebates are available. Visit your state government's website for details."]) {
    assert.equal(triage(text).outcome, "NO_THREAT_IDENTIFIED", text);
  }
});

// "How Apollo checks" — the rules Apollo, Higgins Triage, TC Hawkeye, Magnum DI and Higgins operate under,
// in plain English for the person using Apollo. Mirrors memory/OPERATING_RULES.md: keep the two in step.
// Pure: no React, no native imports.

import { HIGGINS_DESCRIPTION } from "./higginsIdentity.ts";

export type CheckRoleId = "apollo" | "triage" | "tc_flyby" | "magnum" | "higgins";

export interface CheckRole {
  id: CheckRoleId;
  name: string;
  /** What this part of Apollo is for, in a few words. */
  job: string;
  rules: string[];
}

export const HOW_INTRO =
  "Every check goes through the same steps, and each part of ApolloSG has one job. Most of the work is quick and low-cost; " +
  "the deepest step is used only when it could change the answer.";

/** In the order a check moves through them. */
export const CHECK_ROLES: CheckRole[] = [
  {
    id: "apollo",
    name: "Apollo",
    job: "Detects and protects",
    rules: [
      "Watches websites, calls, messages, apps, your device and your connection, and acts on the device.",
      "Apollo detects potential concerns and passes investigation-ready material through the established investigation flow.",
      "Biting means a block Apollo really made on this device. A link, email or message check can raise Apollo to Barking, never Biting.",
      "Something Apollo couldn't check is never treated as safe, or as unsafe. Apollo tells you what it couldn't see.",
      "Passwords and codes are removed on your device before anything is sent, and only what the check needs leaves your device.",
    ],
  },
  {
    id: "triage",
    name: "Higgins Triage",
    job: "Gets everything ready",
    rules: [
      "Reads everything you sent before any investigating starts: the text, the links, the words in a screenshot and the text inside a document.",
      "Picks out what needs checking — links, phone numbers, email addresses, company names, payment details, and anything asking you to act.",
      "Anything it couldn't read is noted, never guessed.",
      "Uses the shared on-device AI, Higgins, to assess whether enough information is available for investigation. It does not decide whether something is a scam.",
    ],
  },
  {
    id: "tc_flyby",
    name: "TC Hawkeye",
    job: "Investigates quickly",
    rules: [
      "Investigates using the shared on-device AI, Higgins, and applicable evidence-backed checks, including available official sources and threat intelligence.",
      "A search answer only counts when a real web page backs it up.",
      "Records findings and limitations; unresolved cases can proceed to Magnum DI for deeper investigation.",
      "A known scam only matches when the whole pattern is there — one word on its own never counts.",
      "A web address that uses a company's name but isn't that company's website is a warning sign.",
      "Magnum DI is engaged when TC Hawkeye cannot reach a conclusive investigation result.",
    ],
  },
  {
    id: "magnum",
    name: "Magnum DI",
    job: "Investigates deeply, only when needed",
    rules: [
      "Called only when TC Hawkeye can't settle something that could change the answer — a picture Apollo couldn't read, a request to send money or details somewhere nobody has verified, or findings that disagree.",
      "Investigates unresolved questions more deeply, using TC Hawkeye's findings and any additional evidence.",
      "Uses the shared on-device AI, Higgins, for deeper investigation. Gemini may be used as an optional extension when deeper capability is warranted.",
      "If a check is unavailable or incomplete, ApolloSG records the limitation rather than presenting it as successful.",
      "Evidence Lock retains findings, sources and limitations. Higgins uses Luddish to explain the recorded findings.",
      "It's the only part of ApolloSG that may ask you a question or ask your device for a fresh reading.",
    ],
  },
  {
    id: "higgins",
    name: "Higgins",
    job: "On-device comprehension, reasoning and explanations",
    rules: [
      HIGGINS_DESCRIPTION,
      "Provides on-device comprehension and reasoning for the investigation stages, within their established evidence and decision rules.",
      "Explains what was found and takes you to the right screen. His wording never changes what the recorded result means.",
      "Answers from what ApolloSG already knows first. Questions about a finished check are answered from its record — the check isn't reopened.",
      "Your device's live reading is the truth. He never guesses past it and never invents a worry.",
      "Talks only about scams, security and ApolloSG.",
    ],
  },
];

/** Outcomes come from the established investigation workflow; Luddish explains the recorded Finding. */
export const OUTCOME_GUIDE: { outcome: string; meaning: string }[] = [
  { outcome: "scam", meaning: "The investigation established this is a scam — through a known scam listing, a fake identity, established deception, or a complete corroborated scam pattern." },
  { outcome: "likely_scam", meaning: "Strong signs of a scam — impersonation indicators, a strong pattern match, or multiple independent scam indicators — but an important part of the evidence remains unverified." },
  { outcome: "unlikely_scam", meaning: "The available evidence points away from a scam, but does not establish that the content is safe." },
  { outcome: "not_scam", meaning: "The investigation verified the identity, destinations, purpose and resolved all scam warnings. That's not a guarantee it's safe — only that these checks found nothing." },
];

export const PROMISES: string[] = [
  "ApolloSG never tells you something is safe — only what its checks found.",
  "Anything Apollo couldn't check is listed, not hidden.",
  "Every final Finding is grounded in investigation evidence, with sources and limitations retained. Higgins uses Luddish to explain it.",
];


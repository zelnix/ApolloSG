// "How Apollo checks" — the rules Apollo, Higgins Triage, TC FlyBy, Magnum DI and Higgins operate under,
// in plain English for the person using Apollo. Mirrors memory/OPERATING_RULES.md: keep the two in step.
// Pure: no React, no native imports.

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
      "Its first look at anything uses fixed rules, with no AI. Only something that looks like a possible threat — or that Apollo can't settle on its own — goes on to be investigated.",
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
      "Uses no AI and doesn't go online. It prepares the check; it doesn't decide the result.",
    ],
  },
  {
    id: "tc_flyby",
    name: "TC FlyBy",
    job: "Investigates quickly",
    rules: [
      "Uses no AI. Checks the cheapest reliable way first: official sources, then ApolloSG's knowledge base, then one small, targeted web search.",
      "A search answer only counts when a real web page backs it up.",
      "Stops as soon as checking further couldn't change the result or what you should do. “Unable to determine” is an honest answer.",
      "A known scam only matches when the whole pattern is there — one word on its own never counts.",
      "A web address that uses a company's name but isn't that company's website is a warning sign.",
      "When TC FlyBy settles a check, Magnum DI isn't called at all.",
    ],
  },
  {
    id: "magnum",
    name: "Magnum DI",
    job: "Investigates deeply, only when needed",
    rules: [
      "Called only when TC FlyBy can't settle something that could change the answer — a picture Apollo couldn't read, a request to send money or details somewhere nobody has verified, or findings that disagree.",
      "Looks only at what's still open, with TC FlyBy's notes — not the whole case again.",
      "Makes at most one AI call per case, and it's never retried. It searches the web only if a fact is still missing.",
      "If that call fails, ApolloSG tells you why and shows what TC FlyBy already found.",
      "Every finding must point to real evidence. If its answer doesn't hold up, ApolloSG says so rather than making one up.",
      "It's the only part of ApolloSG that may ask you a question or ask your device for a fresh reading.",
    ],
  },
  {
    id: "higgins",
    name: "Higgins",
    job: "Explains and guides",
    rules: [
      "Explains what was found and takes you to the right screen. He never investigates, and never changes what a result means.",
      "Answers from what ApolloSG already knows first. Questions about a finished check are answered from its record — the check isn't reopened.",
      "Your device's live reading is the truth. He never guesses past it and never invents a worry.",
      "Talks only about scams, security and ApolloSG.",
    ],
  },
];

/** Every check ends with one of these four Findings, whichever investigator answered. */
export const OUTCOME_GUIDE: { outcome: string; meaning: string }[] = [
  { outcome: "scam", meaning: "The investigation established this is a scam — through a known scam listing, a fake identity, established deception, or a complete corroborated scam pattern." },
  { outcome: "likely_scam", meaning: "Strong signs of a scam — impersonation indicators, a strong pattern match, or multiple independent scam indicators — but an important part of the evidence remains unverified." },
  { outcome: "unable_to_determine", meaning: "Apollo couldn't establish enough to say either way — too little information, important checks unavailable, or conflicting results." },
  { outcome: "not_scam", meaning: "The investigation verified the identity, destinations, purpose and resolved all scam warnings. That's not a guarantee it's safe — only that these checks found nothing." },
];

export const PROMISES: string[] = [
  "ApolloSG never tells you something is safe — only what its checks found.",
  "Anything Apollo couldn't check is listed, not hidden.",
  "Every result says who settled it: TC FlyBy or Magnum DI.",
];


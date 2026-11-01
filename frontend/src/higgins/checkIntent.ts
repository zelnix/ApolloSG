// Deterministic, on-device detection of "I want something checked" in the Higgins chat.
//
// When a person says they want an email, message, call, link, app, file, photo or their device
// checked, Higgins opens the matching input form instead of answering in prose — the person still
// provides the artifact and submits it, and the submission runs Apollo's real check. No AI call is
// made to work this out, and nothing here decides or hints at a verdict.

import type { HigginsCheckCategory } from "@/src/components/HigginsCheckSheet";

export interface CheckIntent {
  category: HigginsCheckCategory;
  /** What Higgins says while the form opens. Never a verdict or reassurance. */
  acknowledgement: string;
}

/** Phrases that show the person wants something checked, not explained. */
const INTENT_PATTERNS = [
  /\bcheck\b/i,
  /\bchecked\b/i,
  /\bscan\b/i,
  /\binvestigate\b/i,
  /\bverify\b/i,
  /\blook at\b/i,
  /\bhave a look\b/i,
  /\bis (this|that|it)\b/i,
  /\bscam\b/i,
  /\bphishing\b/i,
  /\bsuspicious\b/i,
  /\blegit(imate)?\b/i,
  /\bsafe to (open|use|click|pay)\b/i,
];

/** Subject words, in the order their category is offered in the check sheet. */
const SUBJECTS: { category: HigginsCheckCategory; patterns: RegExp[] }[] = [
  {
    category: "screenshot",
    patterns: [/\bscreenshots?\b/i, /\bscreen ?shots?\b/i, /\bphotos?\b/i, /\bpictures?\b/i, /\bimages?\b/i, /\bqr ?(code)?\b/i],
  },
  {
    category: "email_accounts",
    patterns: [/\bemails?\b/i, /\be-?mails?\b/i, /\binbox\b/i, /\bmailbox\b/i],
  },
  {
    category: "messages_calls",
    patterns: [/\bmessages?\b/i, /\btexts?\b/i, /\bsms\b/i, /\bcalls?\b/i, /\bcallers?\b/i, /\bvoicemails?\b/i, /\bphone numbers?\b/i, /\bnumbers?\b/i, /\bwhatsapp\b/i],
  },
  {
    category: "websites_links",
    patterns: [/\blinks?\b/i, /\bwebsites?\b/i, /\burls?\b/i, /\bweb ?pages?\b/i, /\bdomains?\b/i, /\bsite\b/i],
  },
  {
    category: "apps_files",
    patterns: [/\bapps?\b/i, /\bapplications?\b/i, /\bfiles?\b/i, /\battachments?\b/i, /\bdownloads?\b/i, /\bapk\b/i, /\bpdf\b/i],
  },
  {
    category: "device_internet",
    patterns: [/\bdevices?\b/i, /\bwi-?fi\b/i, /\binternet\b/i, /\bnetworks?\b/i, /\brouter\b/i],
  },
];

const ACKNOWLEDGEMENTS: Record<HigginsCheckCategory, string> = {
  screenshot:
    "Of course. Pick the screenshot, or take a photo of what's in front of you, and Apollo will check it.",
  websites_links: "Of course. Paste the link below and Apollo will check it.",
  messages_calls:
    "Of course. Paste the message, or enter the number that called, and Apollo will check it.",
  email_accounts: "Of course. Paste the email below and Apollo will check it.",
  apps_files: "Of course. Tell me the app or file below and Apollo will check it.",
  device_internet: "Of course. Add anything you've noticed below and Apollo will check your device.",
};

/** "How do I check a link?" asks how ApolloSG works — Higgins answers it from the User Guide instead of opening a form. */
const HOW_TO = /^\W*(?:how (?:do|can|should|would) i|how to|where (?:do|can|should|would) i|where (?:is|are)|where's)\b/i;

/**
 * Returns the category to open, or null when the message is a question for Higgins to answer.
 * Requires both an intent phrase and a subject word; the earliest subject mentioned wins.
 */
export function detectCheckIntent(message: string): CheckIntent | null {
  const text = message.trim();
  if (!text || HOW_TO.test(text)) return null;
  if (!INTENT_PATTERNS.some((p) => p.test(text))) return null;

  let best: { category: HigginsCheckCategory; index: number } | null = null;
  for (const subject of SUBJECTS) {
    for (const pattern of subject.patterns) {
      const match = pattern.exec(text);
      if (match && (best === null || match.index < best.index)) {
        best = { category: subject.category, index: match.index };
      }
    }
  }
  if (!best) return null;
  return { category: best.category, acknowledgement: ACKNOWLEDGEMENTS[best.category] };
}

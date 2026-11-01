// The ApolloSG User Guide, bundled so it reads offline. This JSON is an exact copy of
// backend/services/higgins/user_guide.json — the same text Higgins answers "how do I…" from.
// Edit the backend file, then run `cd backend && python scripts/sync_user_guide.py`.
import data from "./userGuide.json";
import type { GuideSection, GuideTopic, UserGuide } from "./search";

export const USER_GUIDE = data as UserGuide;

export function guideSection(id: string | undefined): GuideSection | undefined {
  return USER_GUIDE.sections.find((section) => section.id === id);
}

/** "2026-06" → "June 2026". */
export function reviewedLabel(): string {
  const [year, month] = USER_GUIDE.reviewed.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-AU", { month: "long", year: "numeric" });
}

export type { GuideSection, GuideTopic };

// Apollo's destination map for Higgins.
//
// Higgins may offer a deep link to any screen listed here and nothing else. The
// backend holds the same list (`services/higgins/app_knowledge.py`) and validates
// what the model returns; this is the second gate, on the device, so a route that
// no longer exists in the app can never be turned into a tap that goes nowhere.
//
// Keep in step with the Expo Router tree in `frontend/app`.

export interface NavLink {
  route: string;
  label: string;
}

export const APOLLO_DESTINATIONS: Record<string, string> = {
  // Main tabs
  "/(tabs)/home": "Home",
  "/(tabs)/patrol": "Threats",
  "/(tabs)/scams": "Scam Alerts",
  "/(tabs)/ask": "Ask Higgins",
  "/(tabs)/settings": "Settings",
  "/(tabs)/guard": "Your protections",
  "/(tabs)/protection": "Protections",
  "/(tabs)/learn": "Learn",
  // Manual checks
  "/message": "Check a message",
  "/check": "Check a website link",
  "/file": "Check a file",
  "/call-guard": "Check a number",
  "/scan": "Scan a code",
  "/email": "Check an email",
  "/app-check": "Check an app",
  "/account": "Check an account alert",
  "/device": "Check my device",
  "/device-protection": "Device Protections",
  "/network": "Check my internet",
  "/vision": "Check a screenshot",
  "/text-guard": "Message screening",
  "/recheck": "Re-check my device",
  // Records and history
  "/patrol/history": "Threat history",
  "/saved-checks": "Saved checks",
  "/saved-reports": "Saved reports",
  "/higgins/history": "Conversation history",
  "/app-reports": "App reports",
  "/digest": "Weekly digest",
  "/account-monitor": "Account monitoring",
  // Learning and alerts
  "/higgins/learning": "Learn with Higgins",
  "/higgins/scams": "Scam Alerts",
  "/how-apollo-checks": "How Apollo checks",
  "/alerts": "Your alerts",
  // Protections
  "/gates": "All protections",
  // Records, samples and help
  "/patrol/search": "Search cases",
  "/sample-checks": "Sample checks",
  "/user-guide": "User Guide",
  "/privacy": "Privacy",
  // Settings and policies
  "/settings/personal-data": "My personal data",
  "/settings/email-accounts": "Email accounts",
  "/settings/feed-health": "Feed health",
  "/settings/rule-book": "Rule book",  // admin portal only — hidden from user navigation
  "/privacy-data": "What ApolloSG stores",
  "/privacy-disclosure": "Privacy statement",
  "/third-party-register": "Third-party services",
  "/compliance-matrix": "Compliance matrix",
  "/notification-check": "Notification check",
  "/family": "Family sharing",
  "/support": "Get help with ApolloSG",
};

/** Keep only destinations that genuinely exist, de-duplicated, at most two. */
export function resolveNavLinks(items: { route: string; label?: string }[] | undefined): NavLink[] {
  if (!items?.length) return [];
  const out: NavLink[] = [];
  for (const item of items) {
    const route = String(item.route ?? "").trim();
    const known = APOLLO_DESTINATIONS[route];
    if (!known || out.some((existing) => existing.route === route)) continue;
    out.push({ route, label: item.label?.trim() || known });
    if (out.length === 2) break;
  }
  return out;
}

/** Build links from plain route strings, labelled from the map. */
export function navLinks(...routes: string[]): NavLink[] {
  return resolveNavLinks(routes.map((route) => ({ route })));
}

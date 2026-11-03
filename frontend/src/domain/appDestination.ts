import type { CheckItRoute } from "./checkIt";

export type ApolloDestination = "link_gate" | "text_gate" | "file_gate" | "app_gate" | "device_gate" | "account_gate" | "network_gate" | "email_gate" | "call_gate" | "site_gate" | "patrol" | "saved_reports" | "higgins_case" | "ask_higgins";

export type ApolloRoute = CheckItRoute | "/gates" | "/(tabs)/guard" | "/(tabs)/protection" | "/(tabs)/patrol" | "/higgins/scams" | "/saved-reports" | "/(tabs)/ask" | "/vision";

export interface AppDestinationAction {
  kind: "app_destination";
  destination: ApolloDestination;
  label: string;
  purpose: string;
  route: ApolloRoute;
  context?: { caseId?: string; eventId?: string; operationId?: string };
}

const SAFE_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function safeDestinationParams(context?: AppDestinationAction["context"]): Record<string, string> {
  if (!context) return {};
  return Object.fromEntries(Object.entries(context).filter((entry): entry is [string, string] => typeof entry[1] === "string" && SAFE_ID.test(entry[1])));
}
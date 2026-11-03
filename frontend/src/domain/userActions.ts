export type UserActionId =
  | "restore_site" | "check_link" | "setup_text" | "check_text" | "setup_call" | "check_call"
  | "check_network" | "check_account" | "open_email" | "check_file" | "check_app" | "check_device"
  | "open_check_it" | "start_investigation" | "continue_case" | "open_report" | "ask_higgins_article"
  | "view_official_advice" | "dismiss_notice";

export interface UserAction { id: UserActionId; label: string }

export const USER_ACTION_ROUTES: Partial<Record<UserActionId, string>> = {
  check_link: "/check", setup_text: "/text-guard", check_text: "/message", setup_call: "/call-guard", check_call: "/call",
  check_network: "/network", check_account: "/account", open_email: "/email", check_file: "/file", check_app: "/app-check",
  check_device: "/device", open_check_it: "/(tabs)/ask",
};

export function userActionRoute(id: UserActionId): string | null { return USER_ACTION_ROUTES[id] ?? null; }
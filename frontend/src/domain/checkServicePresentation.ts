// Functional service names are shared with the backend through the canonical triage catalogue.
// Only display text changes; provider identifiers and raw diagnostics stay in their recorded form.
import catalogue from "./triage/catalogue.ts";

const services: readonly { name: string; aliases: readonly string[] }[] = catalogue.completeness.serviceFunctions;
const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const norm = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
const FALLBACK: Record<string, string> = {
  reputation: "Website threat checking", final_destination: "Link destination checking",
  sender_authentication: "Email sender authentication", number_reputation: "Phone number validation",
  domain_age: "Website registration checking", block_proof: "Protection action verification",
};

export function serviceFunction(source: string | null | undefined, check: string): string {
  const found = source && services.find((s) => [s.name, ...s.aliases].some((a) => norm(a) === norm(source)));
  return found ? found.name : FALLBACK[check] ?? "External verification";
}

export function serviceSubject(value: string): string {
  if (/^\+?[\d\s().-]+$/.test(value)) return value;
  try { return new URL(value.includes("://") ? value : `https://${value}`).hostname || value; }
  catch { return value; }
}

export function plainServiceText(text: string): string {
  let out = text;
  const aliases = services.flatMap((s) => s.aliases.map((a) => ({ alias: a, name: s.name }))).sort((a, b) => b.alias.length - a.alias.length);
  for (const { alias, name } of aliases) out = out.replace(new RegExp(`\\b${escape(alias)}\\b`, "gi"), name);
  return out.replace(/\bIP addresses\b/gi, "internet addresses").replace(/\bIP address\b/gi, "internet address");
}

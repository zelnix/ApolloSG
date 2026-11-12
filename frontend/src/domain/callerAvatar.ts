/** Display-only identity cue; never treats a phone-number association as proof of who called. */
import type { PhoneIdentityResult } from "@/src/api/phoneIdentity";
import type { CallerAvatarKind } from "@/src/components/CallerIdentityAvatar";

export function callerAvatarForIdentity(identity: Pick<PhoneIdentityResult, "associated_entity" | "association_confidence" | "known_impersonation" | "scam_intel">): CallerAvatarKind {
  if (identity.known_impersonation || (typeof identity.scam_intel === "string" && identity.scam_intel.trim().length > 0)) return "risk_warning";
  if (identity.associated_entity && (identity.association_confidence === "verified" || identity.association_confidence === "strong")) return "business_association";
  return "unknown";
}

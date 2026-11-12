// Expo config plugin: Google Play restricted SMS / Call Log permissions — OFF unless explicitly approved.
//
// READ_CALL_LOG and READ_SMS belong to Google Play's restricted "SMS and Call Log" permission group. Apollo
// does not currently qualify for an approved Play declaration (see
// docs/APOLLO_PLAY_RESTRICTED_PERMISSIONS_FUTURE_DECLARATIONS.md), so every build — preview, internal
// and Play — ships WITHOUT them by default:
//   - neither permission is declared by any Apollo source manifest, and
//   - this plugin writes `tools:node="remove"` for both, so no library can merge them back in.
//
// Live protection never depended on them: Call Guard screens calls through Android's CallScreeningService
// (the number Android hands Apollo for each incoming call) and Text Guard checks new texts through opt-in
// notification access. These permissions only ever powered the optional "pick from your call log / inbox"
// conveniences, whose code is retained and stays hidden while the permission is absent.
//
// Turning either back on is a deliberate, two-part configuration change, never a default:
//   APOLLO_ANDROID_RESTRICTED_PERMISSIONS=READ_CALL_LOG        (or READ_SMS, or READ_CALL_LOG,READ_SMS)
//   APOLLO_ANDROID_RESTRICTED_PERMISSIONS_APPROVAL=<Google Play declaration approval reference>
// Anything else fails the config load: an unknown value, or a value without the approval reference.
// eas.json pins the production profile to "off" so a stray shell variable cannot leak into a Play build.

const SWITCH = "APOLLO_ANDROID_RESTRICTED_PERMISSIONS";
const APPROVAL = "APOLLO_ANDROID_RESTRICTED_PERMISSIONS_APPROVAL";
const PERMISSIONS = {
  READ_CALL_LOG: "android.permission.READ_CALL_LOG",
  READ_SMS: "android.permission.READ_SMS",
};

/** Reads the build switch. Returns which restricted pickers this build may declare; throws on anything ambiguous. */
function resolveRestrictedPhonePermissions(env = process.env) {
  const raw = String(env[SWITCH] ?? "").trim();
  if (raw === "" || raw === "off") return { callLog: false, sms: false, approval: null };
  const names = raw.split(",").map((name) => name.trim()).filter(Boolean);
  const unknown = names.filter((name) => !Object.prototype.hasOwnProperty.call(PERMISSIONS, name));
  if (!names.length || unknown.length) {
    throw new Error(`[restricted-permissions] ${SWITCH}="${raw}" is not valid. Use "off" (default), READ_CALL_LOG, READ_SMS, or READ_CALL_LOG,READ_SMS.`);
  }
  const approval = String(env[APPROVAL] ?? "").trim();
  if (!approval) {
    throw new Error(`[restricted-permissions] ${SWITCH}="${raw}" also requires ${APPROVAL} (the Google Play permission-declaration approval reference). These permissions must not ship without an approved declaration.`);
  }
  return { callLog: names.includes("READ_CALL_LOG"), sms: names.includes("READ_SMS"), approval };
}

function withRestrictedPhonePermissions(config) {
  // EAS runs the security pre-install hook before dependencies exist. Resolve the
  // Expo plugin only when Expo actually applies this native configuration plugin.
  const { AndroidConfig } = require("@expo/config-plugins");
  const flags = resolveRestrictedPhonePermissions();
  const declared = [flags.callLog && PERMISSIONS.READ_CALL_LOG, flags.sms && PERMISSIONS.READ_SMS].filter(Boolean);
  const blocked = Object.values(PERMISSIONS).filter((permission) => !declared.includes(permission));
  if (declared.length) config = AndroidConfig.Permissions.withPermissions(config, declared);
  if (blocked.length) config = AndroidConfig.Permissions.withBlockedPermissions(config, blocked);
  return config;
}

module.exports = withRestrictedPhonePermissions;
module.exports.resolveRestrictedPhonePermissions = resolveRestrictedPhonePermissions;
module.exports.RESTRICTED_PERMISSIONS_SWITCH = SWITCH;
module.exports.RESTRICTED_PERMISSIONS_APPROVAL = APPROVAL;

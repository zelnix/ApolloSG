// Android and iOS. Contacts are read only after a deliberate opt-in; no contact data is sent to Apollo servers.
// A saved contact is an address-book match, NOT proof that the incoming caller is that person.
import React, { useCallback, useEffect, useState } from "react";
import { AppState, Image, Platform, Pressable, Text, View } from "react-native";
import { getNativeModule } from "@/src/security/nativeBridge";
import { fonts, makeStyles, spacing } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  wrapper: { gap: spacing.xs },
  row: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.sm },
  photo: { width: 40, height: 40, borderRadius: 20 },
  name: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  note: { fontFamily: fonts.text, fontSize: 11, color: c.muted },
  action: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.brand },
}));

type Match = { status: string; name?: string; photoUri?: string | null };
const read = async (number: string): Promise<Match> => {
  try {
    const native = getNativeModule();
    if (!native?.lookupCallerContact) return { status: "unavailable" };
    const raw = await native.lookupCallerContact(number);
    const parsed = JSON.parse(raw) as Match;
    return parsed && typeof parsed.status === "string" ? parsed : { status: "error" };
  } catch { return { status: "error" }; }
};

export function CallerContactPhoto({ number }: { number: string }) {
  const s = useStyles();
  const [consented, setConsented] = useState(false);
  const [match, setMatch] = useState<Match | null>(null);
  const [busy, setBusy] = useState(false);
  const lookup = useCallback(async () => {
    setBusy(true);
    const next = await read(number);
    setMatch(next);
    setBusy(false);
  }, [number]);
  // Consent is session-only; refresh only after the person explicitly opts in.
  useEffect(() => {
    if (!consented) return;
    const sub = AppState.addEventListener("change", state => {
      if (state === "active") void lookup();
    });
    return () => sub.remove();
  }, [consented, lookup]);
  if ((Platform.OS !== "android" && Platform.OS !== "ios") || !getNativeModule()?.lookupCallerContact) return null;
  const request = async () => {
    setConsented(true);
    const native = getNativeModule();
    if (!native) return;
    try {
      const raw = Platform.OS === "ios"
        ? await native.requestCallerContactsAccess?.()
        : await native.requestRuntimePermission?.("contacts");
      if (!raw) { setMatch({ status: "unavailable" }); return; }
      const result = JSON.parse(raw) as { granted?: boolean };
      if (result.granted) await lookup();
      else setMatch({ status: "permission_required" });
    } catch { setMatch({ status: "error" }); }
  };
  return (
    <View style={s.wrapper}>
      {!consented ? (
        <Pressable accessibilityRole="button" onPress={() => void request()}>
          <Text style={s.action}>Show saved contact photo (optional)</Text>
        </Pressable>
      ) : match?.status === "matched" ? (
        <View style={s.row}>
          {match.photoUri ? <Image source={{ uri: match.photoUri }} style={s.photo} /> : null}
          <View style={{ flex: 1 }}>
            <Text style={s.name}>{match.name || "Saved contact"}</Text>
            <Text style={s.note}>From your device contacts · Caller identity not verified</Text>
          </View>
        </View>
      ) : (
        <View style={s.wrapper}>
          <Text style={s.note}>{match?.status === "not_found" ? "No matching saved contact." : match?.status === "permission_required" ? "Contacts access is required. Grant it in Settings, then try again." : match?.status === "error" ? "Contact lookup unavailable." : "Checking contact permission…"}</Text>
          <Pressable accessibilityRole="button" disabled={busy} onPress={() => void lookup()}>
            <Text style={s.action}>{busy ? "Checking…" : "Check contacts again"}</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

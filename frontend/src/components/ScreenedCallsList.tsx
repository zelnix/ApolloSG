// "Calls Apollo screened" (Android). The incoming numbers Android handed to Apollo's call screening,
// recorded on this device only by ApolloCallScreeningService — not the call log. Tap a row to act on it
// (Check with Apollo on Call Guard; "use this number" elsewhere). Renders nothing where unsupported.
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import CircleHelp from "lucide-react-native/icons/circle-help";
import ShieldX from "lucide-react-native/icons/shield-x";
import React, { useCallback, useEffect, useState } from "react";
import { AppState, Pressable, Text, View } from "react-native";

import { Body, Button } from "@/src/components/ui";
import { isRejectionRequest, repeatAlertLine, screenedOutcomeLabel, screenedWhen, type ScreenedCall } from "@/src/domain/screenedCalls";
import { ScreenedCalls } from "@/src/security/screenedCalls";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const COLLAPSED = 5;

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" as const },
  header: { padding: spacing.lg, gap: 4 },
  title: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  count: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.muted },
  sub: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  row: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderTopWidth: 1, borderTopColor: c.border, minHeight: 64 },
  well: { width: 40, height: 40, borderRadius: 20, alignItems: "center" as const, justifyContent: "center" as const, backgroundColor: c.surfaceTertiary },
  wellRejected: { backgroundColor: c.barkingTint },
  info: { flex: 1, gap: 2 },
  number: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface },
  outcome: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary },
  when: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  action: { borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, backgroundColor: c.gold },
  actionText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  footer: { flexDirection: "row" as const, alignItems: "center" as const, justifyContent: "space-between" as const, paddingHorizontal: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  empty: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg },
}));

export function ScreenedCallsList({ onSelect, actionLabel = "Check", disabled = false, testID = "screened-calls" }: {
  onSelect: (number: string) => void; actionLabel?: string; disabled?: boolean; testID?: string;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const [calls, setCalls] = useState<ScreenedCall[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const supported = ScreenedCalls.isSupported();

  const load = useCallback(async () => { if (supported) setCalls(await ScreenedCalls.list()); }, [supported]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => { if (state === "active") void load(); });
    return () => sub.remove();
  }, [load]);

  if (!supported) return null;
  const shown = expanded ? calls ?? [] : (calls ?? []).slice(0, COLLAPSED);

  return (
    <View style={s.card} testID={testID}>
      <View style={s.header}>
        <Text style={s.title}>Recent callers</Text>
        <Text style={s.count}>Calls Apollo screened{calls ? ` · ${calls.length}` : ""}</Text>
        <Text style={s.sub}>Incoming numbers Android passed to Apollo&apos;s call screening, kept on this device for up to 30 days. Apollo doesn&apos;t read your call log.</Text>
      </View>
      {calls && calls.length === 0 ? (
        <View style={s.empty}>
          <Body testID={`${testID}-empty`}>No screened calls recorded. Eligible incoming calls may appear here after Android passes them to ApolloSG. Contacts and other calls may not appear.</Body>
        </View>
      ) : null}
      {shown.map((call, i) => {
        const rejected = isRejectionRequest(call.outcome);
        const { day, time } = screenedWhen(call.at);
        return (
          <Pressable
            key={`${call.number}-${call.at}`}
            testID={`${testID}-row-${i}`}
            accessibilityRole="button"
            accessibilityLabel={`${actionLabel} ${call.number} with ApolloSG`}
            disabled={disabled}
            onPress={() => onSelect(call.number)}
            style={({ pressed }) => [s.row, { opacity: disabled ? 0.5 : pressed ? 0.7 : 1 }]}
          >
            <View style={[s.well, rejected && s.wellRejected]}>
              {rejected ? <ShieldX size={20} color={colors.barkingText} /> : <CircleHelp size={20} color={colors.muted} />}
            </View>
            <View style={s.info}>
              <Text style={s.number}>{call.number}</Text>
              <Text style={s.outcome}>{screenedOutcomeLabel(call)}</Text>
              <Text style={s.when}>Caller identity not confirmed</Text>
              {call.repeat ? <Text style={s.outcome} testID={`${testID}-row-${i}-repeat`}>{repeatAlertLine(call)}</Text> : null}
              <Text style={s.when}>{day} · {time}</Text>
            </View>
            <View style={s.action}><Text style={s.actionText}>{actionLabel}</Text></View>
          </Pressable>
        );
      })}
      {calls && calls.length > 0 ? (
        <View style={s.footer}>
          {calls.length > COLLAPSED ? (
            <Pressable testID={`${testID}-toggle`} accessibilityRole="button" onPress={() => setExpanded((v) => !v)} hitSlop={8} style={{ flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: spacing.sm }}>
              <Text style={s.outcome}>{expanded ? "Show fewer" : `Show all ${calls.length}`}</Text>
              {expanded ? <ChevronUp size={16} color={colors.muted} /> : <ChevronDown size={16} color={colors.muted} />}
            </Pressable>
          ) : <View />}
          <Button testID={`${testID}-clear`} variant="ghost" label="Clear this list" onPress={() => void ScreenedCalls.clear().then(load)} />
        </View>
      ) : null}
    </View>
  );
}

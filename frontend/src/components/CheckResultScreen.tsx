// Universal Check Result screen — presentation only.
// Displays deterministic / device / technical check results. Every check
// that does NOT need a Magnum DI investigation renders through this component.
// Investigation results are handled by InvestigationCheckScreen instead.
//
// Operating principle: Apollo identifies the concern. This screen presents the
// finding. Technical detail lives behind progressive disclosure.

import { useRouter } from "expo-router";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import ExternalLink from "lucide-react-native/icons/external-link";
import React, { useCallback, useMemo, useState } from "react";
import { Linking, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Body, Button, Card, Pill } from "@/src/components/ui";
import type { ActionLink, CheckItem, CheckResultModel } from "@/src/domain/checkResult";
import { STATUS_LABEL, STATUS_TONE } from "@/src/domain/checkResult";
import { luddishCheckResult } from "@/src/domain/luddish";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { CloseButton } from "./CloseButton";
import { EvidenceProfileCard } from "./EvidenceProfileCard";
import { OfficialContactsCard } from "./OfficialContactsCard";
import { ResultQuestions } from "./ResultQuestions";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  title: { fontFamily: fonts.displayBold, fontSize: 26, color: c.onSurface },
  checkType: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurfaceSecondary, marginTop: 2 },
  close: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg, paddingBottom: spacing["3xl"] },

  sectionLabel: { fontFamily: fonts.textSemibold, fontSize: 11, letterSpacing: 0.4, color: c.muted, textTransform: "uppercase" },
  headline: { fontFamily: fonts.displayBold, fontSize: 22, lineHeight: 28, color: c.onSurface, letterSpacing: -0.3 },
  higginsText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  plainNote: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.muted, fontStyle: "italic", marginTop: 2 },
  questions: { borderTopWidth: 1, borderTopColor: c.divider, paddingTop: spacing.md },

  itemRow: { gap: 4, paddingVertical: spacing.sm },
  itemDivider: { borderTopWidth: 1, borderTopColor: c.divider },
  itemHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, justifyContent: "space-between" },
  itemName: { flex: 1, fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  itemFinding: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary },
  itemRaw: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary, backgroundColor: c.surfaceTertiary, borderRadius: radius.sm, padding: spacing.sm },

  disclosureBtn: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  disclosureLabel: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface },

  evidenceRow: { paddingVertical: spacing.xs, flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  evidenceLabel: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.muted, minWidth: 110 },
  evidenceValue: { flex: 1, fontFamily: fonts.text, fontSize: 13, color: c.onSurface },

  secondary: { gap: spacing.sm },

  actionLink: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, paddingHorizontal: spacing.sm, borderRadius: radius.sm, minHeight: 44 },
  actionLinkLabel: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brand, textDecorationLine: "underline" as const, flex: 1 },
  inlineLink: { color: c.brand, textDecorationLine: "underline" as const },
}));

export interface CheckResultScreenProps {
  result: CheckResultModel;
  /** Optional secondary actions (Save / Report / Recover / etc.) — rendered as a
   *  single row of buttons below the result. Keep to 3–4 at most. */
  actions?: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[];
  /** Optional: navigate to Higgins with context about this result. */
  onAskHiggins?: () => void;
  /** Optional close override — defaults to goBackOrHome. */
  onClose?: () => void;
  /** Offered on the evidence card while the email evidence is below the original message (L1/L2). */
  onAddOriginal?: () => void;
  addingOriginal?: boolean;
  /** What changed with the evidence on this check (an upgrade, or an original that didn't match). */
  evidenceNotice?: string | null;
  /** Shown above the result, e.g. the Same Number Reminder. */
  notice?: React.ReactNode;
  /** Shown below the result, e.g. the on-device AI note. Never part of the result itself. */
  footer?: React.ReactNode;
}

export function CheckResultScreen({ result, actions = [], onAskHiggins, onClose, onAddOriginal, addingOriginal, evidenceNotice, notice, footer }: CheckResultScreenProps) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [itemsOpen, setItemsOpen] = useState<Record<string, boolean>>({});
  // Two independent sections: opening the technical evidence must not also open the checklist.
  const [checkedOpen, setCheckedOpen] = useState(false);
  const [fullOpen, setFullOpen] = useState(false);
  // Higgins speaks Luddish (L1): plain words, the evidence unchanged. The full investigation details stay as recorded.
  const plain = useMemo(() => luddishCheckResult(result), [result]);
  // What the result already says, so the question buttons never repeat it.
  const shown = useMemo(() => [plain.headline, plain.higginsSays, plain.whatToDo, ...plain.notes], [plain]);

  const toggleItem = (id: string) => setItemsOpen((prev) => ({ ...prev, [id]: !prev[id] }));
  const close = () => (onClose ? onClose() : goBackOrHome(router));

  return (
    <View style={s.root} testID="check-result-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.md }]}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{result.gate}</Text>
          <Text style={s.checkType}>{result.checkType}</Text>
        </View>
        <CloseButton testID="check-result-close" onPress={close} />
      </View>

      <ScrollView
        contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing["3xl"] }]}
        testID="check-result-scroll"
      >
        {notice}
        {/* ── Apollo's finding ── */}
        <Card style={{ gap: spacing.md }} testID="check-result-main">
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
            <Pill tone={result.tone} label={result.checkType} testID="check-result-tone" />
            <Pill tone="neutral" label={`Confidence: ${result.confidence}`} testID="check-result-confidence" />
          </View>
          <Text style={s.headline} testID="check-result-headline">{plain.headline}</Text>

              <View style={{ gap: spacing.xs }}>
                <Text style={s.sectionLabel}>WHY ACTION WAS TAKEN</Text>
                <Text style={s.higginsText} testID="check-result-higgins">{plain.higginsSays}</Text>
                {plain.notes.length ? (
                  <View testID="check-result-plain-notes">
                    {plain.notes.map((note, i) => <Text key={i} style={s.plainNote}>{note}</Text>)}
                  </View>
                ) : null}
              </View>

              {plain.whatToDo || result.whatToDoLinks?.length ? (
                <View style={{ gap: spacing.xs }}>
                  <Text style={s.sectionLabel}>WHAT TO DO</Text>
                  {plain.whatToDo ? (
                    <LinkifiedText style={s.higginsText} text={plain.whatToDo} testID="check-result-whattodo" />
                  ) : null}
                  {result.whatToDoLinks?.length ? (
                    <View style={{ gap: 2, marginTop: result.whatToDo ? spacing.xs : 0 }}>
                      {result.whatToDoLinks.map((link, i) => (
                        <ActionLinkRow key={i} link={link} testID={`check-result-action-${i}`} />
                      ))}
                    </View>
                  ) : null}
                </View>
              ) : null}

              {/* ── Question buttons: the answer opens right here, under the result ── */}
              <View style={s.questions}>
                <ResultQuestions explanation={plain.explanation} shown={shown} testID="check-result-questions" />
              </View>
        </Card>

        <OfficialContactsCard verdicts={result.official} />

        {result.evidenceProfile ? (
          <EvidenceProfileCard profile={result.evidenceProfile} onAddOriginal={onAddOriginal} busy={addingOriginal} notice={evidenceNotice} testID="check-result-evidence-profile" />
        ) : null}

        {/* ── What Apollo checked ── */}
        <Card style={{ gap: 0 }} testID="check-result-items">
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={checkedOpen ? "Hide what Apollo checked" : "Show what Apollo checked"}
            onPress={() => setCheckedOpen((prev) => !prev)}
            style={s.disclosureBtn}
            testID="check-result-items-toggle"
          >
            <Text style={s.disclosureLabel}>What Apollo checked</Text>
            {checkedOpen ? <ChevronUp size={18} color={colors.onSurface} /> : <ChevronDown size={18} color={colors.onSurface} />}
          </Pressable>
          {checkedOpen ? (
            <>
              {result.items.length === 0 ? (
                <Body>Apollo did not record any check items.</Body>
              ) : (
                result.items.map((item, i) => (
                  <CheckItemRow
                    key={item.id}
                    item={item}
                    finding={plain.items[item.id] ?? item.finding}
                    open={!!itemsOpen[item.id]}
                    onToggle={() => toggleItem(item.id)}
                    showDivider={i > 0}
                  />
                ))
              )}
              <Text style={[s.checkType, { marginTop: spacing.sm }]}>Completed {new Date(result.completedAt).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}</Text>
            </>
          ) : null}
        </Card>

        {/* ── Progressive disclosure — full technical evidence ── */}
        {result.evidence.length > 0 ? (
          <Card style={{ gap: spacing.sm }} testID="check-result-full">
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={fullOpen ? "Hide full investigation" : "Show full investigation"}
              onPress={() => setFullOpen((prev) => !prev)}
              style={s.disclosureBtn}
              testID="check-result-full-toggle"
            >
              <Text style={s.disclosureLabel}>Full investigation details</Text>
              {fullOpen ? <ChevronUp size={18} color={colors.onSurface} /> : <ChevronDown size={18} color={colors.onSurface} />}
            </Pressable>
            {fullOpen ? (
              <View style={{ gap: spacing.xs }}>
                {result.evidence.map((row, i) => (
                  <View key={i} style={s.evidenceRow}>
                    <Text style={s.evidenceLabel}>{row.label}</Text>
                    <Text style={s.evidenceValue} testID={`check-result-evidence-${i}`}>{row.value}</Text>
                  </View>
                ))}
              </View>
            ) : null}
          </Card>
        ) : null}

        {/* ── Secondary row — Ask Higgins + extras ── */}
        {onAskHiggins || actions.length > 0 ? (
          <View style={s.secondary}>
            {onAskHiggins ? (
              <Button
                testID="check-result-ask-higgins"
                variant="secondary"
                label="Ask Higgins about this result"
                onPress={onAskHiggins}
              />
            ) : null}
            {actions.map((a) => (
              <Button
                key={a.testID}
                testID={a.testID}
                label={a.label}
                variant={a.variant ?? "ghost"}
                onPress={a.onPress}
              />
            ))}
          </View>
        ) : null}
        {footer}
      </ScrollView>
    </View>
  );
}

/** Render the `raw` payload as a human-readable string. Special-cases known shapes
 *  (urls, permissions, settings) so the person never sees raw JSON. */
function formatRaw(raw: Record<string, unknown>): string {
  // URLs list (from message/text gate links)
  if (Array.isArray(raw.urls) && raw.urls.length > 0) {
    return (raw.urls as string[]).map((u, i) => `${i + 1}. ${u}`).join("\n");
  }
  // Key-value pairs (settings, permissions, etc.)
  const entries = Object.entries(raw).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (entries.length > 0 && entries.every(([, v]) => typeof v === "string" || typeof v === "number" || typeof v === "boolean")) {
    return entries.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join("\n");
  }
  // Fallback — still avoid raw JSON; show a flat summary
  return entries.map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("\n");
}

function CheckItemRow({ item, finding, open, onToggle, showDivider }: { item: CheckItem; finding: string; open: boolean; onToggle: () => void; showDivider: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const hasRaw = !!item.raw && Object.keys(item.raw).length > 0;
  return (
    <Pressable
      accessibilityRole={hasRaw ? "button" : undefined}
      accessibilityLabel={`${item.name}: ${STATUS_LABEL[item.status]}`}
      onPress={hasRaw ? onToggle : undefined}
      disabled={!hasRaw}
      style={[s.itemRow, showDivider && s.itemDivider]}
      testID={`check-item-${item.id}`}
    >
      <View style={s.itemHeader}>
        <Text style={s.itemName}>{item.name}</Text>
        <Pill tone={STATUS_TONE[item.status]} label={STATUS_LABEL[item.status]} testID={`check-item-${item.id}-status`} />
      </View>
      {finding ? <Text style={s.itemFinding}>{finding}</Text> : null}
      {hasRaw ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
          <Text style={[s.checkType, { fontSize: 12 }]}>{open ? "Hide details" : "Show details"}</Text>
          {open ? <ChevronUp size={12} color={colors.onSurfaceSecondary} /> : <ChevronDown size={12} color={colors.onSurfaceSecondary} />}
        </View>
      ) : null}
      {open && hasRaw ? (
        <Text style={s.itemRaw}>{formatRaw(item.raw!)}</Text>
      ) : null}
    </Pressable>
  );
}

// ── URL detection & inline linking ──────────────────────────────────────────

const URL_RE = /https?:\/\/[^\s,)}\]]+/gi;

/** Render plain text with any embedded URLs as tappable inline links. */
function LinkifiedText({ text, style, testID }: { text: string; style: any; testID?: string }) {
  const s = useStyles();
  const parts = splitByUrls(text);
  if (parts.length === 1 && !parts[0].isUrl) {
    return <Text style={style} testID={testID}>{text}</Text>;
  }
  return (
    <Text style={style} testID={testID}>
      {parts.map((p, i) =>
        p.isUrl ? (
          <Text
            key={i}
            style={s.inlineLink}
            accessibilityRole="link"
            onPress={() => void Linking.openURL(p.text)}
          >
            {p.text}
          </Text>
        ) : (
          <Text key={i}>{p.text}</Text>
        ),
      )}
    </Text>
  );
}

function splitByUrls(text: string): { text: string; isUrl: boolean }[] {
  const result: { text: string; isUrl: boolean }[] = [];
  let lastIndex = 0;
  URL_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = URL_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      result.push({ text: text.slice(lastIndex, match.index), isUrl: false });
    }
    result.push({ text: match[0], isUrl: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    result.push({ text: text.slice(lastIndex), isUrl: false });
  }
  return result;
}

/** Tappable action link row — opens a URL for the user to take action. */
function ActionLinkRow({ link, testID }: { link: ActionLink; testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const handlePress = useCallback(() => {
    void Linking.openURL(link.url);
  }, [link.url]);
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={link.label}
      onPress={handlePress}
      style={({ pressed }) => [s.actionLink, pressed && { opacity: 0.7 }]}
      testID={testID}
    >
      <ExternalLink size={16} color={colors.brand} />
      <Text style={s.actionLinkLabel}>{link.label}</Text>
    </Pressable>
  );
}

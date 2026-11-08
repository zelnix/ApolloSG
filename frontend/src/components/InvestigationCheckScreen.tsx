// InvestigationCheckScreen — Full-screen investigation result presentation.
// This is the screen shown for investigation checks (messages, links, screenshots, etc.).
// It manages the Magnum DI investigation lifecycle directly, without Gate abstraction.
//
// Architecture: Submit -> Apollo privacy protection -> Magnum DI investigation -> this screen.
// CheckResultScreen handles deterministic/device results; this handles investigation results.
import { useRouter } from "expo-router";
import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { InvestigationFlow } from "@/src/components/InvestigationFlow";
import { Button } from "@/src/components/ui";
import type { CheckResultModel } from "@/src/domain/checkResult";
import type { HigginsIssueContext } from "@/src/domain/higginsHandoff";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { CloseButton } from "./CloseButton";
import { EvidenceProfileCard } from "./EvidenceProfileCard";
import { OfficialContactsCard } from "./OfficialContactsCard";
import type { OriginalSourceInput } from "@/src/store/originalSource";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: {
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  title: { fontFamily: fonts.displayBold, fontSize: 26, color: c.onSurface },
  checkType: {
    fontFamily: fonts.textMedium,
    fontSize: 13,
    color: c.onSurfaceSecondary,
    marginTop: 2,
  },
  close: {
    width: 44,
    height: 44,
    borderRadius: radius.pill,
    backgroundColor: c.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  content: {
    paddingHorizontal: spacing.xl,
    gap: spacing.lg,
    paddingBottom: spacing["3xl"],
  },
  secondary: { gap: spacing.sm },
}));

export interface InvestigationCheckScreenProps {
  /** Static check result model — used for header info (gate name, check type). */
  result: CheckResultModel;
  /** Higgins issue context for the investigation. */
  investigationContext: HigginsIssueContext;
  /** Natural-language question for the investigation. */
  investigationQuestion: string;
  /** Stable submission ID for the check. */
  submissionId: string;
  /** Patrol event ID to link the investigation to. */
  eventId?: string | null;
  /** An investigation Apollo already opened for this material — followed instead of starting a new one. */
  caseId?: string | null;
  /** Optional action buttons below the investigation. */
  actions?: {
    label: string;
    onPress: () => void;
    testID: string;
    variant?: "primary" | "secondary" | "ghost";
  }[];
  /** Optional close override — defaults to goBackOrHome. */
  onClose?: () => void;
  /** Offered on the evidence card while the email evidence is below the original message (L1/L2). */
  onAddOriginal?: () => void;
  addingOriginal?: boolean;
  /** What changed with the evidence on this check (an upgrade, or an original that didn't match). */
  evidenceNotice?: string | null;
  /** The material exactly as checked, shown on the case's top card (see InvestigationFlow). */
  original?: OriginalSourceInput | null;
  /** Shown above the investigation (e.g. the Same Number Reminder). */
  notice?: React.ReactNode;
  /** Shown below the investigation, e.g. the on-device AI note. Never part of the result itself. */
  footer?: React.ReactNode;
}

export function InvestigationCheckScreen({
  result,
  investigationContext,
  investigationQuestion,
  submissionId,
  eventId,
  caseId,
  actions = [],
  onClose,
  onAddOriginal,
  addingOriginal,
  evidenceNotice,
  original,
  notice,
  footer,
}: InvestigationCheckScreenProps) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const close = () => (onClose ? onClose() : goBackOrHome(router));

  return (
    <View style={s.root} testID="investigation-check-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.md }]}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{result.gate}</Text>
          <Text style={s.checkType}>{result.checkType}</Text>
        </View>
        <CloseButton testID="investigation-check-close" onPress={close} />
      </View>

      <ScrollView
        contentContainerStyle={[
          s.content,
          { paddingBottom: insets.bottom + spacing["3xl"] },
        ]}
        testID="investigation-check-scroll"
      >
        {notice}
        <InvestigationFlow
          submissionId={submissionId}
          context={investigationContext}
          question={investigationQuestion}
          testID="investigation-check-flow"
          autoStart
          eventId={eventId}
          caseId={caseId}
          openingQuestion={false}
          original={original}
        />

        <OfficialContactsCard verdicts={result.official} testID="investigation-check-official" />

        {result.evidenceProfile ? (
          <EvidenceProfileCard profile={result.evidenceProfile} onAddOriginal={onAddOriginal} busy={addingOriginal} notice={evidenceNotice} testID="investigation-check-evidence-profile" />
        ) : null}

        {actions.length > 0 ? (
          <View style={s.secondary}>
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

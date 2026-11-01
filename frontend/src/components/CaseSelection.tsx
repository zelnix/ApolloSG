// Choosing cases to delete on Threats and Patrol history: the tick on each row, the bar with "Select all", and the
// confirmation that says exactly what goes (this phone and ApolloSG's server, everything linked).
import Check from "lucide-react-native/icons/check";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { Sheet } from "@/src/components/Sheet";
import { Button } from "@/src/components/ui";
import { countLabel } from "@/src/domain/caseDelete";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  box: { width: 24, height: 24, borderRadius: radius.sm, borderWidth: 2, alignItems: "center", justifyContent: "center" },
  bar: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  all: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44, flexShrink: 1 },
  allText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, flexShrink: 1 },
  cancel: { minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.sm },
  cancelText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brand },
  body: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  note: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurfaceSecondary },
}));

/** The tick on a row while choosing. */
export function SelectBox({ selected, testID }: { selected: boolean; testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={[s.box, { borderColor: selected ? colors.brand : colors.borderStrong, backgroundColor: selected ? colors.brand : "transparent" }]}
      testID={testID} accessibilityElementsHidden importantForAccessibility="no">
      {selected ? <Check size={16} color={colors.onBrandPrimary} /> : null}
    </View>
  );
}

/** Select all · Cancel · Delete (N), shown while choosing. */
export function SelectionBar({ count, total, onToggleAll, onCancel, onDelete, testID }: {
  count: number; total: number; onToggleAll: () => void; onCancel: () => void; onDelete: () => void; testID: string;
}) {
  const s = useStyles();
  const all = total > 0 && count === total;
  return (
    <View style={s.bar} testID={testID}>
      <Pressable style={s.all} onPress={onToggleAll} disabled={!total} accessibilityRole="checkbox" accessibilityState={{ checked: all, disabled: !total }}
        accessibilityLabel={all ? "Clear the selection" : `Select all ${total}`} testID={`${testID}-all`}>
        <SelectBox selected={all} />
        <Text style={s.allText} numberOfLines={1}>{count ? `${count} selected` : "Select all"}</Text>
      </Pressable>
      <View style={{ flex: 1 }} />
      <Pressable style={s.cancel} onPress={onCancel} accessibilityRole="button" testID={`${testID}-cancel`}>
        <Text style={s.cancelText}>Cancel</Text>
      </Pressable>
      <Button testID={`${testID}-delete`} variant="danger" label={count ? `Delete (${count})` : "Delete"} disabled={!count} onPress={onDelete} />
    </View>
  );
}

/** "Delete N cases?" — what goes, from where, and that it can't be undone. */
export function DeleteConfirmSheet({ visible, count, records, noun, busy, onConfirm, onClose, testID }: {
  visible: boolean; count: number; records: number; noun: "case" | "record"; busy: boolean; onConfirm: () => void; onClose: () => void; testID: string;
}) {
  const s = useStyles();
  const them = count === 1 ? "It" : "They";
  const more = records > count ? ` That's ${countLabel(records, "record")} in all, with their earlier checks.` : "";
  return (
    <Sheet visible={visible} onClose={busy ? () => undefined : onClose} title={`Delete ${countLabel(count, noun)}?`} testID={testID}
      footer={<>
        <Button testID={`${testID}-confirm`} variant="danger" label={busy ? "Deleting…" : `Delete ${countLabel(count, noun)}`} disabled={busy} onPress={onConfirm} />
        <Button testID={`${testID}-cancel`} variant="secondary" label="Cancel" disabled={busy} onPress={onClose} />
      </>}>
      <Text style={s.body} testID={`${testID}-body`}>
        {`${them}'ll be deleted from this phone and from ApolloSG's server, with everything linked: the original evidence, pictures and files, saved investigation reports, and server working copies.${more}`}
      </Text>
      <Text style={s.note}>This can&apos;t be undone. The message in your own Messages or email app isn&apos;t touched.</Text>
    </Sheet>
  );
}

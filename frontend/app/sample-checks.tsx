/**
 * Sample Checks screen — accessible from the hamburger menu in all builds.
 *
 * Exercises production processes and functions by feeding sample source threats through
 * the real pipeline: real on-device analysis, real Triage, real Magnum DI where Triage
 * escalates. Nothing is simulated or pre-made.
 */
import { useRouter } from "expo-router";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import FlaskConical from "lucide-react-native/icons/flask-conical";
import React, { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChildScreenHeader } from "@/src/components/ChildScreenHeader";
import { Sheet } from "@/src/components/ui";
import { SAMPLE_KINDS, type SampleKind } from "@/src/sampleChecks";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  intro: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary, lineHeight: 20, paddingHorizontal: spacing.xl, paddingTop: spacing.sm, paddingBottom: spacing.md },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface, paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.xs },
  card: { marginHorizontal: spacing.lg, borderRadius: radius.lg, backgroundColor: c.surfaceSecondary, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" as const },
  row: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md, padding: spacing.md, minHeight: 56 },
  rowDivider: { height: 0.5, backgroundColor: c.divider, marginLeft: spacing.md },
  rowBody: { flex: 1, gap: 2 },
  rowLabel: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  rowSub: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary },
  // Item picker sheet
  itemRow: { flexDirection: "row" as const, alignItems: "flex-start" as const, gap: spacing.md, padding: spacing.md, minHeight: 52, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  itemBody: { flex: 1, gap: 2 },
  itemPrimary: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  itemSecondary: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary },
  itemDesc: { fontFamily: fonts.text, fontSize: 11, color: c.muted, fontStyle: "italic" as const },
}));

export default function SampleChecksScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [selectedKind, setSelectedKind] = useState<SampleKind | null>(null);

  const kinds = (Object.entries(SAMPLE_KINDS) as [SampleKind, typeof SAMPLE_KINDS[SampleKind]][])
    .filter(([, def]) => def.items.length > 0);

  const runSample = (kind: SampleKind, sampleId: string) => {
    setSelectedKind(null);
    router.push({ pathname: SAMPLE_KINDS[kind].path as any, params: { sample: sampleId } });
  };

  return (
    <View style={s.root} testID="sample-checks-screen">
      <ChildScreenHeader title="Sample checks" testID="sample-checks-header" />
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }}>
        <Text style={s.intro}>
          Pick a sample threat to exercise the real production check pipeline. Each sample goes through
          the same on-device analysis, the same Triage, and the same investigation that a real submission
          runs. A Threat Case opens only if Apollo&apos;s rules find one.
        </Text>

        <Text style={s.sectionTitle}>What to check</Text>
        <View style={s.card}>
          {kinds.map(([kind, def], i) => (
            <React.Fragment key={kind}>
              {i > 0 ? <View style={s.rowDivider} /> : null}
              <Pressable
                testID={`sample-kind-${kind}`}
                accessibilityRole="button"
                accessibilityLabel={`${def.label} — ${def.gate}`}
                onPress={() => setSelectedKind(kind)}
                style={({ pressed }) => [s.row, { opacity: pressed ? 0.85 : 1 }]}
              >
                <FlaskConical size={20} color={colors.brandPrimary} />
                <View style={s.rowBody}>
                  <Text style={s.rowLabel}>{def.label}</Text>
                  <Text style={s.rowSub}>{def.gate} · {def.items.length} sample{def.items.length === 1 ? "" : "s"}</Text>
                </View>
                <ChevronRight size={16} color={colors.onSurfaceSecondary} />
              </Pressable>
            </React.Fragment>
          ))}
        </View>
      </ScrollView>

      {/* Item picker */}
      <Sheet
        visible={!!selectedKind}
        onClose={() => setSelectedKind(null)}
        title={selectedKind ? SAMPLE_KINDS[selectedKind].label : ""}
        testID="sample-item-picker"
      >
        <Text style={[s.intro, { paddingHorizontal: 0 }]}>
          Apollo runs the real check on whichever one you pick. A Threat Case opens only if Apollo&apos;s rules find one.
        </Text>
        <ScrollView style={{ maxHeight: 400 }}>
          {selectedKind && SAMPLE_KINDS[selectedKind].items.map((item) => (
            <Pressable
              key={item.id}
              testID={`sample-item-${item.id}`}
              accessibilityRole="button"
              onPress={() => runSample(selectedKind, item.id)}
              style={({ pressed }) => [s.itemRow, { opacity: pressed ? 0.85 : 1 }]}
            >
              <View style={s.itemBody}>
                <Text style={s.itemPrimary} numberOfLines={2}>{item.primary}</Text>
                {item.secondary ? <Text style={s.itemSecondary} numberOfLines={2}>{item.secondary}</Text> : null}
                <Text style={s.itemDesc}>{item.description}</Text>
              </View>
              <ChevronRight size={16} color={colors.onSurfaceSecondary} />
            </Pressable>
          ))}
        </ScrollView>
      </Sheet>
    </View>
  );
}

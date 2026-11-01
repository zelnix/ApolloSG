/**
 * Patrol History — the unified record of Apollo's detection, protection and
 * observable device security activity on this device.
 *
 * Sources: PatrolEvents (existing threat/check records) + ActivityLog (device
 * posture changes, protection health events, background check records).
 *
 * Features:
 * - Filters: All | Checks | Detections | Protection | Device
 * - Day-grouped timeline with icons and colour-coded outcomes
 * - Routine successful checks grouped with count + expandable timestamps
 * - Concerns, failures and device changes individually visible
 * - Expandable detail per entry (limitations, before/after settings)
 * - Linked threat cases shown as tappable references
 * - Export and delete controls preserved
 */
import { Redirect, useRouter } from "expo-router";
import AlertTriangle from "lucide-react-native/icons/triangle-alert";
import Activity from "lucide-react-native/icons/activity";
import CheckCircle from "lucide-react-native/icons/circle-check";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import Download from "lucide-react-native/icons/download";
import Monitor from "lucide-react-native/icons/monitor";
import RefreshCw from "lucide-react-native/icons/refresh-cw";
import Search from "lucide-react-native/icons/search";
import Settings from "lucide-react-native/icons/settings";
import ShieldAlert from "lucide-react-native/icons/shield-alert";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import ShieldX from "lucide-react-native/icons/shield-x";
import XCircle from "lucide-react-native/icons/circle-x";
import Zap from "lucide-react-native/icons/zap";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { CheckToolHeader } from "@/src/components/CheckToolHeader";
import { DeleteConfirmSheet, SelectBox, SelectionBar } from "@/src/components/CaseSelection";
import { Button, Pill } from "@/src/components/ui";
import { countLabel } from "@/src/domain/caseDelete";
import {
  buildTimeline,
  filterCounts,
  FILTERS,
  type FilterKey,
  type TimelineDay,
  type TimelineGroup,
  type TimelineItem,
} from "@/src/domain/patrolActivity";
import { loadAllActivities, deleteActivities as deleteActivityEntries, type ActivityEntry } from "@/src/store/activityLog";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { exportPatrolPdf } from "@/src/utils/exportPatrol";

// ── Icon resolver ────────────────────────────────────────────────────────────

const ICON_MAP: Record<TimelineItem["iconHint"], React.ComponentType<{ size: number; color: string }>> = {
  "shield-check": ShieldCheck,
  "shield-alert": ShieldAlert,
  "shield-x": ShieldX,
  "search": Search,
  "settings": Settings,
  "monitor": Monitor,
  "lock": ShieldCheck,
  "unlock": ShieldX,
  "zap": Zap,
  "activity": Activity,
  "check-circle": CheckCircle,
  "alert-triangle": AlertTriangle,
  "x-circle": XCircle,
  "refresh-cw": RefreshCw,
};

// ── Styles ───────────────────────────────────────────────────────────────────

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, paddingBottom: spacing.sm },
  dayLabel: { fontFamily: fonts.displayBold, fontSize: 13, color: c.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs, paddingHorizontal: spacing.xl },
  // Filter bar
  filterBar: { flexDirection: "row" as const, paddingHorizontal: spacing.lg, gap: spacing.xs, paddingBottom: spacing.sm },
  filterChip: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  filterChipActive: { backgroundColor: c.brandPrimary, borderColor: c.brandPrimary },
  filterText: { fontFamily: fonts.textMedium, fontSize: 12, color: c.onSurface },
  filterTextActive: { color: c.onBrandPrimary },
  // Timeline row
  card: { marginHorizontal: spacing.lg, borderRadius: radius.lg, backgroundColor: c.surfaceSecondary, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" as const },
  row: { flexDirection: "row" as const, alignItems: "flex-start" as const, gap: spacing.md, padding: spacing.md, minHeight: 52 },
  rowSelected: { backgroundColor: "rgba(22,34,53,0.04)" },
  iconWrap: { width: 32, height: 32, borderRadius: 16, alignItems: "center" as const, justifyContent: "center" as const, marginTop: 2 },
  rowBody: { flex: 1, gap: 2 },
  rowTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, lineHeight: 19 },
  rowDetail: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary, lineHeight: 17 },
  rowMeta: { fontFamily: fonts.text, fontSize: 11, color: c.muted },
  rowFooter: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.sm, marginTop: 2 },
  // Expanded detail
  expandedWrap: { paddingHorizontal: spacing.md, paddingBottom: spacing.md, gap: spacing.xs, borderTopWidth: 0.5, borderTopColor: c.divider, marginTop: spacing.xs, paddingTop: spacing.sm },
  expandedText: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary, lineHeight: 17 },
  expandedLabel: { fontFamily: fonts.textSemibold, fontSize: 11, color: c.muted, textTransform: "uppercase" as const, letterSpacing: 0.3 },
  limitationRow: { flexDirection: "row" as const, gap: spacing.xs, paddingLeft: spacing.sm },
  limitationDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: c.muted, marginTop: 6 },
  changeRow: { flexDirection: "row" as const, gap: spacing.sm, alignItems: "center" as const },
  changeArrow: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.muted },
  changeValue: { fontFamily: fonts.text, fontSize: 12, color: c.onSurface },
  // Group row (collapsed routine checks)
  groupRow: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md, padding: spacing.md, minHeight: 44 },
  groupTitle: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurfaceSecondary, flex: 1 },
  groupCount: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.muted },
  groupExpanded: { paddingHorizontal: spacing.md, paddingBottom: spacing.sm, gap: 2 },
  groupTimestamp: { fontFamily: fonts.text, fontSize: 11, color: c.muted, paddingVertical: 2 },
  // Case link
  caseLink: { flexDirection: "row" as const, alignItems: "center" as const, gap: 4, paddingVertical: 2 },
  caseLinkText: { fontFamily: fonts.textSemibold, fontSize: 11, color: c.brandPrimary },
  // Divider between rows in a card
  divider: { height: 0.5, backgroundColor: c.divider },
  // Controls
  controlsRow: { flexDirection: "row" as const, gap: spacing.sm, paddingHorizontal: spacing.xl, paddingBottom: spacing.sm },
  // Empty state
  emptyText: { fontFamily: fonts.text, fontSize: 15, color: c.muted, textAlign: "center" as const, paddingVertical: spacing.xl * 2, paddingHorizontal: spacing.xl },
}));

// ── Tone colours ─────────────────────────────────────────────────────────────

function toneColors(tone: TimelineItem["tone"], colors: ReturnType<typeof useTheme>["colors"]): { bg: string; fg: string } {
  switch (tone) {
    case "success": return { bg: "rgba(79,175,131,0.12)", fg: colors.restingText ?? "#2E7D32" };
    case "concern": return { bg: "rgba(217,83,79,0.10)", fg: colors.barkingText ?? "#C62828" };
    case "failure": return { bg: "rgba(217,83,79,0.10)", fg: colors.barkingText ?? "#C62828" };
    case "change": return { bg: "rgba(217,119,6,0.10)", fg: colors.warning ?? "#D4780A" };
    case "neutral": default: return { bg: "rgba(107,114,128,0.10)", fg: colors.muted ?? "#52606D" };
  }
}

// ── Single row ───────────────────────────────────────────────────────────────

function TimelineRowSingle({ item, selecting, selected, onPress, onToggle }: {
  item: TimelineItem; selecting: boolean; selected: boolean;
  onPress: () => void; onToggle: () => void;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const tc = toneColors(item.tone, colors);
  const IconEl = ICON_MAP[item.iconHint] ?? Activity;
  const time = new Date(item.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const hasExpansion = !!(item.expandedDetail || item.limitations?.length || item.beforeValue);

  const handlePress = () => {
    if (selecting) { onToggle(); return; }
    if (hasExpansion) { setExpanded(!expanded); return; }
    onPress();
  };

  return (
    <View>
      <Pressable
        onPress={handlePress}
        accessibilityRole={selecting ? "checkbox" : "button"}
        accessibilityState={selecting ? { checked: selected } : undefined}
        style={({ pressed }) => [s.row, selected && s.rowSelected, { opacity: pressed ? 0.85 : 1 }]}
        testID={`history-row-${item.id}`}
      >
        {selecting ? <SelectBox selected={selected} testID={`history-row-${item.id}-select`} /> : null}
        <View style={[s.iconWrap, { backgroundColor: tc.bg }]}>
          <IconEl size={16} color={tc.fg} />
        </View>
        <View style={s.rowBody}>
          <Text style={s.rowTitle} numberOfLines={2}>{item.title}</Text>
          <Text style={s.rowDetail} numberOfLines={2}>{item.detail}</Text>
          <View style={s.rowFooter}>
            <Text style={s.rowMeta}>{time} · {item.actor}</Text>
            {item.simulated ? <Pill compact label="Simulated" /> : null}
            {item.verified ? <Pill compact tone="resting" label="Verified" /> : null}
          </View>
          {item.linkedCaseRef && !selecting ? (
            <Pressable
              style={s.caseLink}
              onPress={() => item.linkedEventId && router.push(`/patrol/${item.linkedEventId}`)}
              hitSlop={6}
              testID={`history-link-${item.id}`}
            >
              <Text style={s.caseLinkText}>{item.linkedCaseRef}</Text>
              <ChevronRight size={12} color={colors.brandPrimary} />
            </Pressable>
          ) : null}
        </View>
        {!selecting && hasExpansion ? (
          expanded ? <ChevronUp size={16} color={colors.muted} /> : <ChevronDown size={16} color={colors.muted} />
        ) : null}
        {!selecting && !hasExpansion && item.linkedEventId ? (
          <ChevronRight size={16} color={colors.muted} />
        ) : null}
      </Pressable>

      {expanded ? (
        <View style={s.expandedWrap}>
          {item.expandedDetail ? (
            <Text style={s.expandedText}>{item.expandedDetail}</Text>
          ) : null}
          {item.beforeValue && item.afterValue ? (
            <View>
              <Text style={s.expandedLabel}>Setting change</Text>
              <View style={s.changeRow}>
                <Text style={s.changeValue}>{item.beforeValue}</Text>
                <Text style={s.changeArrow}>→</Text>
                <Text style={s.changeValue}>{item.afterValue}</Text>
              </View>
            </View>
          ) : null}
          {item.limitations?.length ? (
            <View style={{ gap: 2 }}>
              <Text style={s.expandedLabel}>Limitations</Text>
              {item.limitations.map((lim, i) => (
                <View key={i} style={s.limitationRow}>
                  <View style={s.limitationDot} />
                  <Text style={[s.expandedText, { flex: 1 }]}>{lim}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

// ── Group row (collapsed routine checks) ─────────────────────────────────────

function TimelineRowGroup({ group, selecting }: { group: TimelineGroup; selecting: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const tc = toneColors(group.tone, colors);
  const IconEl = ICON_MAP[group.iconHint] ?? CheckCircle;

  return (
    <View>
      <Pressable
        onPress={() => setExpanded(!expanded)}
        style={({ pressed }) => [s.groupRow, { opacity: pressed ? 0.85 : 1 }]}
        testID={`history-group-${group.groupKey}`}
      >
        <View style={[s.iconWrap, { backgroundColor: tc.bg }]}>
          <IconEl size={16} color={tc.fg} />
        </View>
        <Text style={s.groupTitle} numberOfLines={1}>{group.title}</Text>
        <Text style={s.groupCount}>{group.count}</Text>
        {expanded ? <ChevronUp size={16} color={colors.muted} /> : <ChevronDown size={16} color={colors.muted} />}
      </Pressable>
      {expanded ? (
        <View style={s.groupExpanded}>
          {group.items.map((item) => (
            <Text key={item.id} style={s.groupTimestamp}>
              {new Date(item.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} — {item.title}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

// ── Day section header + card ────────────────────────────────────────────────

function DaySection({ day, selecting, selected, onToggle, onOpen }: {
  day: TimelineDay; selecting: boolean; selected: Set<string>;
  onToggle: (id: string) => void; onOpen: (item: TimelineItem) => void;
}) {
  const s = useStyles();
  return (
    <View>
      <Text style={s.dayLabel}>{day.label}</Text>
      <View style={s.card}>
        {day.rows.map((row, i) => (
          <React.Fragment key={row.kind === "group" ? row.groupKey : row.item.id}>
            {i > 0 ? <View style={s.divider} /> : null}
            {row.kind === "group" ? (
              <TimelineRowGroup group={row} selecting={selecting} />
            ) : (
              <TimelineRowSingle
                item={row.item}
                selecting={selecting}
                selected={selected.has(row.item.id)}
                onPress={() => onOpen(row.item)}
                onToggle={() => onToggle(row.item.id)}
              />
            )}
          </React.Fragment>
        ))}
      </View>
    </View>
  );
}

// ── Main Screen ──────────────────────────────────────────────────────────────

export default function PatrolHistory() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { ready, setupDone, events, showToast, deviceId, deleteCases } = useApollo();
  const [activities, setActivities] = useState<ActivityEntry[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [exporting, setExporting] = useState(false);

  // Load activity log
  const loadActivities = useCallback(() => {
    void loadAllActivities().then(setActivities).catch(() => setActivities([]));
  }, []);
  useEffect(() => { loadActivities(); }, [loadActivities]);

  // Pull to refresh
  const [pulling, setPulling] = useState(false);
  const onPull = () => { setPulling(true); loadActivities(); setPulling(false); };

  // Build timeline
  const timeline = useMemo(() => buildTimeline(events, activities, filter), [events, activities, filter]);
  const counts = useMemo(() => filterCounts(events, activities), [events, activities]);

  // Selection state
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const allIds = useMemo(() => {
    const ids: string[] = [];
    for (const day of timeline) for (const row of day.rows) {
      if (row.kind === "single") ids.push(row.item.id);
      else for (const item of row.items) ids.push(item.id);
    }
    return ids;
  }, [timeline]);

  const stopSelecting = () => { setSelecting(false); setSelected(new Set()); setConfirming(false); };
  const toggle = (id: string) => setSelected((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const toggleAll = () => setSelected(selected.size === allIds.length ? new Set() : new Set(allIds));

  // Delete selected entries
  const confirmDelete = async () => {
    setDeleting(true);
    try {
      // Separate patrol events from activity entries
      const patrolEventIds: string[] = [];
      const activityIds: string[] = [];
      for (const id of selected) {
        if (id.startsWith("pe:")) patrolEventIds.push(id.slice(3));
        else if (id.startsWith("ae:")) activityIds.push(id.slice(3));
      }

      let ok = true;
      // Delete patrol events (includes server copy)
      if (patrolEventIds.length) {
        const chosen = events.filter((e) => patrolEventIds.includes(e.event_id));
        const result = await deleteCases(chosen, false);
        ok = result.ok;
      }
      // Delete activity entries (local only — does NOT delete linked Threat Cases)
      if (activityIds.length) {
        await deleteActivityEntries(new Set(activityIds));
      }

      if (ok) {
        const total = patrolEventIds.length + activityIds.length;
        showToast(`Deleted ${countLabel(total, "record")} from this device.`, "neutral");
        stopSelecting();
        loadActivities();
      } else {
        setConfirming(false);
      }
    } finally { setDeleting(false); }
  };

  // Open a timeline item
  const openItem = (item: TimelineItem) => {
    if (item.linkedEventId) router.push(`/patrol/${item.linkedEventId}`);
  };

  // Export
  const share = async () => {
    setExporting(true);
    try {
      const outcome = await exportPatrolPdf(events, deviceId);
      if (outcome === "printed") showToast("Opened the history for printing or saving.", "neutral");
    } catch {
      showToast("ApolloSG couldn't produce the history file.", "growling");
    } finally { setExporting(false); }
  };

  if (ready && !setupDone) return <Redirect href="/onboarding" />;

  // Flatten for FlatList
  const sections = timeline;

  return (
    <View style={s.root} testID="patrol-history-root">
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title="Patrol history"
          info={{ title: "About patrol history", body: [
            "A record of Apollo's detection, protection and observable device security activity on this device.",
            "Checks: background and device checks, including successful checks with no concerns.",
            "Detections: suspicious activity and threats Apollo detected.",
            "Protection: verified blocks, protective actions, and gate status changes.",
            "Device changes: permissions, screen lock, VPN, Private DNS and other security settings.",
            "Routine checks are grouped; concerns and changes stay individually visible.",
          ] }}
          testID="patrol-history"
        />
      </View>

      {/* Filter chips */}
      <View style={s.filterBar} testID="patrol-history-filters">
        {FILTERS.map(({ key, label }) => {
          const active = filter === key;
          const count = counts[key];
          return (
            <Pressable
              key={key}
              style={[s.filterChip, active && s.filterChipActive]}
              onPress={() => setFilter(key)}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              testID={`patrol-history-filter-${key}`}
            >
              <Text style={[s.filterText, active && s.filterTextActive]}>
                {label}{count > 0 ? ` (${count})` : ""}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Controls row */}
      <View style={s.controlsRow}>
        <View style={{ flex: 1 }}>
          <Button testID="patrol-history-export" variant="ghost" label={exporting ? "Preparing…" : "Export"}
            icon={<Download size={16} color={colors.onSurface} />} onPress={() => void share()} disabled={exporting} />
        </View>
        {!selecting && (events.length > 0 || activities.length > 0) ? (
          <Button testID="patrol-history-select" variant="secondary" label="Select" onPress={() => setSelecting(true)} />
        ) : null}
      </View>

      {selecting ? (
        <View style={{ paddingHorizontal: spacing.lg, paddingBottom: spacing.sm }}>
          <SelectionBar count={selected.size} total={allIds.length} onToggleAll={toggleAll} onCancel={stopSelecting}
            onDelete={() => setConfirming(true)} testID="patrol-history-selection" />
        </View>
      ) : null}

      {/* Timeline */}
      <FlatList
        data={sections}
        keyExtractor={(item) => item.date}
        renderItem={({ item: day }) => (
          <DaySection
            day={day}
            selecting={selecting}
            selected={selected}
            onToggle={toggle}
            onOpen={openItem}
          />
        )}
        refreshControl={<RefreshControl refreshing={pulling} onRefresh={onPull} tintColor={colors.brand} colors={[colors.brand]} />}
        ListEmptyComponent={
          <Text style={s.emptyText}>
            {filter === "all"
              ? "No activity recorded yet. Checks, detections, protection events and device changes will appear here."
              : `No ${FILTERS.find((f) => f.key === filter)?.label.toLowerCase()} activity recorded.`}
          </Text>
        }
        contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }}
        testID="patrol-history-list"
      />

      <DeleteConfirmSheet visible={confirming} count={selected.size} records={selected.size} noun="record" busy={deleting}
        onConfirm={() => void confirmDelete()} onClose={() => setConfirming(false)} testID="patrol-history-delete-confirm" />
    </View>
  );
}

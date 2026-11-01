/**
 * Threats Screen — Approved mock-up implementation.
 *
 * Shows the user's list of Apollo Threat Cases populated from real Patrol data.
 * Patrol is the underlying data source; there is no separate Patrol UI.
 * Magnum DI investigation data is attached when applicable.
 *
 * Features:
 * - Threat cards with source icon, title, identity, date, type, status, chevron
 * - Status filters: All | Investigating | Blocked | Resolved | No threat
 * - Sort control: Latest first / Oldest first
 * - Tapping a card opens the shared Threat Case detail screen
 * - Deduplication by Threat Case ID
 */
import Camera from "lucide-react-native/icons/camera";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import Clock from "lucide-react-native/icons/clock";

import FileText from "lucide-react-native/icons/file-text";
import Globe from "lucide-react-native/icons/globe";
import Link2 from "lucide-react-native/icons/link-2";
import Mail from "lucide-react-native/icons/mail";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import Search from "lucide-react-native/icons/search";
import Shield from "lucide-react-native/icons/shield";
import Smartphone from "lucide-react-native/icons/smartphone";
import UsersRound from "lucide-react-native/icons/users-round";
import React, { useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { NewBadge } from "@/src/components/NewBadge";
import { DeleteConfirmSheet, SelectBox, SelectionBar } from "@/src/components/CaseSelection";
import { countLabel, deletionSet } from "@/src/domain/caseDelete";
import { useNewCases } from "@/src/hooks/useNewCases";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  threatCaseStatus,
  STATUS_LABELS,
  STATUS_COLORS,
  formatDateTime,
  isSimulated,
  isSampleCheck,
  threatCaseId,
  threatCases as allThreatCases,
  type ThreatCaseStatus,
} from "@/src/domain/threatCase";
import { eventBrief } from "@/src/domain/homeHeroBrief";
import { useKeptIdentifiers } from "@/src/hooks/useKeptIdentifiers";
import type { PatrolEvent, SourceMetadata } from "@/src/domain/types";
import { InfoButton, type ScreenInfo } from "@/src/components/InfoButton";
import { SettledByBadge } from "@/src/components/SettledByBadge";
import { EvidenceBadge } from "@/src/components/EvidenceBadge";
import { evidenceStrength } from "@/src/domain/triage/evidenceProfile";
import { AlertsButton } from "@/src/components/AlertsButton";
import { AppMenuButton } from "@/src/components/AppMenu";
import { HeaderIconTile } from "@/src/components/HeaderIconTile";
import { SourcePickerSheet, type SourceChoice } from "@/src/components/SourcePickerSheet";
import { Button, Pill } from "@/src/components/ui";
import { simulation } from "@/src/simulation";
import ShieldAlert from "lucide-react-native/icons/shield-alert";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const THREATS_INFO: ScreenInfo = { title: "About Threats", body: [
  "Threats lists everything Apollo has detected or investigated for you: blocked links, suspicious messages, calls and investigation cases.",
  "Use the filter to see threats by status, and tap any threat to see its overview, the original evidence and its history.",
  "Each threat shows the evidence ApolloSG received for it — from a screenshot or a name only up to an original file or something ApolloSG saw itself. Sort by “Strongest evidence” to see the best-evidenced cases first.",
  "The line under the title shows when ApolloSG last ran a check or discovered a threat.",
] };

// ── Source icon mapping ──────────────────────────────────────────────────────

function sourceIcon(cat: string, meta?: SourceMetadata | null) {
  const t = meta?.type ?? cat;
  switch (t) {
    case "email": return { Icon: Mail, bg: "rgba(220,38,38,0.1)", fg: "#DC2626", label: "Email" };
    case "text": case "message": return { Icon: MessageSquare, bg: "rgba(16,185,129,0.1)", fg: "#10B981", label: "SMS" };
    case "screenshot": return { Icon: Camera, bg: "rgba(139,92,246,0.1)", fg: "#8B5CF6", label: "Screenshot" };
    case "link": return { Icon: Link2, bg: "rgba(107,114,128,0.1)", fg: "#6B7280", label: "Link Check" };
    case "website": return { Icon: Globe, bg: "rgba(220,38,38,0.1)", fg: "#DC2626", label: "Website" };
    case "call": return { Icon: Phone, bg: "rgba(217,119,6,0.1)", fg: "#D97706", label: "Call" };
    case "file": return { Icon: FileText, bg: "rgba(220,38,38,0.1)", fg: "#DC2626", label: "File" };
    case "app": return { Icon: Smartphone, bg: "rgba(16,185,129,0.1)", fg: "#065F46", label: "App" };
    case "device": case "network": return { Icon: Shield, bg: "rgba(220,38,38,0.1)", fg: "#991B1B", label: "Device" };
    case "account": return { Icon: Shield, bg: "rgba(217,119,6,0.1)", fg: "#92400E", label: "Account" };
    default: return { Icon: Shield, bg: "rgba(107,114,128,0.1)", fg: "#374151", label: "Security" };
  }
}


// ── Filter types ─────────────────────────────────────────────────────────────

type FilterKey = "all" | "investigating" | "blocked" | "resolved" | "no_threat";
const FILTERS: { key: FilterKey; label: string; matchStatuses: ThreatCaseStatus[] }[] = [
  { key: "all", label: "All", matchStatuses: [] },
  { key: "investigating", label: "Investigating", matchStatuses: ["investigating"] },
  { key: "blocked", label: "Blocked", matchStatuses: ["blocked"] },
  { key: "resolved", label: "Resolved", matchStatuses: ["resolved"] },
  { key: "no_threat", label: "No threat", matchStatuses: ["no_threat"] },
];

type SortOrder = "latest" | "oldest" | "strongest";
const SORT_LABEL: Record<SortOrder, string> = { latest: "Latest first", oldest: "Oldest first", strongest: "Strongest evidence" };
const NEXT_SORT: Record<SortOrder, SortOrder> = { latest: "oldest", oldest: "strongest", strongest: "latest" };
/** A case's evidence strength as a share of the strongest its kind can have (0 when it has no profile). */
const strengthOf = (e: PatrolEvent) => {
  if (!e.evidence_profile) return 0;
  const { rank, max } = evidenceStrength(e.evidence_profile);
  return rank / max;
};

// ── Styles ───────────────────────────────────────────────────────────────────

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  // Dark header
  headerBg: { backgroundColor: c.navyDeep, paddingBottom: spacing.md },
  headerTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg },
  headerBrand: { fontFamily: fonts.displayBold, fontSize: 22, color: "#FFFFFF" },
  headerTagline: { fontFamily: fonts.text, fontSize: 13, color: "rgba(255,255,255,0.6)" },
  headerIcons: { flexDirection: "row", gap: spacing.md },
  headerIconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.1)" },
  // Title section
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.xs, gap: 2 },
  titleText: { fontFamily: fonts.displayBold, fontSize: 28, color: c.onSurface },
  subtitleText: { fontFamily: fonts.text, fontSize: 15, color: c.onSurfaceSecondary, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  // Controls row (filter dropdown + sort)
  controlsRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingBottom: spacing.md, gap: spacing.sm },
  filterBtn: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary, flex: 1 },
  filterBtnText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, flex: 1 },
  // Sort control
  sortBtn: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  sortText: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurface },
  // Filter dropdown
  filterDropdown: { marginHorizontal: spacing.lg, marginBottom: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary, overflow: "hidden" },
  filterOption: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.md, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.divider },
  filterOptionActive: { backgroundColor: c.brandPrimary },
  filterOptionText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  filterOptionTextActive: { color: "#FFFFFF", fontFamily: fonts.textSemibold },
  filterOptionCount: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  // Threat card — the Home card shape: compact meta row, full-width words, action bottom right.
  card: { marginHorizontal: spacing.lg, marginBottom: spacing.md, borderRadius: radius.lg, padding: spacing.lg, backgroundColor: c.surfaceSecondary, borderWidth: 0.25, borderColor: c.border, gap: 2 },
  linksRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.lg, paddingHorizontal: spacing.xl },
  historyLink: { flexDirection: "row", alignItems: "center", gap: spacing.xs, alignSelf: "flex-start", minHeight: 44, paddingVertical: spacing.sm },
  historyLinkText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brandPrimary },
  cardTopRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  cardWords: { gap: 2, marginTop: 2 },
  cardTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, lineHeight: 20 },
  cardSubtitle: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary, lineHeight: 18 },
  cardMeta: { flex: 1, fontFamily: fonts.text, fontSize: 12, color: c.muted },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, marginTop: 2 },
  cardAction: { flexDirection: "row", alignItems: "center", gap: 4 },
  cardActionText: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.brand },
  cardCaseId: { fontFamily: fonts.text, fontSize: 11, color: c.muted },
  // Status pill
  statusPill: { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill },
  statusPillText: { fontFamily: fonts.textSemibold, fontSize: 11 },
  sampleRow: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  // Empty state
  emptyText: { fontFamily: fonts.text, fontSize: 15, color: c.muted, textAlign: "center", paddingVertical: spacing.xl * 2, paddingHorizontal: spacing.xl },
}));

// ── Threat Card ──────────────────────────────────────────────────────────────

function ThreatCard({ event, isNew, onPress, selecting = false, selected = false }: {
  event: PatrolEvent; isNew: boolean; onPress: () => void; selecting?: boolean; selected?: boolean;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const status = threatCaseStatus(event);
  const si = sourceIcon(event.category, event.source_metadata);
  const IconEl = si.Icon;
  const kept = useKeptIdentifiers(event);
  const brief = eventBrief(event, new Date(), kept, "card");
  const statusColor = STATUS_COLORS[status];

  return (
    <Pressable style={({ pressed }) => [s.card, selected ? { borderColor: colors.brand, borderWidth: 2 } : null, { opacity: pressed ? 0.85 : 1 }]} onPress={onPress}
      accessibilityRole={selecting ? "checkbox" : "button"} accessibilityState={selecting ? { checked: selected } : undefined} testID={`threat-card-${event.event_id}`}>
      {/* Same shape as the Home cards: icon, time and status on one compact row, the words beneath
          at full card width, and the action at the bottom right. */}
      <View style={s.cardTopRow}>
        {selecting ? <SelectBox selected={selected} testID={`threat-card-${event.event_id}-select`} /> : null}
        <View style={[s.cardIcon, { backgroundColor: si.bg }]}>
          <IconEl size={16} color={si.fg} />
        </View>
        <Text style={s.cardMeta} numberOfLines={1} testID={`threat-card-${event.event_id}-meta`}>
          {si.label} · {formatDateTime(event.occurred_at)}
        </Text>
        {isNew ? <NewBadge testID={`threat-card-${event.event_id}-new`} /> : null}
        {isSampleCheck(event) ? <Pill compact label="Sample Check" testID={`threat-card-${event.event_id}-sample`} /> : isSimulated(event) ? <Pill compact label="Simulated" testID={`threat-card-${event.event_id}-simulated`} /> : null}
        <View style={[s.statusPill, { backgroundColor: statusColor.bg }]}>
          <Text style={[s.statusPillText, { color: statusColor.text }]}>{STATUS_LABELS[status]}</Text>
        </View>
      </View>
      <View style={s.cardWords}>
        <Text style={s.cardTitle} numberOfLines={4}>{brief.line1}</Text>
        <Text style={s.cardSubtitle} numberOfLines={3}>{brief.line2}</Text>
      </View>
      {event.evidence_profile ? <EvidenceBadge profile={event.evidence_profile} testID={`threat-card-${event.event_id}-evidence`} /> : null}
      <SettledByBadge event={event} testID={`threat-card-${event.event_id}-settled`} />
      <View style={s.cardFooter}>
        <Text style={s.cardCaseId}>{threatCaseId(event)}</Text>
        {selecting ? null : (
          <View style={s.cardAction}>
            <Text style={s.cardActionText}>View threat</Text>
            <ChevronRight size={14} color={colors.brand} />
          </View>
        )}
      </View>
    </Pressable>
  );
}

// ── Preview samples ─────────────────────────────────────────────────────────
// Each kind opens its own gate screen with `sample`, and that screen runs the sample through its real check.
type SampleKind = "message" | "email" | "link" | "file" | "call" | "app";
const SAMPLE_KINDS: Record<SampleKind, { label: string; gate: string; path: "/message" | "/email" | "/check" | "/file" | "/call-guard" | "/app-check"; items: () => SourceChoice[] }> = {
  message: { label: "Messages", gate: "Text Gate", path: "/message",
    items: () => simulation.texts.map((m) => ({ id: m.id, primary: m.sender, secondary: m.text, meta: m.probes })) },
  email: { label: "Emails", gate: "Email Gate", path: "/email",
    items: () => simulation.emails.map((x) => ({ id: x.id, primary: x.subject, secondary: x.from, meta: x.probes })) },
  link: { label: "Links", gate: "Link Gate", path: "/check",
    items: () => simulation.links.map((x) => ({ id: x.id, primary: x.url, meta: x.probes })) },
  file: { label: "Files", gate: "File Gate", path: "/file",
    items: () => simulation.files.map((f) => ({ id: f.id, primary: f.name, secondary: f.mime, meta: f.probes })) },
  call: { label: "Calls", gate: "Call Gate", path: "/call-guard",
    items: () => simulation.calls.map((c) => ({ id: c.id, primary: c.number, secondary: c.name ?? undefined, meta: c.probes })) },
  app: { label: "Apps", gate: "App Gate", path: "/app-check",
    items: () => simulation.apps.map((a) => ({ id: a.id, primary: a.appName, secondary: `${a.developer} · ${a.packageId}`, meta: a.probes })) },
};

// ── Main Screen ──────────────────────────────────────────────────────────────

export default function ThreatsScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { events, lastVerifiedAt, refreshCases, deleteCases, showToast } = useApollo();
  const isNew = useNewCases();
  // Pull down to fetch the newest cases now.
  const [pulling, setPulling] = useState(false);
  const onPull = () => {
    setPulling(true);
    void refreshCases().catch(() => undefined).finally(() => setPulling(false));
  };
  // Preview only: which kind of sample is being chosen (the kind sheet opens first).
  const [kindPicker, setKindPicker] = useState(false);
  const [sampleKind, setSampleKind] = useState<SampleKind | null>(null);
  // Most recent moment Apollo ran any check or discovered/updated a threat.
  const lastActivityAt = useMemo(() => {
    const times = [lastVerifiedAt, ...events.flatMap((e) => [e.occurred_at, e.detection_updated_at])]
      .map((t) => (t ? Date.parse(t) : NaN)).filter((t) => !Number.isNaN(t));
    return times.length ? new Date(Math.max(...times)).toISOString() : null;
  }, [events, lastVerifiedAt]);

  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [filterOpen, setFilterOpen] = useState(false);
  const [sortOrder, setSortOrder] = useState<SortOrder>("latest");

  // One row per Threat Case (same case = same list entry), the latest record of each.
  const threatCases = useMemo(() => allThreatCases(events), [events]);

  // Compute status counts for filter chips
  const statusCounts = useMemo(() => {
    const counts: Record<FilterKey, number> = { all: 0, investigating: 0, blocked: 0, resolved: 0, no_threat: 0 };
    for (const event of threatCases) {
      const status = threatCaseStatus(event);
      counts.all++;
      if (status === "investigating") counts.investigating++;
      else if (status === "blocked") counts.blocked++;
      else if (status === "resolved") counts.resolved++;
      else if (status === "no_threat") counts.no_threat++;
    }
    return counts;
  }, [threatCases]);

  // Filter + sort
  const filtered = useMemo(() => {
    const filter = FILTERS.find((f) => f.key === activeFilter)!;
    let list = threatCases;
    if (filter.matchStatuses.length > 0) {
      list = list.filter((e) => filter.matchStatuses.includes(threatCaseStatus(e)));
    }
    list = [...list].sort((a, b) => {
      const ta = new Date(a.occurred_at).getTime();
      const tb = new Date(b.occurred_at).getTime();
      if (sortOrder === "strongest") return strengthOf(b) - strengthOf(a) || tb - ta;
      return sortOrder === "latest" ? tb - ta : ta - tb;
    });
    return list;
  }, [threatCases, activeFilter, sortOrder]);

  const toggleSort = () => setSortOrder((prev) => NEXT_SORT[prev]);

  // Choosing cases to delete: each row is a whole case; "Select all" means every case the filter shows.
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const chosen = useMemo(() => filtered.filter((e) => selected.has(e.event_id)), [filtered, selected]);
  const records = useMemo(() => deletionSet(events, chosen, true).eventIds.length, [events, chosen]);
  const stopSelecting = () => { setSelecting(false); setSelected(new Set()); setConfirming(false); };
  const toggle = (id: string) => setSelected((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const toggleAll = () => setSelected(chosen.length === filtered.length ? new Set() : new Set(filtered.map((e) => e.event_id)));
  const confirmDelete = async () => {
    setDeleting(true);
    try {
      const { ok } = await deleteCases(chosen, true);
      if (ok) { showToast(`Deleted ${countLabel(chosen.length, "case")} from this phone and ApolloSG's server.`, "neutral"); stopSelecting(); }
      else setConfirming(false);
    } finally { setDeleting(false); }
  };

  // Preview only: the chosen sample opens its own gate screen, which runs it through that gate's real check and
  // shows production's own result. Apollo's rules decide whether a Threat Case opens; nothing is pre-made.
  const runSample = (kind: SampleKind, id: string) => {
    setSampleKind(null);
    router.push({ pathname: SAMPLE_KINDS[kind].path, params: { sample: id } });
  };

  return (
    <View style={s.root} testID="threats-screen">
      {/* Title */}
      <View style={[s.titleRow, { paddingTop: insets.top + spacing.sm }]}>
        <View style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.md }}>
          <HeaderIconTile icon={ShieldAlert} color={colors.barking} fg={colors.onBrand} testID="threats-title-icon" />
          <Text style={[s.titleText, { flexShrink: 1 }]}>Threats</Text>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 2 }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Search your open cases"
            onPress={() => router.push("/patrol/search")}
            hitSlop={6}
            style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}
            testID="threats-search"
          >
            <Search size={22} color={colors.onSurface} />
          </Pressable>
          <AlertsButton testID="threats-alerts" />
          <InfoButton info={THREATS_INFO} testID="threats-info" />
          <AppMenuButton testID="threats-menu" />
        </View>
      </View>
      <Text style={s.subtitleText} testID="threats-last-check">
        {lastActivityAt ? `Apollo last checked ${new Date(lastActivityAt).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}` : "Apollo hasn't run a check yet"}
      </Text>

      {/* Threats lists one row per case; the full record as it happened lives in patrol history. Alerts shared by
          family live on the Family screen. */}
      <View style={s.linksRow}>
        <Pressable
          testID="threats-history-link"
          accessibilityRole="button"
          accessibilityLabel="Open patrol history — everything ApolloSG has filed, newest first"
          onPress={() => router.push("/patrol/history")}
          style={({ pressed }) => [s.historyLink, { opacity: pressed ? 0.7 : 1 }]}
        >
          <Clock size={16} color={colors.brandPrimary} />
          <Text style={s.historyLinkText}>Patrol history</Text>
          <ChevronRight size={16} color={colors.brandPrimary} />
        </Pressable>
        <Pressable
          testID="threats-family-alerts-link"
          accessibilityRole="button"
          accessibilityLabel="Open family alerts — alerts from the people you watch"
          onPress={() => router.push("/family?focus=alerts")}
          style={({ pressed }) => [s.historyLink, { opacity: pressed ? 0.7 : 1 }]}
        >
          <UsersRound size={16} color={colors.brandPrimary} />
          <Text style={s.historyLinkText}>Family alerts</Text>
          <ChevronRight size={16} color={colors.brandPrimary} />
        </Pressable>
      </View>

      {simulation.included ? (
        <View style={s.sampleRow}>
          <Button
            testID="threats-sample-check"
            variant="ghost"
            label="Try a sample check"
            onPress={() => setKindPicker(true)}
          />
        </View>
      ) : null}

      {/* Filter + sort row */}
      <View style={s.controlsRow}>
        <Pressable style={s.filterBtn} onPress={() => setFilterOpen(!filterOpen)} accessibilityRole="button" testID="threats-filter-btn">
          <Text style={s.filterBtnText}>
            {FILTERS.find((f) => f.key === activeFilter)!.label} ({statusCounts[activeFilter]})
          </Text>
          <ChevronDown size={16} color={colors.onSurface} />
        </Pressable>
        <Pressable style={s.sortBtn} onPress={toggleSort} accessibilityRole="button" accessibilityLabel={`Sort: ${SORT_LABEL[sortOrder]}. Tap to change.`} testID="threats-sort-btn">
          <Text style={s.sortText}>{SORT_LABEL[sortOrder]}</Text>
          <ChevronDown size={16} color={colors.onSurface} />
        </Pressable>
        {!selecting && threatCases.length ? (
          <Pressable style={s.sortBtn} onPress={() => { setFilterOpen(false); setSelecting(true); }} accessibilityRole="button"
            accessibilityLabel="Choose cases to delete" testID="threats-select">
            <Text style={s.sortText}>Select</Text>
          </Pressable>
        ) : null}
      </View>
      {selecting ? (
        <SelectionBar count={chosen.length} total={filtered.length} onToggleAll={toggleAll} onCancel={stopSelecting}
          onDelete={() => setConfirming(true)} testID="threats-selection" />
      ) : null}

      {/* Filter dropdown */}
      {filterOpen ? (
        <View style={s.filterDropdown} testID="threats-filter-dropdown">
          {FILTERS.map(({ key, label }) => {
            const isActive = activeFilter === key;
            const count = statusCounts[key];
            return (
              <Pressable
                key={key}
                style={[s.filterOption, isActive && s.filterOptionActive]}
                onPress={() => { setActiveFilter(key); setFilterOpen(false); }}
                accessibilityRole="button"
                accessibilityState={{ selected: isActive }}
                testID={`threats-filter-${key}`}
              >
                <Text style={[s.filterOptionText, isActive && s.filterOptionTextActive]}>
                  {label}
                </Text>
                <Text style={[s.filterOptionCount, isActive && s.filterOptionTextActive]}>
                  {count}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}

      {/* Threat list */}
      <FlatList
        data={filtered}
        keyExtractor={(item) => item.event_id}
        extraData={selected}
        renderItem={({ item }) => (
          <ThreatCard
            event={item}
            isNew={isNew(item)}
            selecting={selecting}
            selected={selected.has(item.event_id)}
            onPress={() => (selecting ? toggle(item.event_id) : router.push(`/patrol/${item.event_id}`))}
          />
        )}
        refreshControl={<RefreshControl refreshing={pulling} onRefresh={onPull} tintColor={colors.brand} colors={[colors.brand]} />}
        ListEmptyComponent={
          <Text style={s.emptyText}>
            {activeFilter === "all"
              ? "No threats detected yet. Apollo is watching."
              : `No ${FILTERS.find((f) => f.key === activeFilter)?.label.toLowerCase()} threats.`}
          </Text>
        }
        contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }}
        testID="threats-list"
      />

      <DeleteConfirmSheet visible={confirming} count={chosen.length} records={records} noun="case" busy={deleting}
        onConfirm={() => void confirmDelete()} onClose={() => setConfirming(false)} testID="threats-delete-confirm" />

      <SourcePickerSheet
        visible={kindPicker}
        title="Try a sample check"
        note="Pick what to check. Each sample goes through that gate's real check, exactly as in production."
        preview
        items={(Object.keys(SAMPLE_KINDS) as SampleKind[]).map((kind) => ({
          id: kind, primary: SAMPLE_KINDS[kind].label, secondary: SAMPLE_KINDS[kind].gate,
        }))}
        emptyText="There are no samples here."
        onSelect={(id: string) => { setKindPicker(false); setSampleKind(id as SampleKind); }}
        onClose={() => setKindPicker(false)}
        testID="threats-sample-kinds"
      />
      <SourcePickerSheet
        visible={!!sampleKind}
        title={sampleKind ? SAMPLE_KINDS[sampleKind].label : ""}
        note="Apollo runs the real check on whichever one you pick. A Threat Case opens only if Apollo's rules find one."
        preview
        items={sampleKind ? SAMPLE_KINDS[sampleKind].items() : []}
        emptyText="There are no samples to choose from here."
        onSelect={(id: string) => { if (sampleKind) runSample(sampleKind, id); }}
        onClose={() => setSampleKind(null)}
        testID="threats-sample-picker"
      />
    </View>
  );
}

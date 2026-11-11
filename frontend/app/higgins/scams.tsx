import { router, useFocusEffect, useSegments } from "expo-router";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChildScreenHeader } from "@/src/components/ChildScreenHeader";
import { HeaderIconTile } from "@/src/components/HeaderIconTile";
import { RootScreenHeader } from "@/src/components/RootScreenHeader";
import Megaphone from "lucide-react-native/icons/megaphone";
import { Body, Button, Card, Pill, toneColor, toneTint } from "@/src/components/ui";
import { alertFreshness } from "@/src/domain/alertFreshness";
import { governmentScams, type GovernmentAlert } from "@/src/higgins/hubClient";
import { getNewSevereAlertCount, markScamAlertsSeen } from "@/src/higgins/scamAlertBadge";
import { alertIcon, alertTime, appliesHere, familyScamAlerts, homeRegion, loadRegionFilter, openScamAlert, rememberAlerts, saveRegionFilter, SEVERITY_RANK, SEVERITY_TONE, severityLabel, type SharedScamAlert } from "@/src/higgins/scamAlertUi";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

type RegionFilter = "ALL" | "AU" | "US" | "UK" | "EU" | "GLOBAL";
const REGIONS: { id: RegionFilter; label: string }[] = [
  { id: "ALL", label: "All" }, { id: "AU", label: "Australia" }, { id: "US", label: "USA" },
  { id: "UK", label: "UK" }, { id: "EU", label: "EU" }, { id: "GLOBAL", label: "Global" },
];
const HOME = homeRegion();
// "All" shows every alert regardless of region. Individual region chips narrow by source or applicability.
const regionMatch = (a: GovernmentAlert, f: RegionFilter) =>
  f === "ALL" ? true
  : f === "AU" ? a.region === "AU" || a.australianRelevance === "confirmed" || a.appliesIn === "everywhere"
  : f === "GLOBAL" ? a.appliesIn === "everywhere" || a.appliesIn === "everywhere"
  : a.region === f;

type SortMode = "latest" | "severity";
const COMPACT_WIDTH = 430; // below this the six region chips overflow the screen
const SORT_LABEL: Record<SortMode, string> = { latest: "Latest first", severity: "Highest severity" };

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  list: { paddingHorizontal: spacing.xl, gap: spacing.sm },
  subtitle: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary },
  chip: { paddingHorizontal: spacing.md, minHeight: 36, justifyContent: "center", borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  chipOn: { backgroundColor: c.brand, borderColor: c.brand },
  chipText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  chipTextOn: { color: "#FFFFFF" },
  toolbar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dropBtn: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingHorizontal: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  dropBtnText: { flex: 1, fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  dropList: { borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary, overflow: "hidden" },
  dropOption: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44, paddingHorizontal: spacing.md, borderBottomWidth: 1, borderBottomColor: c.divider },
  sort: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: spacing.xs },
  sortText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  // Half the old 44pt badge: it marks the severity, it doesn't lead the card.
  icon: { width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center" },
  titleRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  rowBody: { flex: 1, gap: 4 },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  title: { fontFamily: fonts.displayBold, fontSize: 15, lineHeight: 20, color: c.onSurface },
  meta: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary },
  sectionHeading: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface, marginTop: spacing.md },
}));

function AlertRow({ item, index }: { item: GovernmentAlert; index: number }) {
  const s = useStyles(); const { colors } = useTheme();
  const tone = SEVERITY_TONE[item.severity]; const Icon = alertIcon(item);
  return (
    <Pressable
      testID={`higgins-scam-${index}`} accessibilityRole="button" accessibilityLabel={`${severityLabel(item.severity)} alert: ${item.title}`}
      onPress={() => router.push({ pathname: "/higgins/scam/[id]", params: { id: item.url } })}
      style={({ pressed }) => [{ opacity: pressed ? 0.8 : 1 }]}
    >
      <Card style={[s.row, { padding: spacing.md }]}>
        <View style={s.rowBody}>
          <View style={s.titleRow}>
            <Text style={[s.title, { flex: 1 }]} numberOfLines={2}>{item.title}</Text>
            <View style={[s.icon, { backgroundColor: toneTint(colors, tone) }]}><Icon size={11} color={toneColor(colors, tone)} /></View>
          </View>
          <View style={s.pills}>
            <Pill compact testID={`higgins-scam-${index}-severity`} tone={tone} label={severityLabel(item.severity)} />
            <Pill compact tone="neutral" label={item.regionLabel} />
          </View>
          <Text style={s.meta} numberOfLines={1} testID={`higgins-scam-${index}-source-name`}>{`${item.source} · ${item.dateLabel}`}</Text>
        </View>
        <ChevronRight size={20} color={colors.onSurfaceSecondary} />
      </Card>
    </Pressable>
  );
}

export default function GovernmentScamsScreen() {
  const s = useStyles(); const { colors } = useTheme(); const insets = useSafeAreaInsets();
  const [alerts, setAlerts] = useState<GovernmentAlert[]>([]); const [emerging, setEmerging] = useState<GovernmentAlert[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [coverage, setCoverage] = useState(""); const [lastSourced, setLastSourced] = useState<string | null>(null);
  const [loading, setLoading] = useState(true); const [refreshing, setRefreshing] = useState(false); const [error, setError] = useState(false);
  const [region, setRegion] = useState<RegionFilter>("ALL"); const [sort, setSort] = useState<SortMode>("latest");
  const isTab = (useSegments() as string[]).includes("(tabs)");
  const { deviceId } = useApollo();
  const [fromFamily, setFromFamily] = useState<SharedScamAlert[]>([]);
  // Remember the last region the person chose so Scam Alerts reopens on it.
  useEffect(() => { void loadRegionFilter().then((v) => { if (v && REGIONS.some((r) => r.id === v)) setRegion(v as RegionFilter); }); }, []);
  const chooseRegion = (id: RegionFilter) => { setRegion(id); void saveRegionFilter(id); };
  // Smaller phones can't fit all six region chips, so they get a dropdown list instead.
  const compact = useWindowDimensions().width < COMPACT_WIDTH;
  const [regionOpen, setRegionOpen] = useState(false);
  const regionCount = (id: RegionFilter) => alerts.filter((a) => regionMatch(a, id)).length + emerging.filter((a) => regionMatch(a, id)).length;

  const load = (pull = false) => {
    if (pull) setRefreshing(true); else setLoading(true);
    setError(false);
    if (deviceId) void familyScamAlerts(deviceId).then(setFromFamily).catch(() => undefined);
    void governmentScams().then((result) => {
      rememberAlerts([...result.alerts, ...result.emerging]);
      // Open and showing these: they no longer count on the Scam Alerts tab.
      void markScamAlertsSeen([...result.alerts, ...result.emerging]);
      setAlerts(result.alerts); setEmerging(result.emerging); setPendingCount(result.pendingCount);
      setCoverage(result.coverage); setLastSourced(result.lastSourcedAt);
    }).catch(() => setError(true)).finally(() => { setLoading(false); setRefreshing(false); });
  };
  useEffect(() => load(), [deviceId]); // eslint-disable-line react-hooks/exhaustive-deps
  // Coming back to Scam Alerts while the tab shows a count: load the new alerts, which also clears the count.
  useFocusEffect(useCallback(() => { if (getNewSevereAlertCount() > 0) load(); }, [])); // eslint-disable-line react-hooks/exhaustive-deps

  const sourced = useMemo(() => alertFreshness(lastSourced), [lastSourced]);
  const sourcedLabel = sourced.exact
    ? `${sourced.label} · Official sources read ${sourced.exact}`
    : sourced.label;
  const arrange = (list: GovernmentAlert[]) => list.filter((a) => regionMatch(a, region)).sort((a, b) =>
    sort === "severity" ? SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || alertTime(b) - alertTime(a) : alertTime(b) - alertTime(a));
  const shown = useMemo(() => arrange(alerts), [alerts, region, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  const shownEmerging = useMemo(() => arrange(emerging), [emerging, region, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  // Count alerts specific to another country (not global/everywhere/home). Shown as an informational note on region filters.
  const otherCountryCount = useMemo(() => [...alerts, ...emerging].filter((a) => !appliesHere(a, HOME)).length, [alerts, emerging]);
  const info = { title: "About Scam Alerts", body: [coverage || "Specific scam campaigns reported by recognised government and official cyber-authority sources (Australia, USA, UK, EU), each read and explained from the source itself.", "Emerging patterns are techniques appearing across several reports with no single named campaign yet."] };
  const titleIcon = <HeaderIconTile icon={Megaphone} color={colors.growling} fg={colors.onBrand} testID="higgins-scams-title-icon" />;

  return (
    <View style={s.root} testID="higgins-scams-screen">
      {isTab
        ? <View style={{ paddingTop: insets.top + spacing.md }}><RootScreenHeader title="Scam Alerts" testID="higgins-scams-header" info={info} leading={titleIcon} /></View>
        : <ChildScreenHeader title="Scam Alerts" testID="higgins-scams-header" info={info} leading={titleIcon} />}
      <FlatList
        testID="higgins-scams-list" data={shown} keyExtractor={(item) => item.url}
        contentContainerStyle={[s.list, { paddingBottom: insets.bottom + spacing.xl }]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={colors.brand} />}
        ListHeaderComponent={
          <View style={{ gap: spacing.sm, marginBottom: spacing.xs }}>
            <Text style={s.subtitle} testID="higgins-scams-sourced">{sourcedLabel}{sourced.stale && sourced.exact ? "  ·  ApolloSG is still trying to refresh" : ""}{pendingCount > 0 ? `  ·  Reading ${pendingCount} new…` : ""}</Text>
            {compact ? (
              <View style={{ gap: spacing.xs }}>
                <Pressable testID="scam-filter-dropdown-btn" accessibilityRole="button" accessibilityLabel={`Region: ${REGIONS.find((r) => r.id === region)!.label}`} accessibilityState={{ expanded: regionOpen }} onPress={() => setRegionOpen(!regionOpen)} style={s.dropBtn}>
                  <Text style={s.dropBtnText}>{`Region: ${REGIONS.find((r) => r.id === region)!.label} (${regionCount(region)})`}</Text>
                  <ChevronDown size={16} color={colors.onSurface} />
                </Pressable>
                {regionOpen ? (
                  <View style={s.dropList} testID="scam-filter-dropdown">
                    {REGIONS.map((r) => {
                      const on = region === r.id;
                      return (
                        <Pressable key={r.id} testID={`scam-filter-${r.id}`} accessibilityRole="button" accessibilityState={{ selected: on }} onPress={() => { chooseRegion(r.id); setRegionOpen(false); }} style={[s.dropOption, on && s.chipOn]}>
                          <Text style={[s.chipText, on && s.chipTextOn]}>{r.label}</Text>
                          <Text style={[s.meta, on && s.chipTextOn]}>{regionCount(r.id)}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                ) : null}
              </View>
            ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm, paddingVertical: 2 }}>
              {REGIONS.map((r) => {
                const on = region === r.id;
                return (
                  <Pressable key={r.id} testID={`scam-filter-${r.id}`} accessibilityRole="button" accessibilityState={{ selected: on }} onPress={() => chooseRegion(r.id)} style={[s.chip, on && s.chipOn]}>
                    <Text style={[s.chipText, on && s.chipTextOn]}>{r.label}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
            )}
            {fromFamily.length > 0 ? (
              <View style={{ gap: spacing.sm }} testID="higgins-scams-family">
                <Text style={s.sectionHeading}>Sent by your family</Text>
                {fromFamily.slice(0, 3).map((f, i) => (
                  <Pressable key={`${f.url}-${f.from_label}`} testID={`higgins-scams-family-${i}`} accessibilityRole="button" accessibilityLabel={`${f.from_label} sent: ${f.title}`} onPress={() => openScamAlert(router, f.url)} style={({ pressed }) => [{ opacity: pressed ? 0.8 : 1 }]}>
                    <Card style={[s.row, { padding: spacing.md }]}>
                      <View style={s.rowBody}>
                        <Text style={s.title} numberOfLines={2}>{f.title}</Text>
                        <View style={s.pills}><Pill compact tone={SEVERITY_TONE[f.severity]} label={severityLabel(f.severity)} /><Pill compact tone="neutral" label={`From ${f.from_label}`} /></View>
                        <Text style={s.meta} numberOfLines={1}>{`${f.source} · ${f.date_label}`}</Text>
                      </View>
                      <ChevronRight size={20} color={colors.onSurfaceSecondary} />
                    </Card>
                  </Pressable>
                ))}
                <Text style={s.sectionHeading}>All alerts</Text>
              </View>
            ) : null}
            <View style={s.toolbar}>
              <Text style={s.meta}>{`${shown.length + shownEmerging.length} alert${(shown.length + shownEmerging.length) === 1 ? "" : "s"}`}</Text>
              <Pressable testID="scam-sort" accessibilityRole="button" accessibilityLabel={`Sort: ${SORT_LABEL[sort]}`} accessibilityHint="Switches between latest and highest severity" onPress={() => setSort(sort === "latest" ? "severity" : "latest")} style={s.sort}>
                <Text style={s.sortText}>{SORT_LABEL[sort]}</Text><ChevronDown size={16} color={colors.onSurface} />
              </Pressable>
            </View>
            {region !== "ALL" && otherCountryCount > 0 ? (
              <Text style={s.meta} testID="higgins-scams-local-note">
                {`Showing ${regionCount(region)} of ${alerts.length + emerging.length} total alerts. Switch to All to see everything.`}
              </Text>
            ) : null}
          </View>
        }
        renderItem={({ item, index }) => <AlertRow item={item} index={index} />}
        ListEmptyComponent={loading ? <ActivityIndicator testID="higgins-scams-loading" color={colors.brand} /> : error ? (
          <Card testID="higgins-scams-error"><Body>Official guidance could not be loaded. ApolloSG will not substitute unrecognised sources.</Body><Button testID="higgins-scams-retry" label="Try again" onPress={() => load()} /></Card>
        ) : (
          <Card testID="higgins-scams-empty"><Body>{pendingCount > 0 ? "ApolloSG is still reading the latest official reports. Specific alerts will appear here once their facts are verified." : region === "ALL" ? "No specific scam campaigns are being reported by the configured official sources right now. This does not mean there are no new scams." : "No alerts for this region right now."}</Body></Card>
        )}
        ListFooterComponent={shownEmerging.length > 0 ? (
          <View style={{ gap: spacing.sm }}>
            <Text style={s.sectionHeading} testID="higgins-scams-emerging-heading">Emerging patterns</Text>
            <Text style={s.meta}>Techniques showing up across several reports. No single named campaign yet.</Text>
            {shownEmerging.map((item, i) => <AlertRow key={item.url} item={item} index={1000 + i} />)}
          </View>
        ) : null}
      />
    </View>
  );
}

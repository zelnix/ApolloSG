// Evidence tab — the original source, shown the way it arrived.
//
// One card per case: the artefact itself (email / screenshot / message / chat / post), a toggle
// between the original kept on this device and the exact copy that was sent for investigation, the
// captured headers, and the provenance. Everything on screen is captured material; nothing about
// the source app is reconstructed.
import * as Clipboard from "expo-clipboard";
import Camera from "lucide-react-native/icons/camera";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import CopyIcon from "lucide-react-native/icons/copy";
import FileText from "lucide-react-native/icons/file-text";
import Globe from "lucide-react-native/icons/globe";
import Info from "lucide-react-native/icons/info";
import Mail from "lucide-react-native/icons/mail";
import Maximize2 from "lucide-react-native/icons/maximize-2";
import MessageCircle from "lucide-react-native/icons/message-circle";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import Share2 from "lucide-react-native/icons/share-2";
import Smartphone from "lucide-react-native/icons/smartphone";
import Trash2 from "lucide-react-native/icons/trash";
import X from "lucide-react-native/icons/x";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Image, Modal, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ConversationArtefact, EmailArtefact, FieldRows, PostArtefact, ScreenshotArtefact, useArtefactStyles, type ArtefactImage, type LayoutProps } from "./ArtefactLayouts";
import { InertEmailView } from "./InertEmailView";
import { InfoButton } from "@/src/components/InfoButton";
import { Button } from "@/src/components/ui";
import { describeArtefact, describeRedaction, redactView, type EvidenceLayout } from "@/src/domain/evidencePresentation";
import { inertEmail, type InertEmail } from "@/src/domain/inertEmail";
import { phoneFindingLine, type EvidencePhoneResult } from "@/src/domain/phoneNumbers";
import { purposeLimitedUrl, redactInvestigationSecrets } from "@/src/domain/privacy";
import { readEmailBody } from "@/src/domain/triage/emailOriginal";
import { listImageEvidence, removeOriginal, subscribeImageEvidence, type ImageEvidenceRecord } from "@/src/store/imageEvidence";
import { readKeptOriginalEmail } from "@/src/store/originalEmail";
import { getCaseOriginal, originalSourceDeletedAt, subscribeOriginalSource, type OriginalSource } from "@/src/store/originalSource";
import { heldCopyDeletedNote } from "@/src/domain/heldCopies";
import { formatDateTime } from "@/src/domain/threatCase";
import { shareEvidencePack, type PackSummary } from "@/src/utils/evidencePack";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.lg, gap: spacing.md },

  header: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  iconWrap: { width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: c.navyTint },
  headerInfo: { flex: 1, gap: 2 },
  title: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface },
  subtitle: { fontFamily: fonts.text, fontSize: 12, color: c.muted },

  segmentRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  segments: { flex: 1, flexDirection: "row", backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: 3, gap: 3 },
  segment: { flex: 1, paddingVertical: 9, borderRadius: radius.sm, alignItems: "center" },
  segmentOn: { backgroundColor: c.navyTintStrong },
  segmentText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.muted },
  segmentTextOn: { fontFamily: fonts.textSemibold, color: c.onSurface },

  tabs: { flexDirection: "row", gap: spacing.sm },
  tab: { paddingHorizontal: spacing.lg, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  tabOn: { backgroundColor: c.brandPrimary },
  tabText: { fontFamily: fonts.textMedium, fontSize: 13, color: c.muted },
  tabTextOn: { color: c.onBrandPrimary, fontFamily: fonts.textSemibold },

  actions: { flexDirection: "row", gap: spacing.sm },
  action: { flex: 1 },

  detailsToggle: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: c.border },
  detailsTitle: { flex: 1, fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  details: { gap: spacing.sm, paddingBottom: spacing.sm },
  phones: { gap: 4, padding: spacing.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  phonesTitle: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  note: { fontFamily: fonts.text, fontSize: 12, lineHeight: 18, color: c.muted },
  confirm: { gap: spacing.sm, padding: spacing.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  confirmText: { fontFamily: fonts.textMedium, fontSize: 13, lineHeight: 19, color: c.onSurface },

  banner: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, borderRadius: radius.md, backgroundColor: c.navyTint },
  bannerInfo: { flex: 1, gap: 2 },
  bannerTitle: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  bannerBody: { fontFamily: fonts.text, fontSize: 12, lineHeight: 18, color: c.onSurfaceSecondary },

  modeNotice: { gap: 2, padding: spacing.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary, borderLeftWidth: 3, borderLeftColor: c.brandPrimary },
  modeNoticeTitle: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  modeNoticeBody: { fontFamily: fonts.text, fontSize: 12, lineHeight: 18, color: c.onSurfaceSecondary },

  viewer: { flex: 1, backgroundColor: "#000000" },
  viewerBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  viewerTitle: { flex: 1, fontFamily: fonts.textMedium, fontSize: 15, color: "#FFFFFF" },
  viewerClose: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  emailViewer: { flex: 1, backgroundColor: c.surface },
  emailViewerTitle: { flex: 1, fontFamily: fonts.textMedium, fontSize: 15, color: c.onSurface },
}));

const LAYOUT_ICON: Record<EvidenceLayout, React.ComponentType<{ size: number; color: string }>> = {
  email: Mail, screenshot: Camera, message: MessageSquare, chat: MessageCircle, post: Globe,
};
const KIND_ICON: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  call: Phone, file: FileText, app: Smartphone, device: Smartphone, network: Smartphone, link: Globe, website: Globe,
};

const SOURCE_INFO = {
  title: "Original Source",
  body: [
    "This is the material Apollo investigated, exactly as it was captured — not a summary and not anything ApolloSG wrote.",
    "Links, buttons, pictures, phone numbers and addresses in it look as they did, but touching them does nothing: nothing opens, dials, downloads or connects. Where each link really goes is listed under Details.",
    "It is kept on this device only. It is never uploaded for storage, and it is deleted when you delete this case or wipe ApolloSG's data.",
  ],
};

const MODE_INFO = {
  title: "Original, Redacted and Side by side",
  body: [
    "Original is the material as captured on this device. Nothing in it has been altered.",
    "Redacted is the exact copy that left this phone for the investigation. Passwords, PINs and verification codes are blacked out or replaced; the sender, the links and everything else are kept so the investigation has the real evidence.",
    "For screenshots, Side by side shows both pictures together so you can see exactly what was covered up before anything was sent.",
  ],
};

type Mode = "original" | "redacted" | "side";
type EmailTab = "email" | "headers" | "details";

const MODE_LABEL: Record<Mode, string> = { original: "Original", redacted: "Redacted", side: "Side by side" };

/** Notes about what was changed on the copy that was sent — facts from the evidence record. */
function imageNotes(r: ImageEvidenceRecord): string[] {
  const out: string[] = [];
  if (r.cropped) out.push("You cropped the image before sending.");
  if (!r.checked) out.push("On-device text recognition was unavailable, so nothing could be blacked out.");
  else if (r.redactedRegions > 0) out.push(`${r.redactedRegions} password, PIN or code area${r.redactedRegions === 1 ? " was" : "s were"} blacked out on the copy that was sent.`);
  else out.push("No passwords, PINs or codes were found, so nothing was blacked out.");
  if (r.originalRemovedAt) out.push("You removed the original from this device. The sent copy is kept with the case.");
  else out.push("The original is kept only on this device and was never uploaded.");
  return out;
}

export function EvidenceArtefactCard({ caseKeys, packTitle, packDate, packSummary, phones, onAvailable, showMissing = false, testID = "evidence-artefact" }: {
  /** Every key this case is known by — a threat case carries both its event id and its
   *  investigation id, and the original may have been filed under either. */
  caseKeys: (string | null | undefined)[];
  /** Title and date used if the person shares an evidence pack. */
  packTitle: string;
  packDate: string;
  packSummary?: PackSummary | null;
  /** Telephone/mobile numbers found in this material and what the reputation service returned. */
  phones?: EvidencePhoneResult[] | null;
  /** Reports whether a local original exists, so the screen can drop its server-side duplicate. */
  onAvailable?: (available: boolean) => void;
  /** Say so when this phone holds no original, rather than showing nothing (a Threat Case's Evidence tab). */
  showMissing?: boolean;
  testID?: string;
}) {
  const s = useStyles(); const a = useArtefactStyles(); const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [src, setSrc] = useState<OriginalSource | null | undefined>(undefined);
  const [records, setRecords] = useState<ImageEvidenceRecord[]>([]);
  const [mode, setMode] = useState<Mode>("original");
  const [tab, setTab] = useState<EmailTab>("email");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [full, setFull] = useState<ArtefactImage | null>(null);
  const [email, setEmail] = useState<InertEmail | null>(null);
  const [emailFull, setEmailFull] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [deletedAt, setDeletedAt] = useState<string | null>(null);
  const keyList = caseKeys.filter((k): k is string => !!k).join("|");

  useEffect(() => {
    const keys = keyList ? keyList.split("|") : [];
    const load = async () => {
      const found = await getCaseOriginal(keys).catch(() => null);
      if (found) { setSrc(found); setDeletedAt(null); return; }
      // Where ApolloSG's copy was deleted after its 24 hours, say so rather than showing nothing.
      let gone: string | null = null;
      for (const key of keys) { gone = gone ?? (await originalSourceDeletedAt(key).catch(() => null)); }
      setDeletedAt(gone);
      setSrc(null);
    };
    void load();
    return subscribeOriginalSource(() => void load());
  }, [keyList]);

  useEffect(() => {
    const keys = keyList ? keyList.split("|") : [];
    const load = async () => {
      const found = new Map<string, ImageEvidenceRecord>();
      for (const key of keys) {
        for (const r of await listImageEvidence(key).catch(() => [])) found.set(r.id, r);
      }
      setRecords([...found.values()]);
    };
    void load();
    return subscribeImageEvidence(() => void load());
  }, [keyList]);

  // An email's kept original (.eml / original source): its own HTML part, made inert, is how it is shown. Without
  // one (no HTML part, or only the text was kept) the email's text is shown instead.
  useEffect(() => {
    let live = true;
    void readKeptOriginalEmail(keyList ? keyList.split("|") : [])
      .then((raw) => (raw ? inertEmail(readEmailBody(raw)) : null))
      .catch(() => null)
      .then((found) => { if (live) setEmail(found); });
    return () => { live = false; };
  }, [keyList]);

  // An image-only case has no text original, but the picture kept on this device IS the original.
  const source = useMemo<OriginalSource | null>(
    () => src ?? (records.length ? { kind: "screenshot", capturedAt: records[0].createdAt, origin: "this_device" } : null),
    [src, records],
  );
  const view = useMemo(() => (source ? describeArtefact(source, records.length > 0) : null), [source, records.length]);
  useEffect(() => { if (src !== undefined) onAvailable?.(!!source); }, [src, source, onAvailable]);  const shown = useMemo(() => (view && mode === "redacted" ? redactView(view, redactInvestigationSecrets) : view), [view, mode]);

  const images: ArtefactImage[] = useMemo(() => records.flatMap((r) => {
    if (mode === "redacted") return [{ uri: r.sentUri, label: "Copy sent for investigation" }];
    if (mode === "side") {
      return [
        ...(r.originalUri ? [{ uri: r.originalUri, label: "Original on this device" }] : []),
        { uri: r.sentUri, label: "Copy sent for investigation" },
      ];
    }
    return r.originalUri ? [{ uri: r.originalUri, label: "Original on this device" }] : [];
  }), [records, mode]);

  const copyText = useCallback(() => {
    const parts = [shown?.subject, shown?.body, mode === "redacted" && source?.url ? purposeLimitedUrl(source.url) : source?.url].filter(Boolean);
    void Clipboard.setStringAsync(parts.join("\n\n")).then(() => setNote("Copied what is shown above.")).catch(() => setNote("ApolloSG couldn't copy that."));
  }, [shown, source, mode]);

  const share = useCallback(async () => {
    setBusy(true); setNote(null);
    try {
      await shareEvidencePack(records[0] ?? null, { title: packTitle, date: packDate, notes: records[0] ? imageNotes(records[0]) : [], summary: packSummary, originalSource: source });
    } catch { setNote("ApolloSG couldn't create the evidence pack. Try again."); }
    finally { setBusy(false); }
  }, [records, packTitle, packDate, packSummary, source]);

  if (src !== undefined && !source && deletedAt) {
    return (
      <View style={s.card} testID={`${testID}-deleted`}>
        <View style={s.header}>
          <View style={s.iconWrap}><Info size={20} color={colors.onSurface} /></View>
          <View style={s.headerInfo}>
            <Text style={s.title}>Original Source</Text>
            <Text style={s.subtitle} testID={`${testID}-deleted-note`}>{heldCopyDeletedNote(formatDateTime(deletedAt) || null)}</Text>
          </View>
        </View>
      </View>
    );
  }
  if (src !== undefined && !source && showMissing) {
    return (
      <View style={s.card} testID={`${testID}-missing`}>
        <View style={s.header}>
          <View style={s.iconWrap}><Info size={20} color={colors.onSurface} /></View>
          <View style={s.headerInfo}>
            <Text style={s.title}>Original Source</Text>
            <Text style={s.subtitle} testID={`${testID}-missing-note`}>
              Not provided: this phone doesn&apos;t hold the original of this case. What ApolloSG recorded about it is in the card at the top.
            </Text>
          </View>
        </View>
      </View>
    );
  }
  if (src === undefined || !source || !view || !shown) return null;

  const url = mode === "redacted" && source.url ? purposeLimitedUrl(source.url) : source.url ?? null;
  // What is actually different about the copy that left this device. Stated where the toggle is, so
  // "Redacted" never looks like it did nothing.
  const redaction = describeRedaction({
    original: view, redacted: redactView(view, redactInvestigationSecrets),
    url: source.url, sentUrl: source.url ? purposeLimitedUrl(source.url) : null,
    blackedOutRegions: records.reduce((n, r) => n + r.redactedRegions, 0),
    cropped: records.some((r) => r.cropped),
  });
  const sentCopyIdentical = !redaction.changed;
  const Icon = view.layout === "message" ? (KIND_ICON[source.kind] ?? MessageSquare) : LAYOUT_ICON[view.layout];

  // The original email is drawn from its own HTML; the copy that left this phone was its text, so Redacted shows that.
  const shownEmail = view.layout === "email" && mode === "original" ? email : null;
  const layoutProps: LayoutProps & { s: typeof a } = {
    view: shown, body: shown.body, url, record: source.data, images, side: mode === "side", email: shownEmail,
    onViewImage: setFull, s: a,
  };
  // Side by side only makes sense where there are two versions of a picture to compare.
  const modes: Mode[] = view.layout === "screenshot" && records.length ? ["original", "redacted", "side"] : ["original", "redacted"];

  return (
    <View style={s.card} testID={testID}>
      {/* ── Header ── */}
      <View style={s.header}>
        <View style={s.iconWrap}><Icon size={20} color={colors.onSurface} /></View>
        <View style={s.headerInfo}>
          <Text style={s.title}>Original Source</Text>
          <Text style={s.subtitle}>{view.title} · Preserved on this device · Unaltered</Text>
        </View>
        <InfoButton info={SOURCE_INFO} testID={`${testID}-info`} />
      </View>

      {/* ── Original / Redacted ── */}
      <View style={s.segmentRow}>
        <View style={s.segments}>
          {modes.map((m) => (
            <Pressable key={m} style={[s.segment, mode === m && s.segmentOn]} onPress={() => setMode(m)}
              accessibilityRole="tab" accessibilityState={{ selected: mode === m }} testID={`${testID}-mode-${m}`}>
              <Text style={[s.segmentText, mode === m && s.segmentTextOn]}>{MODE_LABEL[m]}</Text>
            </Pressable>
          ))}
        </View>
        <InfoButton info={MODE_INFO} testID={`${testID}-mode-info`} />
      </View>

      {/* ── What is different about the copy that was sent (stated on sight) ── */}
      {mode !== "original" ? (
        <View style={s.modeNotice} testID={`${testID}-redaction-notice`}>
          <Text style={s.modeNoticeTitle}>
            {sentCopyIdentical ? "Nothing needed hiding" : "What ApolloSG hid before sending"}
          </Text>
          <Text style={s.modeNoticeBody}>
            {sentCopyIdentical
              ? (records.some((r) => !r.checked)
                ? "No password, PIN or code could be read here, so nothing was blacked out. This copy is identical to the original."
                : "Apollo found no password, PIN or verification code in this material, so this copy is identical to the original above.")
              : `Blacked out or replaced on this copy: ${redaction.items.join(", ")}. Everything else — the sender, the links and the wording — is exactly as captured.`}
          </Text>
        </View>
      ) : null}

      {/* ── Email sub-tabs ── */}
      {view.layout === "email" ? (
        <View style={s.tabs}>
          {(["email", "headers", "details"] as EmailTab[]).map((t) => (
            <Pressable key={t} style={[s.tab, tab === t && s.tabOn]} onPress={() => setTab(t)}
              accessibilityRole="tab" accessibilityState={{ selected: tab === t }} testID={`${testID}-tab-${t}`}>
              <Text style={[s.tabText, tab === t && s.tabTextOn]}>{t === "email" ? "Email" : t === "headers" ? "Headers" : "Details"}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {/* ── The artefact ── */}
      {view.layout === "email" ? <EmailArtefact {...layoutProps} tab={tab} />
        : view.layout === "screenshot" ? <ScreenshotArtefact {...layoutProps} />
          : view.layout === "post" ? <PostArtefact {...layoutProps} />
            : <ConversationArtefact {...layoutProps} />}

      {/* ── Actions ── */}
      <View style={s.actions}>
        {images.length ? (
          <View style={s.action}><Button testID={`${testID}-fullscreen`} variant="secondary" label="View full screen" icon={<Maximize2 size={16} color={colors.brand} />} onPress={() => setFull(images[0])} /></View>
        ) : shownEmail && tab === "email" ? (
          <View style={s.action}><Button testID={`${testID}-email-fullscreen`} variant="secondary" label="View full screen" icon={<Maximize2 size={16} color={colors.brand} />} onPress={() => setEmailFull(true)} /></View>
        ) : null}
        {shown.body || url ? (
          <View style={s.action}><Button testID={`${testID}-copy`} variant="secondary" label="Copy text" icon={<CopyIcon size={16} color={colors.brand} />} onPress={copyText} /></View>
        ) : null}
      </View>
      {note ? <Text style={s.note} testID={`${testID}-note`}>{note}</Text> : null}

      {/* ── Source details ── */}
      <Pressable style={s.detailsToggle} onPress={() => setDetailsOpen((v) => !v)} testID={`${testID}-details-toggle`} accessibilityRole="button" accessibilityState={{ expanded: detailsOpen }}>
        <Text style={s.detailsTitle}>Source details</Text>
        {detailsOpen ? <ChevronDown size={18} color={colors.muted} /> : <ChevronRight size={18} color={colors.muted} />}
      </Pressable>
      {detailsOpen ? (
        <View style={s.details} testID={`${testID}-details`}>
          <FieldRows s={a} fields={[
            { label: "Type", value: view.title },
            ...(view.platform ? [{ label: "Platform", value: view.platform }] : []),
            { label: "Captured", value: `${source.origin === "this_device" ? "On this device" : "Saved from the investigation"} · ${new Date(source.capturedAt).toLocaleString()}` },
            { label: "Stored", value: "On this device only. Deleted when you delete this case." },
            ...(view.links.length ? [{ label: "Links", value: view.links.join("\n") }] : []),
          ]} />
          {phones?.length ? (
            <View style={s.phones} testID={`${testID}-phones`}>
              <Text style={s.phonesTitle}>Phone numbers in this material</Text>
              {phones.map((p) => <Text key={p.number} style={s.note} testID={`${testID}-phone-${p.number}`}>{phoneFindingLine(p)}</Text>)}
              <Text style={s.note}>Checked with ApolloSG&apos;s caller-reputation service. A number&apos;s reputation is one signal — it is never the verdict on its own.</Text>
            </View>
          ) : null}
          {records.flatMap(imageNotes).map((n) => <Text key={n} style={s.note}>{n}</Text>)}
          {confirmId ? (
            <View style={s.confirm} testID={`${testID}-remove-confirm`}>
              <Text style={s.confirmText}>Remove the original from this phone? The sent copy and the case notes stay. This can&apos;t be undone.</Text>
              <View style={s.actions}>
                <View style={s.action}><Button testID={`${testID}-remove-keep`} variant="secondary" label="Keep" onPress={() => setConfirmId(null)} /></View>
                <View style={s.action}><Button testID={`${testID}-remove-yes`} variant="danger" label="Remove" onPress={() => { const id = confirmId; setConfirmId(null); void removeOriginal(id).catch(() => setNote("ApolloSG couldn't remove the original.")); }} /></View>
              </View>
            </View>
          ) : (
            <View style={s.actions}>
              <View style={s.action}><Button testID={`${testID}-share`} variant="secondary" label={busy ? "Preparing…" : "Share evidence pack"} disabled={busy} icon={<Share2 size={16} color={colors.brand} />} onPress={() => void share()} accessibilityHint="Creates a PDF with the evidence and the case notes" /></View>
              {records.some((r) => r.originalUri) ? (
                <View style={s.action}><Button testID={`${testID}-remove`} variant="ghost" label="Remove original" icon={<Trash2 size={16} color={colors.brand} />} onPress={() => setConfirmId(records.find((r) => r.originalUri)?.id ?? null)} /></View>
              ) : null}
            </View>
          )}
        </View>
      ) : null}

      {/* ── What you are looking at ── */}
      <View style={s.banner} testID={`${testID}-banner`}>
        <Info size={16} color={colors.onSurfaceSecondary} />
        <View style={s.bannerInfo}>
          <Text style={s.bannerTitle}>{mode === "original" ? view.bannerTitle : mode === "side" ? "Original and sent copy, side by side" : "This is the copy ApolloSG sent"}</Text>
          <Text style={s.bannerBody}>
            {mode === "original" ? view.bannerBody
              : mode === "side" ? "On the left is the picture kept on this device. On the right is the copy that was sent, with any password, PIN or code blacked out. Tap either to see it full screen."
                : sentCopyIdentical ? "Nothing in this one needed hiding, so the copy sent for investigation is identical to the original."
                  : "Passwords, PINs and verification codes are blacked out or replaced. The sender, the links and everything else are exactly as captured."}
          </Text>
        </View>
      </View>

      {/* ── Full screen ── */}
      <Modal visible={!!full} animationType="fade" onRequestClose={() => setFull(null)} statusBarTranslucent>
        <View style={[s.viewer, { paddingTop: insets.top, paddingBottom: insets.bottom }]} testID={`${testID}-viewer`}>
          <View style={s.viewerBar}>
            <Text style={s.viewerTitle}>{full?.label}</Text>
            <Pressable onPress={() => setFull(null)} accessibilityRole="button" accessibilityLabel="Close full screen" hitSlop={12} style={s.viewerClose} testID={`${testID}-viewer-close`}><X size={22} color="#FFFFFF" /></Pressable>
          </View>
          {full ? <Image source={{ uri: full.uri }} style={{ flex: 1 }} resizeMode="contain" /> : null}
        </View>
      </Modal>

      {/* ── The email as it appeared, full screen (still inert) ── */}
      <Modal visible={emailFull && !!shownEmail} animationType="slide" onRequestClose={() => setEmailFull(false)} statusBarTranslucent>
        <View style={[s.emailViewer, { paddingTop: insets.top, paddingBottom: insets.bottom }]} testID={`${testID}-email-viewer`}>
          <View style={s.viewerBar}>
            <Text style={s.emailViewerTitle} numberOfLines={1}>{shown.subject ?? "Original email"}</Text>
            <Pressable onPress={() => setEmailFull(false)} accessibilityRole="button" accessibilityLabel="Close full screen" hitSlop={12} style={s.viewerClose} testID={`${testID}-email-viewer-close`}><X size={22} color={colors.onSurface} /></Pressable>
          </View>
          {shownEmail ? <InertEmailView email={shownEmail} style={{ flex: 1 }} /> : null}
        </View>
      </Modal>
    </View>
  );
}

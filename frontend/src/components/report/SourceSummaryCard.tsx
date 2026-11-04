// The compact top card of an investigation and a Threat Case: "What caused this, and when?" — the heading from the
// case's recorded origin, its time, and a short preview of the material itself. For what Apollo detected, the facts
// of the detection follow (From · Type · Detected by · Reason). No findings or verdicts: those are in the Findings
// Brief below; how the case got there is in History and DI.
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import Clock from "lucide-react-native/icons/clock";
import FileText from "lucide-react-native/icons/file-text";
import ImageIcon from "lucide-react-native/icons/image";
import Link from "lucide-react-native/icons/link";
import Mail from "lucide-react-native/icons/mail";
import MessageCircleMore from "lucide-react-native/icons/message-circle-more";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import Search from "lucide-react-native/icons/search";
import Shield from "lucide-react-native/icons/shield";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import Smartphone from "lucide-react-native/icons/smartphone";
import TriangleAlert from "lucide-react-native/icons/triangle-alert";
import React, { useEffect, useMemo, useState } from "react";
import { Image, Pressable, Text, useWindowDimensions, View, type StyleProp, type ViewStyle } from "react-native";

import { toneText, toneTint } from "@/src/components/ui";
import {
  DELETED_HERE, detectionFacts, emptyPreview, isAddress, originHeading, previewFromEvent, previewFromEvidence, previewFromOriginal, shortenMiddle,
  sourceOf, splitLine, type DetectionFact, type PreviewIcon, type SourcePreview,
} from "@/src/domain/caseSourceSummary";
import { callNumberOf } from "@/src/domain/numberDetails";
import { isEmailCase, NOT_PROVIDED } from "@/src/domain/emailRecord";
import { formatDateTime } from "@/src/domain/threatCase";
import { NumberDetails } from "./NumberDetails";
import type { ApolloState, PatrolEvent } from "@/src/domain/types";
import type { CaseOrigin, EvidenceItem } from "@/src/investigation/types";
import { listImageEvidence, subscribeImageEvidence, type ImageEvidenceRecord } from "@/src/store/imageEvidence";
import { getCaseOriginal, originalSourceDeletedAt, subscribeOriginalSource, type OriginalSource } from "@/src/store/originalSource";
import { fonts, makeStyles, radius, spacing, useTheme, type ThemeColors } from "@/src/theme";

type Icon = React.ComponentType<{ size: number; color: string }>;
const PREVIEW_ICON: Record<PreviewIcon, Icon> = {
  sms: MessageSquare, email: Mail, link: Link, call: Phone, file: FileText, picture: ImageIcon, app: Smartphone, device: Shield, item: FileText,
};
const FACT_ICON: Record<DetectionFact["id"], Icon> = { from: Phone, type: MessageSquare, detected_by: Clock, reason: ShieldCheck };

/** Remove extraction artefacts ([link], [image], [image: …]) from an email text summary for clean display. */
function cleanEmailSummary(text: string): string {
  return text
    .replace(/\[(?:link|image)[^\]]*\]/gi, "")
    .replace(/\[(?:encoded content|Unsubscribe link)\]/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

type CardTone = "sniffing" | "resting" | "ears_up" | "growling" | "barking";
/** What Apollo detected is tinted by how serious Apollo recorded it as. */
function detectedTone(state: ApolloState | undefined): CardTone {
  if (state === "barking" || state === "biting") return "barking";
  if (state === "growling" || state === "ears_up" || state === "resting") return state;
  return "sniffing";
}
const tint = (c: ThemeColors, tone: CardTone) => ({ sniffing: c.sniffingTint, resting: c.restingTint, ears_up: c.ears_upTint, growling: c.growlingTint, barking: c.barkingTint }[tone]);
const ink = (c: ThemeColors, tone: CardTone) => ({ sniffing: c.sniffingText, resting: c.restingText, ears_up: c.ears_upText, growling: c.growlingText, barking: c.barkingText }[tone]);

const useStyles = makeStyles((c) => ({
  card: { borderRadius: radius.lg, borderWidth: 0.25, borderColor: c.border, padding: spacing.md, gap: spacing.md },
  top: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  badge: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  headingWrap: { flex: 1, gap: 2 },
  heading: { fontFamily: fonts.displayBold, fontSize: 18, color: c.onSurface },
  time: { fontFamily: fonts.text, fontSize: 14, color: c.muted },
  tag: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  tagText: { fontFamily: fonts.textSemibold, fontSize: 11 },
  previewBox: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm },
  preview: { flexDirection: "row", gap: spacing.md },
  chevron: { alignSelf: "flex-end", minHeight: 22, justifyContent: "flex-end" },
  details: { gap: 4, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider },
  detail: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
  detailLabel: { fontFamily: fonts.textSemibold, color: c.onSurfaceSecondary },
  fullText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 21, color: c.onSurface, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider },
  expand: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, minHeight: 44, borderRadius: radius.md, backgroundColor: c.surface },
  expandText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brand },
  tile: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: c.surface, alignItems: "center", justifyContent: "center" },
  smsMark: { position: "absolute", fontFamily: fonts.textSemibold, fontSize: 8, letterSpacing: 0.3, color: c.onSurface, top: 15 },
  thumb: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: c.surface },
  previewText: { flex: 1, gap: 2 },
  line: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  facts: { flexDirection: "row", flexWrap: "wrap", rowGap: spacing.sm },
  fact: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs },
  factDivider: { borderLeftWidth: 1, borderLeftColor: c.divider, paddingLeft: spacing.md },
  factText: { flex: 1, gap: 1 },
  factLabel: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  factValue: { fontFamily: fonts.text, fontSize: 14, color: c.onSurface },
}));

/** The picture beside the preview: the picture itself when one was kept, else the kind of material. */
function PreviewTile({ icon, picture, kind, testID }: { icon: PreviewIcon; picture: string | null; kind: string; testID: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  if (picture) return <Image source={{ uri: picture }} style={s.thumb} resizeMode="cover" testID={`${testID}-image`} accessibilityLabel="Picture that was checked" />;
  const Glyph = PREVIEW_ICON[icon];
  return (
    <View style={s.tile} accessibilityLabel={kind} testID={`${testID}-icon`}>
      <Glyph size={icon === "sms" ? 30 : 22} color={colors.onSurface} />
      {icon === "sms" ? <Text style={s.smsMark}>SMS</Text> : null}
    </View>
  );
}

/** The preview box: tappable (to open it) only while it's folded; a plain box otherwise. */
function FoldBox({ foldable, onOpen, hint, style, testID, children }: {
  foldable: boolean; onOpen: () => void; hint: string; style: StyleProp<ViewStyle>; testID: string; children: React.ReactNode;
}) {
  if (!foldable) return <View style={style} testID={testID}>{children}</View>;
  return (
    <Pressable style={style} testID={testID} onPress={onOpen} accessibilityRole="button" accessibilityHint={hint} accessibilityState={{ expanded: false }}>
      {children}
    </Pressable>
  );
}


export function SourceSummaryCard({ origin, at, caseKeys, event, evidence, gates, simulated, testID }: {
  origin: CaseOrigin | null | undefined;
  /** When the case began: when it was submitted or detected. */
  at: string | null | undefined;
  /** Every key the case's original may be kept under (its event id and its investigation id). */
  caseKeys: (string | null | undefined)[];
  /** What the case recorded at intake, used when no original is kept on the device, and for what Apollo detected. */
  event?: PatrolEvent | null;
  /** The investigation's evidence list, used when nothing else is kept. */
  evidence?: EvidenceItem[];
  /** The investigation's gates: an Email Gate case is shown as an email even with only its evidence list. */
  gates?: string[] | null;
  /** The material itself, or an outside source behind the answer, was simulated in the preview. */
  simulated?: boolean;
  testID: string;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const [original, setOriginal] = useState<OriginalSource | null>(null);
  // Where an earlier version of ApolloSG deleted this phone's copy of the original (a rule since removed).
  const [deletedAt, setDeletedAt] = useState<string | null>(null);
  const [images, setImages] = useState<ImageEvidenceRecord[]>([]);
  const [open, setOpen] = useState(false);
  const keyList = caseKeys.filter((k): k is string => !!k).join("|");

  useEffect(() => {
    const keys = keyList ? keyList.split("|") : [];
    let live = true;
    const load = async () => {
      const found = await getCaseOriginal(keys).catch(() => null);
      let gone: string | null = null;
      if (!found) for (const key of keys) gone = gone ?? await originalSourceDeletedAt(key).catch(() => null);
      const pictures = new Map<string, ImageEvidenceRecord>();
      for (const key of keys) for (const r of await listImageEvidence(key).catch(() => [])) pictures.set(r.id, r);
      if (live) { setOriginal(found); setDeletedAt(gone); setImages([...pictures.values()]); }
    };
    void load();
    const offOriginal = subscribeOriginalSource(() => void load());
    const offImages = subscribeImageEvidence(() => void load());
    return () => { live = false; offOriginal(); offImages(); };
  }, [keyList]);

  const preview = useMemo<SourcePreview>(() => {
    const kind = images.length > 1 ? `${images.length} pictures` : "Picture";
    const pictureLines = [`Pictures: ${images.length}`];
    const local = original ? previewFromOriginal(original, images.length > 0, event, images.length)
      : images.length ? { kind, icon: "picture" as const, lines: pictureLines, fullLines: pictureLines, received: null, body: null, details: [{ label: "Type", value: kind }], recorded: true } : null;
    if (local?.recorded) return local;
    // Nothing recorded in the kept copy: what the case recorded at intake, then its evidence list. Whichever is used,
    // every line the kind of material always shows is there, "Not provided" where nothing recorded it.
    const fromEvent = event ? previewFromEvent(event) : null;
    if (fromEvent?.recorded) return fromEvent;
    const fromEvidence = evidence ? previewFromEvidence(evidence, isEmailCase(event, original, gates)) : null;
    if (fromEvidence?.recorded) return fromEvidence;
    return local ?? fromEvent ?? fromEvidence ?? emptyPreview();
  }, [original, images, event, evidence, gates]);

  const { heading, verb } = originHeading(origin);
  const when = formatDateTime(at);
  const picture = images[0]?.originalUri ?? images[0]?.sentUri ?? null;
  const email = preview.icon === "email";
  // A text message shows who sent it, when it arrived and the message itself, each "Not provided" where not recorded.
  const sms = preview.icon === "sms";
  // A call says when it came in, the same way.
  const call = preview.icon === "call";
  // Where it came from, on every case.
  const source = sourceOf(event, original);
  // Every source type opens: the full text, every summary line in full and everything else recorded about it.
  const expandable = true;
  const detected = origin === "apollo";
  const tone = detectedTone(event?.state);
  const facts = detected && event ? detectionFacts(event, original) : [];
  const callNumber = callNumberOf(original, event);
  const wide = width >= 600;
  // About two lines of a web address beside the tile at this screen width (the third line is slack for wrapping).
  const addressFit = Math.max(28, Math.floor((width - 184) / 7.5) * 2);
  const BadgeIcon = detected ? TriangleAlert : origin === "user" ? MessageCircleMore : Search;
  const badgeBg = detected ? tint(colors, tone) : origin === "user" ? colors.groupAccountsTint : colors.sniffingTint;
  const badgeFg = detected ? ink(colors, tone) : origin === "user" ? colors.groupAccounts : colors.sniffingText;

  return (
    <View style={[s.card, { backgroundColor: detected ? tint(colors, tone) : colors.surfaceSecondary }]} testID={testID}>
      <View style={s.top}>
        <View style={[s.badge, { backgroundColor: badgeBg }]}><BadgeIcon size={22} color={badgeFg} /></View>
        <View style={s.headingWrap}>
          <Text style={s.heading} testID={`${testID}-heading`}>{heading}</Text>
          {when ? <Text style={s.time} testID={`${testID}-time`}>{`${verb} ${when}`}</Text> : null}
        </View>
        {simulated ? (
          <View style={[s.tag, { backgroundColor: toneTint(colors, "neutral") }]} testID={`${testID}-simulated`}>
            <Text style={[s.tagText, { color: toneText(colors, "neutral") }]}>Simulated</Text>
          </View>
        ) : null}
      </View>
      {/* Folded, the card shows a short preview; tapping it opens everything recorded about the material (an email's
          text without its links). Only the folded card is tappable, so the open text stays selectable and the Hide
          button stays enabled. Every kind of material shows its own lines, "Not provided" where nothing recorded them. */}
      <FoldBox foldable={expandable && !open} onOpen={() => setOpen(true)} hint={email ? "Shows the full email" : "Shows more details"}
          style={s.previewBox} testID={`${testID}-preview`}>
          <View style={s.preview}>
            <PreviewTile icon={preview.icon} picture={picture} kind={preview.kind} testID={testID} />
            <View style={s.previewText}>
              {(open ? preview.fullLines : preview.lines).map((line, i) => {
                // A web address, folded: shortened in the middle to what fits this screen, so its start and end both show.
                const { label, value } = splitLine(preview.fullLines[i] ?? line);
                const lead = label ? `${label}: ` : "";
                const address = !open && isAddress(value);
                return (
                  <Text key={`${i}-${line}`} style={s.line} numberOfLines={open ? undefined : address ? 3 : 2} selectable={open} testID={`${testID}-line-${i}`}>
                    {address ? `${lead}${shortenMiddle(value, addressFit - lead.length)}` : line}
                  </Text>
                );
              })}
              {email || sms || call ? (
                <Text style={s.line} numberOfLines={open ? undefined : 2} testID={`${testID}-received`}>
                  {`Received: ${preview.received ? formatDateTime(preview.received) || preview.received : NOT_PROVIDED}`}
                </Text>
              ) : null}
              {email && (!open || !preview.body) ? (
                // The email's own words: a line of them folded (in full once opened), or why there are none.
                <Text style={s.line} numberOfLines={2} testID={`${testID}-message`}>
                  {`Message: ${preview.body ? cleanEmailSummary(preview.body).replace(/\s+/g, " ").trim() : deletedAt ? DELETED_HERE : NOT_PROVIDED}`}
                </Text>
              ) : !email && preview.body ? (
                <Text style={s.line} numberOfLines={open ? undefined : preview.body.includes("\n") ? 10 : 3} selectable={open} testID={`${testID}-body`}>{preview.body}</Text>
              ) : sms ? (
                <Text style={s.line} testID={`${testID}-message`}>
                  {`Message: ${deletedAt ? DELETED_HERE : NOT_PROVIDED}`}
                </Text>
              ) : null}
              <Text style={s.line} numberOfLines={open ? undefined : 2} selectable={open} testID={`${testID}-source`}>{`Source: ${source}`}</Text>
            </View>
            {expandable && !open ? <View style={s.chevron}><ChevronDown size={20} color={colors.brand} testID={`${testID}-expand`} /></View> : null}
          </View>
          {expandable && open ? (
            <>
              {email && preview.body ? <Text style={s.fullText} selectable testID={`${testID}-body`}>{cleanEmailSummary(preview.body)}</Text> : null}
              {preview.details.length ? (
                <View style={s.details} testID={`${testID}-details`}>
                  {preview.details.map((d, i) => (
                    <Text key={`${d.label}-${i}`} style={s.detail} selectable testID={`${testID}-detail-${i}`}>
                      <Text style={s.detailLabel}>{`${d.label}: `}</Text>{d.time ? formatDateTime(d.value) || d.value : d.value}
                    </Text>
                  ))}
                </View>
              ) : null}
              <Pressable onPress={() => setOpen(false)} style={s.expand} accessibilityRole="button" testID={`${testID}-collapse`}>
                <Text style={s.expandText}>{email ? "Hide the full email" : "Hide details"}</Text>
                <ChevronUp size={18} color={colors.brand} />
              </Pressable>
            </>
          ) : null}
        </FoldBox>
      {callNumber ? <NumberDetails number={callNumber} testID={`${testID}-number-details`} /> : null}
      {facts.length ? (
        <View style={s.facts} testID={`${testID}-facts`}>
          {facts.map((fact, i) => {
            // An email's sender and type are shown with the envelope, never the text-message bubble.
            const FactIcon = email && (fact.id === "from" || fact.id === "type") ? Mail : FACT_ICON[fact.id];
            return (
              <View key={fact.id} style={[s.fact, wide ? { flex: 1 } : { width: "50%" }, wide && i > 0 ? s.factDivider : null]} testID={`${testID}-fact-${fact.id}`}>
                <FactIcon size={20} color={colors.onSurfaceSecondary} />
                <View style={s.factText}>
                  <Text style={s.factLabel}>{fact.label}</Text>
                  <Text style={s.factValue} numberOfLines={2}>{fact.value}</Text>
                </View>
              </View>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

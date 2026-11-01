// The artefact itself, drawn the way it arrived: an email, a screenshot, a message thread, a chat or
// a post. Every value on screen comes from what Apollo captured — see domain/evidencePresentation.
// Nothing the source app displayed but Apollo never captured is drawn here.
// Inert Source Principle: links, numbers, addresses and buttons inside the source look as they did but do nothing
// when touched. Where a link really goes is evidence, listed separately under Details.
import Paperclip from "lucide-react-native/icons/paperclip";
import User from "lucide-react-native/icons/user";
import React from "react";
import { Image, Platform, Pressable, Text, View } from "react-native";

import { InertEmailView } from "./InertEmailView";
import type { ArtefactView } from "@/src/domain/evidencePresentation";
import { linksIn } from "@/src/domain/evidencePresentation";
import { NOT_PROVIDED } from "@/src/domain/emailRecord";
import { inertEmailNote, type InertEmail } from "@/src/domain/inertEmail";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

export interface ArtefactImage { uri: string; label: string }

export interface LayoutProps {
  view: ArtefactView;
  /** Artefact text in the mode being shown (original, or the copy that was sent). */
  body: string | null;
  url: string | null;
  /** Raw device/OS record, when that is what was captured. */
  record?: unknown;
  images: ArtefactImage[];
  /** Screenshots only: show the original and the sent copy next to each other. */
  side?: boolean;
  /** Email only: the kept original's own HTML, made inert — shown instead of its text when it has one. */
  email?: InertEmail | null;
  onViewImage: (image: ArtefactImage) => void;
}

/** Height of the email as it appeared, inside the card (it scrolls within; full screen shows all of it). */
export const EMAIL_VIEW_HEIGHT = 480;

const useStyles = makeStyles((c) => ({
  // ── Shared frame: the artefact sits inside a bordered "as received" surface ──
  frame: { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, backgroundColor: c.surfaceSecondary, overflow: "hidden" },
  frameHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.surfaceTertiary },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: c.navyTint },
  avatarText: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  headerInfo: { flex: 1, gap: 1 },
  headerName: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  headerMeta: { fontFamily: fonts.text, fontSize: 12, color: c.muted },

  // ── Conversation (message / chat) ──
  thread: { padding: spacing.md, gap: spacing.sm },
  dateChip: { alignSelf: "center", paddingHorizontal: spacing.md, paddingVertical: 3, borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  dateChipText: { fontFamily: fonts.textMedium, fontSize: 11, color: c.muted },
  bubble: { alignSelf: "flex-start", maxWidth: "92%", backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderTopLeftRadius: radius.sm, padding: spacing.md, gap: spacing.xs },
  bubbleText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  bubbleTime: { fontFamily: fonts.text, fontSize: 11, color: c.muted, alignSelf: "flex-end" },

  // ── Email ──
  emailFrom: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, borderBottomWidth: 1, borderBottomColor: c.border },
  emailBody: { padding: spacing.md, gap: spacing.sm },
  subject: { fontFamily: fonts.displayBold, fontSize: 16, lineHeight: 23, color: c.onSurface },
  bodyText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 23, color: c.onSurface },
  attachRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  attachName: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface, flex: 1 },
  sectionLabel: { fontFamily: fonts.textSemibold, fontSize: 11, letterSpacing: 0.4, color: c.muted, textTransform: "uppercase" },

  // ── Field rows (headers / details) ──
  fieldRow: { flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.xs },
  fieldLabel: { fontFamily: fonts.textMedium, fontSize: 13, color: c.muted, width: 92 },
  fieldValue: { flex: 1, fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
  mono: { fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }), fontSize: 12, lineHeight: 18, color: c.onSurface },

  // ── Screenshot ──
  shot: { width: "100%", aspectRatio: 3 / 4, maxHeight: 520, backgroundColor: c.surfaceTertiary },
  shotStrip: { flexDirection: "row", gap: spacing.sm, padding: spacing.sm },
  shotThumb: { width: 56, height: 72, borderRadius: radius.sm, backgroundColor: c.surfaceTertiary },
  sideRow: { flexDirection: "row", gap: spacing.sm, padding: spacing.sm },
  sideCol: { flex: 1, gap: spacing.xs },
  sideImage: { width: "100%", aspectRatio: 3 / 4, maxHeight: 360, borderRadius: radius.sm, backgroundColor: c.surfaceTertiary },
  sideCaption: { fontFamily: fonts.textMedium, fontSize: 11, lineHeight: 15, color: c.muted, textAlign: "center" },

  // ── Post ──
  postHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
  postBody: { paddingHorizontal: spacing.md, paddingBottom: spacing.md, gap: spacing.sm },
  postMedia: { width: "100%", aspectRatio: 4 / 3, backgroundColor: c.surfaceTertiary },

  link: { fontFamily: fonts.textMedium, color: c.brandPrimary, textDecorationLine: "underline" },
  empty: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.muted, padding: spacing.md },
  emailView: { height: EMAIL_VIEW_HEIGHT, borderRadius: radius.sm, borderWidth: 1, borderColor: c.border },
  inertNote: { fontFamily: fonts.text, fontSize: 12, lineHeight: 17, color: c.muted },
}));

type Styles = ReturnType<typeof useStyles>;

/** Captured text with its links drawn as links, exactly as written — inert: touching one does nothing. */
function InertText({ text, style, s, testID }: { text: string; style: object; s: Styles; testID?: string }) {
  const urls = linksIn(text);
  if (!urls.length) return <Text style={style} selectable testID={testID}>{text}</Text>;
  const pattern = new RegExp(`(${urls.map((u) => u.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return (
    <Text style={style} selectable testID={testID}>
      {text.split(pattern).map((part, i) => <Text key={i} style={urls.includes(part) ? s.link : undefined}>{part}</Text>)}
    </Text>
  );
}

/** Each link the email carried: what it displayed, and where it actually goes. */
export function emailLinkRows(email: InertEmail): string {
  return email.links.map((l) => `Displayed text: \u201c${l.text || "(no text)"}\u201d\nActual destination: ${l.href}`).join("\n\n");
}

function initial(name: string | null): string | null {
  // A letter only: a phone number must not be reduced to a random digit in an avatar.
  const ch = name?.trim().charAt(0);
  return ch && /[A-Za-z]/.test(ch) ? ch.toUpperCase() : null;
}

function Avatar({ name, s }: { name: string | null; s: Styles }) {
  const { colors } = useTheme();
  const letter = initial(name);
  return <View style={s.avatar}>{letter ? <Text style={s.avatarText}>{letter}</Text> : <User size={18} color={colors.onSurfaceSecondary} />}</View>;
}

export function FieldRows({ fields, s }: { fields: { label: string; value: string }[]; s: Styles }) {
  return <>{fields.map((f, i) => (
    <View key={`${f.label}-${i}`} style={s.fieldRow}>
      <Text style={s.fieldLabel}>{f.label}</Text>
      <Text style={s.fieldValue} selectable>{f.value}</Text>
    </View>
  ))}</>;
}

// ── Message / chat ────────────────────────────────────────────────────────────

/** The default layout: the thread as it arrived. Used for every type without one of its own. */
export function ConversationArtefact({ view, body, url, record, images, onViewImage, s }: LayoutProps & { s: Styles }) {
  const text = body ?? url ?? null;
  const hasRecord = record !== undefined && record !== null;
  // Nothing to attribute (a link, a file) → no sender strip: an empty header is noise, not evidence.
  const attribution = view.sender ?? view.platform ?? null;
  return (
    <View style={s.frame} testID="evidence-artefact-conversation">
      {attribution ? (
        <View style={s.frameHeader}>
          <Avatar name={view.sender} s={s} />
          <View style={s.headerInfo}>
            <Text style={s.headerName}>{attribution}</Text>
            {view.sender ? <Text style={s.headerMeta}>{view.platform ?? view.title}</Text> : null}
          </View>
        </View>
      ) : null}
      <View style={s.thread}>
        {view.occurredAt ? <View style={s.dateChip}><Text style={s.dateChipText}>{view.occurredAt}</Text></View> : null}
        {text ? (
          <View style={s.bubble}>
            <InertText text={text} style={s.bubbleText} s={s} testID="evidence-artefact-body" />
          </View>
        ) : null}
        {images.map((img) => (
          <Pressable key={img.uri} onPress={() => onViewImage(img)} style={[s.bubble, { padding: spacing.xs }]} accessibilityRole="imagebutton" accessibilityLabel={`View ${img.label}`}>
            <Image source={{ uri: img.uri }} style={{ width: 200, height: 150, borderRadius: radius.sm }} resizeMode="cover" />
          </Pressable>
        ))}
        {hasRecord ? (
          <View style={[s.bubble, { maxWidth: "100%" }]}>
            <Text style={s.sectionLabel}>Recorded by this device</Text>
            <Text style={s.mono} selectable testID="evidence-artefact-record">{JSON.stringify(record, null, 2)}</Text>
          </View>
        ) : null}
        {!text && !images.length && !hasRecord ? <Text style={s.empty}>No content was captured for this item.</Text> : null}
      </View>
    </View>
  );
}

// ── Email ─────────────────────────────────────────────────────────────────────

export function EmailArtefact({ view, body, images, email, onViewImage, tab, s }: LayoutProps & { tab: "email" | "headers" | "details"; s: Styles }) {
  const { colors } = useTheme();
  if (tab === "headers") {
    return (
      <View style={[s.frame, { padding: spacing.md }]} testID="evidence-artefact-headers">
        {view.fields.length ? <FieldRows fields={view.fields} s={s} /> : <Text style={s.empty}>No headers were captured with this email.</Text>}
      </View>
    );
  }
  if (tab === "details") {
    const rows = [
      email?.links.length ? { label: "Links", value: emailLinkRows(email) }
        : view.links.length ? { label: "Links", value: view.links.join("\n") } : null,
      view.attachments.length ? { label: "Attachments", value: view.attachments.join("\n") } : null,
      ...view.fields.filter((f) => /auth|provider|mailbox|spf|dkim|dmarc/i.test(f.label)),
    ].filter((r): r is { label: string; value: string } => !!r);
    return (
      <View style={[s.frame, { padding: spacing.md }]} testID="evidence-artefact-details">
        {rows.length ? <FieldRows fields={rows} s={s} /> : <Text style={s.empty}>Nothing beyond the message itself was captured.</Text>}
      </View>
    );
  }
  return (
    <View style={s.frame} testID="evidence-artefact-email">
      <View style={s.emailFrom}>
        <Avatar name={view.sender} s={s} />
        <View style={s.headerInfo}>
          <Text style={s.headerName} numberOfLines={2}>{view.sender ?? `From: ${NOT_PROVIDED}`}</Text>
          {view.recipient ? <Text style={s.headerMeta}>To: {view.recipient}</Text> : null}
          <Text style={s.headerMeta}>{view.occurredAt ?? `Received: ${NOT_PROVIDED}`}</Text>
        </View>
      </View>
      <View style={s.emailBody}>
        <Text style={s.subject} selectable>{view.subject ?? `Subject: ${NOT_PROVIDED}`}</Text>
        {/* The email as it appeared (its HTML, inert). Its text only when the kept original has no HTML part. */}
        {email ? <>
          <InertEmailView email={email} style={s.emailView} testID="evidence-artefact-email-html" />
          <Text style={s.inertNote} testID="evidence-artefact-email-inert-note">{inertEmailNote(email)}</Text>
        </> : body ? <InertText text={body} style={s.bodyText} s={s} testID="evidence-artefact-body" /> : <Text style={s.empty}>No message body was captured.</Text>}
        {images.map((img) => (
          <Pressable key={img.uri} onPress={() => onViewImage(img)} accessibilityRole="imagebutton" accessibilityLabel={`View ${img.label}`}>
            <Image source={{ uri: img.uri }} style={{ width: "100%", aspectRatio: 4 / 3, borderRadius: radius.sm }} resizeMode="contain" />
          </Pressable>
        ))}
        {view.attachments.length ? (
          <View>
            <Text style={s.sectionLabel}>Attachments ({view.attachments.length})</Text>
            {view.attachments.map((name) => (
              <View key={name} style={s.attachRow}>
                <Paperclip size={16} color={colors.onSurfaceSecondary} />
                <Text style={s.attachName} numberOfLines={1}>{name}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
    </View>
  );
}

// ── Screenshot ────────────────────────────────────────────────────────────────

export function ScreenshotArtefact({ view, body, images, side, onViewImage, s }: LayoutProps & { s: Styles }) {
  const [main, ...rest] = images;
  // The image's own proportions, read from the file — so the screenshot isn't letterboxed in a box
  // that was never its shape.
  const [ratio, setRatio] = React.useState<number | null>(null);
  React.useEffect(() => {
    setRatio(null);
    if (!main) return;
    Image.getSize(main.uri, (w, h) => { if (h > 0) setRatio(w / h); }, () => undefined);
  }, [main?.uri]);
  return (
    <View style={s.frame} testID="evidence-artefact-screenshot">
      {side ? (
        <View style={s.sideRow} testID="evidence-artefact-side">
          {images.map((img) => (
            <Pressable key={img.uri} style={s.sideCol} onPress={() => onViewImage(img)} accessibilityRole="imagebutton" accessibilityLabel={`View ${img.label} full screen`}>
              <Image source={{ uri: img.uri }} style={[s.sideImage, ratio ? { aspectRatio: ratio } : null]} resizeMode="contain" />
              <Text style={s.sideCaption}>{img.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : main ? (
        <Pressable onPress={() => onViewImage(main)} accessibilityRole="imagebutton" accessibilityLabel={`View ${main.label} full screen`} testID="evidence-artefact-image">
          <Image source={{ uri: main.uri }} style={[s.shot, ratio ? { aspectRatio: ratio } : null]} resizeMode="contain" />
        </Pressable>
      ) : <Text style={s.empty}>The image is no longer on this device.</Text>}
      {rest.length && !side ? (
        <View style={s.shotStrip}>
          {rest.map((img) => (
            <Pressable key={img.uri} onPress={() => onViewImage(img)} accessibilityRole="imagebutton" accessibilityLabel={`View ${img.label}`}>
              <Image source={{ uri: img.uri }} style={s.shotThumb} resizeMode="cover" />
            </Pressable>
          ))}
        </View>
      ) : null}
      {body ? (
        <View style={s.emailBody}>
          <Text style={s.sectionLabel}>Captured with the image</Text>
          <InertText text={body} style={s.bodyText} s={s} testID="evidence-artefact-body" />
        </View>
      ) : null}
      {view.occurredAt ? <View style={[s.emailBody, { paddingTop: 0 }]}><Text style={s.headerMeta}>{view.occurredAt}</Text></View> : null}
    </View>
  );
}

// ── Social post ───────────────────────────────────────────────────────────────

export function PostArtefact({ view, body, url, images, onViewImage, s }: LayoutProps & { s: Styles }) {
  return (
    <View style={s.frame} testID="evidence-artefact-post">
      <View style={s.postHeader}>
        <Avatar name={view.sender ?? view.platform} s={s} />
        <View style={s.headerInfo}>
          <Text style={s.headerName}>{view.sender ?? view.platform ?? `Account: ${NOT_PROVIDED}`}</Text>
          <Text style={s.headerMeta}>{[view.platform, view.occurredAt].filter(Boolean).join(" · ")}</Text>
        </View>
      </View>
      <View style={s.postBody}>
        {body ? <InertText text={body} style={s.bodyText} s={s} testID="evidence-artefact-body" /> : null}
        {url && !body?.includes(url) ? <Text style={[s.bodyText, s.link]} selectable>{url}</Text> : null}
        {!body && !url ? <Text style={s.empty}>No post content was captured.</Text> : null}
      </View>
      {images.map((img) => (
        <Pressable key={img.uri} onPress={() => onViewImage(img)} accessibilityRole="imagebutton" accessibilityLabel={`View ${img.label}`}>
          <Image source={{ uri: img.uri }} style={s.postMedia} resizeMode="cover" />
        </Pressable>
      ))}
    </View>
  );
}

export { useStyles as useArtefactStyles };
